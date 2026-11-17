"""Claves, sesiones del panel, límites de uso y limpieza de datos personales."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import string
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .db import ahora

DURACION_SESION = timedelta(hours=8)
LARGO_MINIMO_CLAVE = 10
_N, _R, _P = 2**14, 8, 1


def crear_hash(clave: str) -> str:
    sal = secrets.token_bytes(16)
    derivada = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P)
    return f"scrypt${base64.b64encode(sal).decode()}${base64.b64encode(derivada).decode()}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, sal, derivada = guardado.split("$")
        calculada = hashlib.scrypt(clave.encode(), salt=base64.b64decode(sal), n=_N, r=_R, p=_P)
        return hmac.compare_digest(calculada, base64.b64decode(derivada))
    except ValueError:
        return False


def problema_de_clave(clave: str, correo: str = "") -> str | None:
    """Devuelve qué le falta a una contraseña, o None si sirve."""
    if len(clave) < LARGO_MINIMO_CLAVE:
        return f"La contraseña debe tener al menos {LARGO_MINIMO_CLAVE} caracteres."
    if correo and clave.lower() in correo.lower():
        return "La contraseña no puede ser parte del correo."
    if not (re.search(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", clave) and re.search(r"\d", clave)):
        return "La contraseña debe combinar letras y números."
    return None


def clave_temporal() -> str:
    """Contraseña de un solo uso para un usuario nuevo o restablecido: la persona la cambia al entrar."""
    alfabeto = string.ascii_letters + string.digits
    while True:
        clave = "".join(secrets.choice(alfabeto) for _ in range(14))
        if problema_de_clave(clave) is None:
            return clave


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def abrir_sesion(conexion: sqlite3.Connection, usuario_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expira = (datetime.now(timezone.utc) + DURACION_SESION).strftime("%Y-%m-%dT%H:%M:%SZ")
    conexion.execute("DELETE FROM sesiones WHERE expira < ?", (ahora(),))
    conexion.execute("INSERT INTO sesiones (token_hash, usuario_id, expira) VALUES (?, ?, ?)", (_hash_token(token), usuario_id, expira))
    conexion.commit()
    return token


def usuario_de_sesion(conexion: sqlite3.Connection, token: str | None) -> dict | None:
    if not token:
        return None
    fila = conexion.execute(
        """SELECT u.id, u.correo, u.nombre, u.rol, u.dependencia, u.debe_cambiar_clave FROM sesiones s
           JOIN usuarios u ON u.id = s.usuario_id
           WHERE s.token_hash = ? AND s.expira > ? AND u.activo = 1""",
        (_hash_token(token), ahora()),
    ).fetchone()
    return dict(fila) if fila else None


def cerrar_sesion(conexion: sqlite3.Connection, token: str | None) -> None:
    if token:
        conexion.execute("DELETE FROM sesiones WHERE token_hash = ?", (_hash_token(token),))
        conexion.commit()


def cerrar_sesiones_de(conexion: sqlite3.Connection, usuario_id: int) -> None:
    conexion.execute("DELETE FROM sesiones WHERE usuario_id = ?", (usuario_id,))
    conexion.commit()


class Limitador:
    """Ventanas deslizantes en memoria. Con varios servidores habría que moverlo a un almacén compartido."""

    def __init__(self, reglas: list[tuple[int, int]]):
        self.reglas = reglas  # (máximo de usos, segundos de la ventana)
        self._usos: dict[str, deque[float]] = defaultdict(deque)
        self._candado = threading.Lock()
        self._ultima_limpieza = time.monotonic()

    def permitir(self, clave: str) -> bool:
        momento = time.monotonic()
        ventana_mayor = max(segundos for _, segundos in self.reglas)
        with self._candado:
            self._limpiar(momento, ventana_mayor)
            usos = self._usos[clave]
            while usos and momento - usos[0] > ventana_mayor:
                usos.popleft()
            for maximo, segundos in self.reglas:
                if sum(1 for uso in usos if momento - uso <= segundos) >= maximo:
                    return False
            usos.append(momento)
            return True

    def _limpiar(self, momento: float, ventana: int) -> None:
        """Olvida a quien no ha preguntado en toda la ventana, para que la memoria no crezca sin fin."""
        if momento - self._ultima_limpieza < 600:
            return
        self._ultima_limpieza = momento
        for clave in [c for c, usos in self._usos.items() if not usos or momento - usos[-1] > ventana]:
            del self._usos[clave]

    def reiniciar(self, clave: str) -> None:
        with self._candado:
            self._usos.pop(clave, None)


_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Documentos y códigos: 1.144.555.777, 1 144 555 777, 1144555777, 202012345. No toca fechas ni listas cortas,
# ni valores en dinero («$1.300.000», «1.300.000 pesos»), que sí importan para responder.
_DOCUMENTO = re.compile(
    r"(?<![\d$-])(?<!\$ )(?:\d{1,3}(?:[. ]\d{3}){2,3}|\d{6,12})(?![\d-])(?!\s*(?:pesos|cop|millones)\b)", re.IGNORECASE
)
_CELULAR = re.compile(r"(?<!\d)(?:\+?57[ -]?)?3\d{2}[ -]\d{3}[ -]?\d{4}(?!\d)")
_NOMBRE = re.compile(r"\b((?i:me llamo|mi nombre es|soy))\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*)")
# «Soy Estudiante de Medicina» describe un rol, no un nombre.
_ROLES = {
    "estudiante", "aspirante", "egresado", "egresada", "graduado", "graduada", "profesor", "profesora", "docente",
    "bachiller", "admitido", "admitida", "padre", "madre", "acudiente", "funcionario", "funcionaria", "monitor",
    "monitora", "representante", "nuevo", "nueva", "de", "del", "la", "el", "un", "una",
}


def _nombre(coincidencia: re.Match) -> str:
    inicio, palabras = coincidencia.group(1), coincidencia.group(2)
    if inicio.lower() == "soy" and palabras.split()[0].lower() in _ROLES:
        return coincidencia.group(0)
    return f"{inicio} [nombre]"


def anonimizar(texto: str) -> str:
    """Quita correos, celulares, números de documento o código y nombres antes de guardar o enviar una pregunta."""
    texto = _CORREO.sub("[correo]", texto)
    texto = _CELULAR.sub("[número]", texto)
    texto = _DOCUMENTO.sub("[número]", texto)
    return _NOMBRE.sub(_nombre, texto)
