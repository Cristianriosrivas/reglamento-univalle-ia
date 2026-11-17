"""Cada prueba recibe una copia de una base ya cargada: la carga inicial solo se hace una vez."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Antes de importar la app: las pruebas nunca usan claves reales, no gastan llamadas ni salen a internet,
# y siempre ven el mismo «hoy» para que las fechas y novedades venzan igual en cualquier máquina.
for _variable in ("COHERE_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY", "IA_LOCAL_URL", "IA_LOCAL_MODELO"):
    os.environ[_variable] = ""
os.environ["FUENTES_WEB"] = "0"
os.environ["BUSQUEDA_SEMANTICA"] = "ninguna"
os.environ["ENTORNO"] = "desarrollo"
os.environ["FECHA_HOY"] = "2026-11-16"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, semilla  # noqa: E402
from app.asistente import Asistente  # noqa: E402
from app.config import Config  # noqa: E402
from app.main import crear_app  # noqa: E402

CLAVE = "clave-de-prueba"
ORIGEN_EXTERNO = "http://localhost:5500"


@pytest.fixture(scope="session")
def base_cargada(tmp_path_factory) -> Path:
    ruta = tmp_path_factory.mktemp("base") / "plantilla.db"
    db.inicializar(ruta)
    conexion = db.conectar(ruta)
    semilla.cargar_si_vacia(conexion, CLAVE)
    conexion.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conexion.close()
    return ruta


@pytest.fixture
def ruta_db(base_cargada, tmp_path) -> Path:
    destino = tmp_path / "prueba.db"
    shutil.copy(base_cargada, destino)
    return destino


@pytest.fixture
def conexion(ruta_db):
    abierta = db.conectar(ruta_db)
    yield abierta
    abierta.close()


@pytest.fixture
def config(ruta_db) -> Config:
    return Config(
        ruta_db=ruta_db, proveedores=[], busqueda_semantica="ninguna", demo_clave=CLAVE,
        limite_minuto=1000, limite_dia=10000, origenes=[ORIGEN_EXTERNO], fuentes_web=False,
    )


@pytest.fixture
def asistente(config) -> Asistente:
    return Asistente(config)


@pytest.fixture
def cliente(config):
    with TestClient(crear_app(config)) as abierto:
        yield abierto


def entrar(cliente: TestClient, correo: str, clave: str = CLAVE) -> TestClient:
    cliente.cookies.clear()
    respuesta = cliente.post("/api/panel/entrar", json={"correo": correo, "clave": clave}, headers={"X-Panel": "1"})
    assert respuesta.status_code == 200, respuesta.text
    return cliente
