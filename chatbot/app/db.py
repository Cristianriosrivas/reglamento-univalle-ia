"""
Base de datos del asistente (SQLite para la demo).

Un contenido publicado sigue respondiendo con su versión vigente mientras alguien prepara un cambio:
los cambios sin publicar viven en la columna `pendiente`, y solo llegan al público al publicarlos.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

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
    tipo TEXT NOT NULL CHECK (tipo IN ('articulo', 'faq', 'fecha', 'contacto')),
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
    clave_hash TEXT NOT NULL
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

CREATE TABLE IF NOT EXISTS metricas (
    dia TEXT NOT NULL,
    clave TEXT NOT NULL,
    valor INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (dia, clave)
);

CREATE TABLE IF NOT EXISTS vectores (
    contenido_id INTEGER PRIMARY KEY REFERENCES contenidos(id),
    huella TEXT NOT NULL,
    vector BLOB NOT NULL
);
"""


def ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hoy() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def conectar(ruta: Path | str) -> sqlite3.Connection:
    """Abre una conexión por petición: SQLite no admite compartirla entre hilos con seguridad."""
    conexion = sqlite3.connect(ruta, check_same_thread=False, timeout=15)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def inicializar(ruta: Path | str) -> None:
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    conexion = conectar(ruta)
    conexion.execute("PRAGMA journal_mode = WAL")
    conexion.executescript(ESQUEMA)
    conexion.close()


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
