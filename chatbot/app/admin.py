"""
Tareas de administración desde la terminal.

    python -m app.admin crear --correo persona@correounivalle.edu.co --nombre "Nombre"
    python -m app.admin actualizar-fuentes

La contraseña se pide sin mostrarla en pantalla y nunca queda en el historial de la terminal.
"""
from __future__ import annotations

import argparse
import getpass
import sys

import httpx

from . import fuentes_web as W
from . import usuarios as U
from .config import cargar_config
from .contenidos import ErrorContenido
from .db import conectar, inicializar


def main(argumentos: list[str] | None = None) -> int:
    lector = argparse.ArgumentParser(prog="python -m app.admin", description="Administración del asistente")
    ordenes = lector.add_subparsers(dest="orden", required=True)
    crear = ordenes.add_parser("crear", help="Crea una cuenta de administración")
    crear.add_argument("--correo", required=True)
    crear.add_argument("--nombre", required=True)
    ordenes.add_parser("actualizar-fuentes", help="Vuelve a leer ahora todas las páginas oficiales activas")
    datos = lector.parse_args(argumentos)

    config = cargar_config()
    inicializar(config.ruta_db)
    conexion = conectar(config.ruta_db)
    try:
        if datos.orden == "crear":
            clave = getpass.getpass("Contraseña (mínimo 10 caracteres, letras y números): ")
            if clave != getpass.getpass("Repítela: "):
                print("Las contraseñas no coinciden.", file=sys.stderr)
                return 1
            U.crear_administrador(conexion, datos.correo, datos.nombre, clave)
            print("Cuenta de administración creada.")
        else:
            http = httpx.Client(timeout=W.ESPERA)
            for fila in conexion.execute("SELECT id, nombre FROM fuentes_web WHERE activa = 1").fetchall():
                resultado = W.sincronizar(conexion, fila["id"], http, config.dominios_web)
                print(f"{fila['nombre']}: {resultado}")
    except ErrorContenido as error:
        print(error.mensaje, file=sys.stderr)
        return 1
    finally:
        conexion.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
