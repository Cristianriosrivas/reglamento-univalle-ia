"""Gestión de cuentas del panel: altas, roles, desactivación y contraseñas temporales."""
from __future__ import annotations

import re
import sqlite3

from . import seguridad as S
from .config import DEPENDENCIAS, ROLES
from .contenidos import ErrorContenido
from .db import ahora

_CORREO = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")


def listar(conexion: sqlite3.Connection) -> list[dict]:
    filas = conexion.execute(
        "SELECT id, correo, nombre, rol, dependencia, activo, debe_cambiar_clave, creado_en FROM usuarios ORDER BY activo DESC, nombre"
    )
    return [dict(f) for f in filas]


def _validar(datos: dict) -> dict:
    nombre = str(datos.get("nombre") or "").strip()
    rol = datos.get("rol")
    dependencia = str(datos.get("dependencia") or "").strip()
    if not 3 <= len(nombre) <= 80:
        raise ErrorContenido("El nombre debe tener entre 3 y 80 caracteres.")
    if rol not in ROLES:
        raise ErrorContenido("Elige un rol válido.")
    if rol != "admin" and dependencia not in DEPENDENCIAS:
        raise ErrorContenido("Los editores y aprobadores necesitan una dependencia.")
    return {"nombre": nombre, "rol": rol, "dependencia": "" if rol == "admin" else dependencia}


def crear(conexion: sqlite3.Connection, datos: dict) -> tuple[int, str]:
    """Crea la cuenta con una contraseña temporal, que se muestra una sola vez y se cambia al entrar."""
    correo = str(datos.get("correo") or "").strip().lower()
    if not _CORREO.match(correo):
        raise ErrorContenido("Escribe un correo válido.")
    if conexion.execute("SELECT 1 FROM usuarios WHERE correo = ?", (correo,)).fetchone():
        raise ErrorContenido("Ya existe una cuenta con ese correo.")
    limpio = _validar(datos)
    temporal = S.clave_temporal()
    cursor = conexion.execute(
        """INSERT INTO usuarios (correo, nombre, rol, dependencia, clave_hash, activo, debe_cambiar_clave, creado_en)
           VALUES (?, ?, ?, ?, ?, 1, 1, ?)""",
        (correo, limpio["nombre"], limpio["rol"], limpio["dependencia"], S.crear_hash(temporal), ahora()),
    )
    conexion.commit()
    return cursor.lastrowid, temporal


def _buscar(conexion: sqlite3.Connection, usuario_id: int) -> sqlite3.Row:
    fila = conexion.execute("SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    if not fila:
        raise ErrorContenido("Ese usuario no existe.", 404)
    return fila


def _admins_activos(conexion: sqlite3.Connection) -> int:
    return conexion.execute("SELECT COUNT(*) FROM usuarios WHERE rol = 'admin' AND activo = 1").fetchone()[0]


def actualizar(conexion: sqlite3.Connection, usuario_id: int, datos: dict, quien: dict) -> None:
    fila = _buscar(conexion, usuario_id)
    limpio = _validar({**dict(fila), **{k: v for k, v in datos.items() if k in ("nombre", "rol", "dependencia")}})
    activo = int(bool(datos.get("activo", fila["activo"])))
    era_admin_activo = fila["rol"] == "admin" and fila["activo"]
    if era_admin_activo and (limpio["rol"] != "admin" or not activo) and _admins_activos(conexion) <= 1:
        raise ErrorContenido("Debe quedar al menos un administrador activo.")
    if usuario_id == quien["id"] and not activo:
        raise ErrorContenido("No puedes desactivar tu propia cuenta.")
    conexion.execute(
        "UPDATE usuarios SET nombre = ?, rol = ?, dependencia = ?, activo = ? WHERE id = ?",
        (limpio["nombre"], limpio["rol"], limpio["dependencia"], activo, usuario_id),
    )
    conexion.commit()
    if not activo or limpio["rol"] != fila["rol"] or limpio["dependencia"] != fila["dependencia"]:
        # Los permisos cambiaron: la persona vuelve a entrar con los nuevos.
        S.cerrar_sesiones_de(conexion, usuario_id)


def restablecer_clave(conexion: sqlite3.Connection, usuario_id: int) -> str:
    _buscar(conexion, usuario_id)
    temporal = S.clave_temporal()
    conexion.execute(
        "UPDATE usuarios SET clave_hash = ?, debe_cambiar_clave = 1 WHERE id = ?", (S.crear_hash(temporal), usuario_id)
    )
    conexion.commit()
    S.cerrar_sesiones_de(conexion, usuario_id)
    return temporal


def cambiar_propia_clave(conexion: sqlite3.Connection, usuario_id: int, actual: str, nueva: str) -> None:
    fila = _buscar(conexion, usuario_id)
    if not S.verificar_clave(actual, fila["clave_hash"]):
        raise ErrorContenido("La contraseña actual no es correcta.", 403)
    if actual == nueva:
        raise ErrorContenido("La contraseña nueva debe ser distinta de la actual.")
    problema = S.problema_de_clave(nueva, fila["correo"])
    if problema:
        raise ErrorContenido(problema)
    conexion.execute(
        "UPDATE usuarios SET clave_hash = ?, debe_cambiar_clave = 0 WHERE id = ?", (S.crear_hash(nueva), usuario_id)
    )
    conexion.commit()


def crear_administrador(conexion: sqlite3.Connection, correo: str, nombre: str, clave: str) -> int:
    """Para la primera cuenta de un servidor nuevo (ver `python -m app.admin`)."""
    correo = correo.strip().lower()
    if not _CORREO.match(correo):
        raise ErrorContenido("Escribe un correo válido.")
    problema = S.problema_de_clave(clave, correo)
    if problema:
        raise ErrorContenido(problema)
    if conexion.execute("SELECT 1 FROM usuarios WHERE correo = ?", (correo,)).fetchone():
        raise ErrorContenido("Ya existe una cuenta con ese correo.")
    cursor = conexion.execute(
        """INSERT INTO usuarios (correo, nombre, rol, dependencia, clave_hash, activo, debe_cambiar_clave, creado_en)
           VALUES (?, ?, 'admin', '', ?, 1, 0, ?)""",
        (correo, nombre.strip() or "Administración", S.crear_hash(clave), ahora()),
    )
    conexion.commit()
    return cursor.lastrowid
