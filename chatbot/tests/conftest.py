"""Cada prueba recibe una copia de una base ya cargada: la carga inicial solo se hace una vez."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Antes de importar la app: las pruebas nunca deben usar la clave real ni gastar llamadas.
os.environ["COHERE_API_KEY"] = ""

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
        ruta_db=ruta_db, cohere_api_key="", demo_clave=CLAVE, limite_minuto=1000, limite_dia=10000,
        origenes=[ORIGEN_EXTERNO],
    )


@pytest.fixture
def asistente(config) -> Asistente:
    return Asistente(config)


@pytest.fixture
def cliente(config):
    with TestClient(crear_app(config)) as abierto:
        yield abierto


def entrar(cliente: TestClient, correo: str) -> TestClient:
    cliente.cookies.clear()
    respuesta = cliente.post("/api/panel/entrar", json={"correo": correo, "clave": CLAVE}, headers={"X-Panel": "1"})
    assert respuesta.status_code == 200, respuesta.text
    return cliente
