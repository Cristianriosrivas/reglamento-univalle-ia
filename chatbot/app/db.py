"""
Base de datos del asistente (SQLite).

Un contenido publicado sigue respondiendo con su versión vigente mientras alguien prepara un cambio:
los cambios sin publicar viven en la columna `pendiente`, y solo llegan al público al publicarlos.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("asistente.db")

VERSION_ESQUEMA = 2

ESQUEMA = """
CREATE TABLE IF NOT EXISTS fuentes (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    dependencia TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    nota TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS contenidos (
    id INTEGER PRIMARY KEY,
    tipo TEXT NOT NULL CHECK (tipo IN ('articulo', 'faq', 'pagina', 'novedad', 'fecha', 'contacto')),
    dependencia TEXT NOT NULL,
    fuente_id INTEGER REFERENCES fuentes(id),
    titulo TEXT NOT NULL,
    texto TEXT NOT NULL,
    capitulo TEXT NOT NULL DEFAULT '',
    numero INTEGER,
    url TEXT NOT NULL DEFAULT '',
    inicio TEXT,
    fin TEXT,
    destacada INTEGER NOT NULL DEFAULT 0,
    publico TEXT NOT NULL DEFAULT 'todos' CHECK (publico IN ('todos', 'aspirante', 'estudiante')),
    origen TEXT NOT NULL DEFAULT 'manual',
    origen_ref TEXT NOT NULL DEFAULT '',
    estado TEXT NOT NULL DEFAULT 'borrador' CHECK (estado IN ('borrador', 'revision', 'publicado', 'archivado')),
    reemplaza INTEGER REFERENCES contenidos(id),
    reemplazado_por INTEGER REFERENCES contenidos(id),
    pendiente TEXT,
    pendiente_estado TEXT CHECK (pendiente_estado IN ('borrador', 'revision')),
    nota_revision TEXT NOT NULL DEFAULT '',
    actualizado_por TEXT NOT NULL DEFAULT '',
    actualizado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contenidos_estado ON contenidos(estado, tipo);
CREATE INDEX IF NOT EXISTS idx_contenidos_origen ON contenidos(origen, origen_ref);

CREATE TABLE IF NOT EXISTS versiones (
    id INTEGER PRIMARY KEY,
    contenido_id INTEGER NOT NULL REFERENCES contenidos(id),
    accion TEXT NOT NULL,
    datos TEXT NOT NULL,
    autor TEXT NOT NULL,
    fecha TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versiones_contenido ON versiones(contenido_id, id DESC);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    correo TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('admin', 'aprobador', 'editor')),
    dependencia TEXT NOT NULL DEFAULT '',
    clave_hash TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    debe_cambiar_clave INTEGER NOT NULL DEFAULT 0,
    creado_en TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sesiones (
    token_hash TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    expira TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sin_respuesta (
    id INTEGER PRIMARY KEY,
    clave TEXT NOT NULL UNIQUE,
    pregunta TEXT NOT NULL,
    veces INTEGER NOT NULL DEFAULT 1,
    primera TEXT NOT NULL,
    ultima TEXT NOT NULL,
    resuelta INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS valoraciones (
    id INTEGER PRIMARY KEY,
    fecha TEXT NOT NULL,
    dia TEXT NOT NULL,
    util INTEGER NOT NULL,
    tipo TEXT NOT NULL DEFAULT '',
    pregunta TEXT NOT NULL DEFAULT '',
    fuentes TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_valoraciones_dia ON valoraciones(dia);

CREATE TABLE IF NOT EXISTS metricas (
    dia TEXT NOT NULL,
    clave TEXT NOT NULL,
    valor INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dia, clave)
);

CREATE TABLE IF NOT EXISTS ajustes (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fuentes_web (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    nombre TEXT NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('pagina', 'noticias')),
    dependencia TEXT NOT NULL,
    publico TEXT NOT NULL DEFAULT 'todos',
    activa INTEGER NOT NULL DEFAULT 1,
    huella TEXT NOT NULL DEFAULT '',
    piezas INTEGER NOT NULL DEFAULT 0,
    ultima_revision TEXT NOT NULL DEFAULT '',
    ultimo_cambio TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS vectores (
    contenido_id INTEGER PRIMARY KEY REFERENCES contenidos(id),
    huella TEXT NOT NULL,
    vector BLOB NOT NULL
);
"""


def _zona() -> timezone:
    """Colombia no cambia de horario: UTC-5 todo el año. Configurable para otras sedes o pruebas."""
    try:
        horas = float(os.environ.get("ZONA_HORARIA_UTC", "-5"))
    except ValueError:
        horas = -5.0
    return timezone(timedelta(hours=horas))


def ahora() -> str:
    """Momento exacto, en UTC: es lo que se guarda en historiales y sesiones."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hoy() -> str:
    """El día en Colombia. `FECHA_HOY` lo fija para pruebas o para ensayar una demostración."""
    return os.environ.get("FECHA_HOY") or datetime.now(_zona()).strftime("%Y-%m-%d")


def sumar_dias(dia: str, dias: int) -> str:
    return (datetime.strptime(dia, "%Y-%m-%d") + timedelta(days=dias)).strftime("%Y-%m-%d")


def conectar(ruta: Path | str) -> sqlite3.Connection:
    """Abre una conexión por petición: SQLite no admite compartirla entre hilos con seguridad."""
    conexion = sqlite3.connect(ruta, check_same_thread=False, timeout=15)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def inicializar(ruta: Path | str) -> None:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists():
        _respaldar_si_es_antigua(ruta)
    conexion = conectar(ruta)
    conexion.execute("PRAGMA journal_mode = WAL")
    conexion.executescript(ESQUEMA)
    conexion.execute(f"PRAGMA user_version = {VERSION_ESQUEMA}")
    conexion.commit()
    conexion.close()


def _respaldar_si_es_antigua(ruta: Path) -> None:
    """Una base de la versión anterior de la demo se guarda aparte y se crea una nueva con el contenido inicial."""
    conexion = conectar(ruta)
    version = conexion.execute("PRAGMA user_version").fetchone()[0]
    tiene_datos = conexion.execute("SELECT 1 FROM sqlite_master WHERE name = 'contenidos'").fetchone()
    conexion.close()
    if version >= VERSION_ESQUEMA or not tiene_datos:
        return
    respaldo = ruta.with_name(f"{ruta.stem}.v{version}.bak")
    shutil.move(ruta, respaldo)
    for extra in ("-wal", "-shm"):
        anexo = Path(f"{ruta}{extra}")
        if anexo.exists():
            anexo.unlink()
    logger.warning("La base de datos era de una versión anterior; se guardó en %s y se crea una nueva", respaldo.name)


def sumar_metrica(conexion: sqlite3.Connection, clave: str, cantidad: int = 1) -> None:
    conexion.execute(
        """INSERT INTO metricas (dia, clave, valor) VALUES (?, ?, ?)
           ON CONFLICT (dia, clave) DO UPDATE SET valor = valor + excluded.valor""",
        (hoy(), clave, cantidad),
    )
    conexion.commit()


def leer_metrica(conexion: sqlite3.Connection, clave: str, dia: str | None = None) -> int:
    fila = conexion.execute("SELECT valor FROM metricas WHERE dia = ? AND clave = ?", (dia or hoy(), clave)).fetchone()
    return fila["valor"] if fila else 0
