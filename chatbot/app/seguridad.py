"""Claves, sesiones del panel, límites de uso y limpieza de datos personales."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from .db import ahora

DURACION_SESION = timedelta(hours=8)
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
        """SELECT u.id, u.correo, u.nombre, u.rol, u.dependencia FROM sesiones s
           JOIN usuarios u ON u.id = s.usuario_id WHERE s.token_hash = ? AND s.expira > ?""",
        (_hash_token(token), ahora()),
    ).fetchone()
    return dict(fila) if fila else None


def cerrar_sesion(conexion: sqlite3.Connection, token: str | None) -> None:
    if token:
        conexion.execute("DELETE FROM sesiones WHERE token_hash = ?", (_hash_token(token),))
        conexion.commit()


class Limitador:
    """Ventanas deslizantes en memoria. Con varios servidores habría que moverlo a un almacén compartido."""

    def __init__(self, reglas: list[tuple[int, int]]):
        self.reglas = reglas  # (máximo de usos, segundos de la ventana)
        self._usos: dict[str, deque[float]] = defaultdict(deque)
        self._candado = threading.Lock()

    def permitir(self, clave: str) -> bool:
        momento = time.monotonic()
        ventana_mayor = max(segundos for _, segundos in self.reglas)
        with self._candado:
            usos = self._usos[clave]
            while usos and momento - usos[0] > ventana_mayor:
                usos.popleft()
            for maximo, segundos in self.reglas:
                if sum(1 for uso in usos if momento - uso <= segundos) >= maximo:
                    return False
            usos.append(momento)
            return True

    def reiniciar(self, clave: str) -> None:
        with self._candado:
            self._usos.pop(clave, None)


_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_NUMERO_LARGO = re.compile(r"\b\d[\d .\-]{5,}\d\b")
_NOMBRE = re.compile(r"\b((?i:me llamo|mi nombre es|soy))\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)*")


def anonimizar(texto: str) -> str:
    """Quita correos, números de documento o código y nombres antes de guardar una pregunta."""
    texto = _CORREO.sub("[correo]", texto)
    texto = _NUMERO_LARGO.sub("[número]", texto)
    return _NOMBRE.sub(lambda m: f"{m.group(1)} [nombre]", texto)
