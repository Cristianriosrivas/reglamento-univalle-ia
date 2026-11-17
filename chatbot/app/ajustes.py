"""Ajustes que un administrador cambia desde el panel, sin tocar código ni reiniciar el servidor."""
from __future__ import annotations

import json
import sqlite3

from .contenidos import ErrorContenido

MAX_SUGERENCIAS = 6

DEFECTOS: dict[str, object] = {
    "nombre": "Asistente Univalle",
    "bienvenida": (
        "¡Hola! Soy el asistente virtual de la Universidad del Valle. Te ayudo con admisiones, matrícula, reglamento, "
        "trámites, grados y novedades. ¿Quieres estudiar en Univalle o ya eres estudiante?"
    ),
    "sugerencias_aspirante": [
        "¿Cómo me inscribo a un programa de pregrado?",
        "¿Cuánto cuesta la inscripción?",
        "¿Me devuelven el dinero de la inscripción?",
        "¿Qué necesito al ser admitido?",
    ],
    "sugerencias_estudiante": [
        "¿Cuál es el plazo para cancelar una asignatura?",
        "¿Qué pasa si incurro en bajo rendimiento académico por segunda vez?",
        "¿Cómo funciona la evaluación de habilitación?",
        "¿Qué novedades hay?",
    ],
    "ia_activa": True,
    "max_llamadas_ia_dia": None,  # None = el valor de la configuración del servidor
    "version_contenido": 0,
}

EDITABLES = ("nombre", "bienvenida", "sugerencias_aspirante", "sugerencias_estudiante", "ia_activa", "max_llamadas_ia_dia")


def leer(conexion: sqlite3.Connection, clave: str):
    fila = conexion.execute("SELECT valor FROM ajustes WHERE clave = ?", (clave,)).fetchone()
    return json.loads(fila["valor"]) if fila else DEFECTOS.get(clave)


def todos(conexion: sqlite3.Connection) -> dict:
    guardados = {f["clave"]: json.loads(f["valor"]) for f in conexion.execute("SELECT clave, valor FROM ajustes")}
    return {clave: guardados.get(clave, defecto) for clave, defecto in DEFECTOS.items()}


def _guardar(conexion: sqlite3.Connection, clave: str, valor) -> None:
    conexion.execute(
        "INSERT INTO ajustes (clave, valor) VALUES (?, ?) ON CONFLICT (clave) DO UPDATE SET valor = excluded.valor",
        (clave, json.dumps(valor, ensure_ascii=False)),
    )


def actualizar(conexion: sqlite3.Connection, cambios: dict) -> dict:
    for clave, valor in cambios.items():
        if clave not in EDITABLES:
            raise ErrorContenido(f"El ajuste «{clave}» no se puede cambiar.")
        _guardar(conexion, clave, _validar(clave, valor))
    conexion.commit()
    subir_version(conexion)
    return todos(conexion)


def _validar(clave: str, valor):
    if clave == "nombre":
        valor = str(valor or "").strip()
        if not 3 <= len(valor) <= 40:
            raise ErrorContenido("El nombre debe tener entre 3 y 40 caracteres.")
    elif clave == "bienvenida":
        valor = str(valor or "").strip()
        if not 10 <= len(valor) <= 400:
            raise ErrorContenido("La bienvenida debe tener entre 10 y 400 caracteres.")
    elif clave.startswith("sugerencias_"):
        if isinstance(valor, str):
            valor = valor.splitlines()
        valor = [str(v).strip() for v in valor if str(v).strip()][:MAX_SUGERENCIAS]
        if any(len(v) > 120 for v in valor):
            raise ErrorContenido("Cada sugerencia debe tener como máximo 120 caracteres.")
    elif clave == "ia_activa":
        valor = bool(valor)
    elif clave == "max_llamadas_ia_dia":
        if valor in (None, ""):
            return None
        if not isinstance(valor, int) or not 0 <= valor <= 100_000:
            raise ErrorContenido("El tope de IA debe ser un número entre 0 y 100.000.")
    return valor


def version(conexion: sqlite3.Connection) -> int:
    return int(leer(conexion, "version_contenido") or 0)


def subir_version(conexion: sqlite3.Connection) -> None:
    """Cada publicación cambia la versión: todos los procesos del servidor rehacen su índice en la siguiente pregunta."""
    _guardar(conexion, "version_contenido", version(conexion) + 1)
    conexion.commit()
