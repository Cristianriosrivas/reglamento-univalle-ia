"""
Ciclo de vida del contenido: borrador -> revisión -> publicado, con historial y restauración.

Reglas clave:
- Un editor solo toca lo de su dependencia; solo un aprobador o administrador publica.
- Editar algo publicado no lo cambia para el público hasta que se aprueba el cambio.
- Cada acción deja una versión con su autor, para saber quién cambió qué y poder volver atrás.
"""
from __future__ import annotations

import json
import re
import sqlite3

from .busqueda import Documento
from .config import DEPENDENCIAS, PUBLICOS, TIPOS
from .db import ahora

CAMPOS = ("titulo", "texto", "capitulo", "numero", "url", "inicio", "fin", "destacada", "reemplaza", "publico")
# El artículo más largo cargado (cupos especiales de la Resolución 080) tiene 20.000 caracteres.
MAX_TEXTO = 40_000
_LIMITES = {"titulo": (3, 300), "texto": (3, MAX_TEXTO)}
_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErrorContenido(Exception):
    """Algo que se le puede explicar a la persona que usa el panel."""

    def __init__(self, mensaje: str, codigo: int = 400):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo


def puede_editar(usuario: dict, dependencia: str) -> bool:
    return usuario["rol"] == "admin" or usuario["dependencia"] == dependencia


def puede_publicar(usuario: dict, dependencia: str) -> bool:
    return usuario["rol"] == "admin" or (usuario["rol"] == "aprobador" and usuario["dependencia"] == dependencia)


def _exigir_edicion(usuario: dict, fila: sqlite3.Row) -> None:
    if not puede_editar(usuario, fila["dependencia"]):
        raise ErrorContenido(f"Este contenido es de {fila['dependencia']}: solo esa dependencia puede cambiarlo.", 403)


def _exigir_publicacion(usuario: dict, fila: sqlite3.Row) -> None:
    if not puede_publicar(usuario, fila["dependencia"]):
        raise ErrorContenido("Solo un aprobador de la dependencia o un administrador puede hacer esto.", 403)


def validar(datos: dict, tipo: str) -> dict:
    limpio = {c: datos[c] for c in CAMPOS if c in datos}
    for campo, (minimo, maximo) in _LIMITES.items():
        valor = str(limpio.get(campo, "")).strip()
        if not minimo <= len(valor) <= maximo:
            nombre = {"titulo": "El título", "texto": "El texto"}[campo]
            raise ErrorContenido(f"{nombre} debe tener entre {minimo} y {maximo} caracteres.")
        limpio[campo] = valor
    url = str(limpio.get("url") or "").strip()
    if url and not url.startswith(("https://", "http://")):
        raise ErrorContenido("El enlace debe empezar por https://")
    limpio["url"] = url
    for campo in ("inicio", "fin"):
        valor = (limpio.get(campo) or "").strip() or None
        if valor and not _FECHA.match(valor):
            raise ErrorContenido("Las fechas deben tener el formato AAAA-MM-DD.")
        limpio[campo] = valor
    if tipo == "fecha" and not limpio["fin"]:
        raise ErrorContenido("Una fecha necesita día de finalización: así deja de mostrarse cuando pase.")
    if limpio["inicio"] and limpio["fin"] and limpio["inicio"] > limpio["fin"]:
        raise ErrorContenido("La fecha de inicio no puede ser posterior a la de finalización.")
    limpio["destacada"] = 1 if limpio.get("destacada") else 0
    limpio["publico"] = limpio.get("publico") or "todos"
    if limpio["publico"] not in PUBLICOS:
        raise ErrorContenido("Elige para quién es el contenido: todos, aspirantes o estudiantes.")
    limpio["capitulo"] = str(limpio.get("capitulo") or "").strip()
    for campo in ("numero", "reemplaza"):
        valor = limpio.get(campo)
        if valor is not None and not isinstance(valor, int):
            raise ErrorContenido("Hay un dato numérico no válido.")
    return limpio


def _exigir_referencias(conexion: sqlite3.Connection, datos: dict) -> None:
    reemplaza, fuente = datos.get("reemplaza"), datos.get("fuente_id")
    if reemplaza and not conexion.execute("SELECT 1 FROM contenidos WHERE id = ?", (reemplaza,)).fetchone():
        raise ErrorContenido("La norma que se quiere reemplazar no existe.")
    if fuente and not conexion.execute("SELECT 1 FROM fuentes WHERE id = ?", (fuente,)).fetchone():
        raise ErrorContenido("La fuente indicada no existe.")


def _registrar(conexion: sqlite3.Connection, contenido_id: int, accion: str, datos: dict, autor: str) -> None:
    conexion.execute(
        "INSERT INTO versiones (contenido_id, accion, datos, autor, fecha) VALUES (?, ?, ?, ?, ?)",
        (contenido_id, accion, json.dumps(datos, ensure_ascii=False), autor, ahora()),
    )


def _vigente(fila: sqlite3.Row) -> dict:
    return {c: fila[c] for c in CAMPOS}


def _buscar(conexion: sqlite3.Connection, contenido_id: int) -> sqlite3.Row:
    fila = conexion.execute("SELECT * FROM contenidos WHERE id = ?", (contenido_id,)).fetchone()
    if not fila:
        raise ErrorContenido("Ese contenido no existe.", 404)
    return fila


def crear(conexion: sqlite3.Connection, datos: dict, usuario: dict) -> int:
    tipo, dependencia = datos.get("tipo"), datos.get("dependencia") or usuario["dependencia"]
    if tipo not in TIPOS:
        raise ErrorContenido("Tipo de contenido no válido.")
    if dependencia not in DEPENDENCIAS:
        raise ErrorContenido("Elige una dependencia válida.")
    if not puede_editar(usuario, dependencia):
        raise ErrorContenido(f"Solo puedes crear contenido de {usuario['dependencia']}.", 403)
    limpio = validar(datos, tipo)
    _exigir_referencias(conexion, {**limpio, "fuente_id": datos.get("fuente_id")})
    cursor = conexion.execute(
        """INSERT INTO contenidos (tipo, dependencia, fuente_id, titulo, texto, capitulo, numero, url, inicio, fin,
                                   destacada, reemplaza, publico, estado, actualizado_por, actualizado_en)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'borrador', ?, ?)""",
        (
            tipo, dependencia, datos.get("fuente_id"), limpio["titulo"], limpio["texto"], limpio["capitulo"],
            limpio.get("numero"), limpio["url"], limpio["inicio"], limpio["fin"], limpio["destacada"],
            limpio.get("reemplaza"), limpio["publico"], usuario["nombre"], ahora(),
        ),
    )
    _registrar(conexion, cursor.lastrowid, "creado", limpio, usuario["nombre"])
    conexion.commit()
    return cursor.lastrowid


def editar(conexion: sqlite3.Connection, contenido_id: int, datos: dict, usuario: dict) -> None:
    fila = _buscar(conexion, contenido_id)
    _exigir_edicion(usuario, fila)
    # Se parte del cambio pendiente, si existe, para no perder una edición anterior aún sin publicar.
    base = json.loads(fila["pendiente"]) if fila["pendiente"] else _vigente(fila)
    limpio = validar({**base, **datos}, fila["tipo"])
    _exigir_referencias(conexion, limpio)
    marca = (usuario["nombre"], ahora(), contenido_id)
    if fila["estado"] == "publicado":
        conexion.execute(
            """UPDATE contenidos SET pendiente = ?, pendiente_estado = 'borrador', nota_revision = '',
               actualizado_por = ?, actualizado_en = ? WHERE id = ?""",
            (json.dumps(limpio, ensure_ascii=False), *marca),
        )
    else:
        conexion.execute(
            """UPDATE contenidos SET titulo = ?, texto = ?, capitulo = ?, numero = ?, url = ?, inicio = ?, fin = ?,
               destacada = ?, reemplaza = ?, publico = ?, estado = 'borrador', nota_revision = '',
               actualizado_por = ?, actualizado_en = ? WHERE id = ?""",
            (
                limpio["titulo"], limpio["texto"], limpio["capitulo"], limpio.get("numero"), limpio["url"],
                limpio["inicio"], limpio["fin"], limpio["destacada"], limpio.get("reemplaza"), limpio["publico"], *marca,
            ),
        )
    _registrar(conexion, contenido_id, "editado", limpio, usuario["nombre"])
    conexion.commit()


def enviar_a_revision(conexion: sqlite3.Connection, contenido_id: int, usuario: dict) -> None:
    fila = _buscar(conexion, contenido_id)
    _exigir_edicion(usuario, fila)
    if fila["pendiente"]:
        conexion.execute("UPDATE contenidos SET pendiente_estado = 'revision' WHERE id = ?", (contenido_id,))
    elif fila["estado"] == "borrador":
        conexion.execute("UPDATE contenidos SET estado = 'revision' WHERE id = ?", (contenido_id,))
    else:
        raise ErrorContenido("No hay cambios por enviar a revisión.")
    _registrar(conexion, contenido_id, "enviado a revisión", _vigente(fila), usuario["nombre"])
    conexion.commit()


def publicar(conexion: sqlite3.Connection, contenido_id: int, usuario: dict) -> None:
    fila = _buscar(conexion, contenido_id)
    _exigir_publicacion(usuario, fila)
    if not fila["pendiente"] and fila["estado"] not in ("borrador", "revision"):
        raise ErrorContenido("No hay cambios por publicar.")
    datos = json.loads(fila["pendiente"]) if fila["pendiente"] else _vigente(fila)
    conexion.execute(
        """UPDATE contenidos SET titulo = ?, texto = ?, capitulo = ?, numero = ?, url = ?, inicio = ?, fin = ?,
           destacada = ?, reemplaza = ?, publico = ?, estado = 'publicado', pendiente = NULL, pendiente_estado = NULL,
           nota_revision = '', actualizado_por = ?, actualizado_en = ? WHERE id = ?""",
        (
            datos["titulo"], datos["texto"], datos["capitulo"], datos.get("numero"), datos["url"], datos["inicio"],
            datos["fin"], datos["destacada"], datos.get("reemplaza"), datos.get("publico") or "todos",
            usuario["nombre"], ahora(), contenido_id,
        ),
    )
    if datos.get("reemplaza"):
        # La versión anterior de la norma deja de responderse, pero se conserva como antecedente.
        conexion.execute("UPDATE contenidos SET reemplazado_por = ? WHERE id = ?", (contenido_id, datos["reemplaza"]))
    _registrar(conexion, contenido_id, "publicado", datos, usuario["nombre"])
    conexion.commit()
    _avisar_cambio(conexion)


def devolver(conexion: sqlite3.Connection, contenido_id: int, nota: str, usuario: dict) -> None:
    fila = _buscar(conexion, contenido_id)
    _exigir_publicacion(usuario, fila)
    nota = (nota or "").strip()[:500]
    if len(nota) < 5:
        raise ErrorContenido("Explica en al menos 5 caracteres qué hay que corregir.")
    if fila["pendiente_estado"] == "revision":
        conexion.execute("UPDATE contenidos SET pendiente_estado = 'borrador', nota_revision = ? WHERE id = ?", (nota, contenido_id))
    elif fila["estado"] == "revision":
        conexion.execute("UPDATE contenidos SET estado = 'borrador', nota_revision = ? WHERE id = ?", (nota, contenido_id))
    else:
        raise ErrorContenido("Este contenido no está en revisión.")
    _registrar(conexion, contenido_id, f"devuelto: {nota}", _vigente(fila), usuario["nombre"])
    conexion.commit()


def descartar_cambios(conexion: sqlite3.Connection, contenido_id: int, usuario: dict) -> None:
    fila = _buscar(conexion, contenido_id)
    _exigir_edicion(usuario, fila)
    if not fila["pendiente"]:
        raise ErrorContenido("No hay cambios sin publicar.")
    conexion.execute(
        "UPDATE contenidos SET pendiente = NULL, pendiente_estado = NULL, nota_revision = '' WHERE id = ?", (contenido_id,)
    )
    _registrar(conexion, contenido_id, "cambios descartados", _vigente(fila), usuario["nombre"])
    conexion.commit()


def archivar(conexion: sqlite3.Connection, contenido_id: int, usuario: dict) -> None:
    """Retira el contenido del asistente sin borrarlo."""
    fila = _buscar(conexion, contenido_id)
    _exigir_publicacion(usuario, fila)
    conexion.execute(
        "UPDATE contenidos SET estado = 'archivado', pendiente = NULL, pendiente_estado = NULL WHERE id = ?", (contenido_id,)
    )
    conexion.execute("UPDATE contenidos SET reemplazado_por = NULL WHERE reemplazado_por = ?", (contenido_id,))
    _registrar(conexion, contenido_id, "archivado", _vigente(fila), usuario["nombre"])
    conexion.commit()
    _avisar_cambio(conexion)


def _avisar_cambio(conexion: sqlite3.Connection) -> None:
    from .ajustes import subir_version

    subir_version(conexion)


def restaurar(conexion: sqlite3.Connection, contenido_id: int, version_id: int, usuario: dict) -> None:
    """Recupera una versión anterior como cambio pendiente: se revisa antes de volver al público."""
    fila = _buscar(conexion, contenido_id)
    _exigir_edicion(usuario, fila)
    version = conexion.execute(
        "SELECT datos FROM versiones WHERE id = ? AND contenido_id = ?", (version_id, contenido_id)
    ).fetchone()
    if not version:
        raise ErrorContenido("Esa versión no existe.", 404)
    editar(conexion, contenido_id, json.loads(version["datos"]), usuario)
    _registrar(conexion, contenido_id, "versión restaurada", json.loads(version["datos"]), usuario["nombre"])
    conexion.commit()


_SELECT_DOC = """
    SELECT c.*, COALESCE(f.nombre, fw.nombre) AS fuente, COALESCE(f.url, fw.url) AS fuente_url FROM contenidos c
    LEFT JOIN fuentes f ON f.id = c.fuente_id
    LEFT JOIN fuentes_web fw ON c.origen = 'web' AND c.origen_ref LIKE 'web' || fw.id || ':%'
"""


def _documento(fila: sqlite3.Row, datos: dict | None = None, borrador: bool = False) -> Documento:
    origen = datos or fila
    return Documento(
        id=fila["id"], tipo=fila["tipo"], titulo=origen["titulo"], texto=origen["texto"],
        dependencia=fila["dependencia"], capitulo=origen["capitulo"], numero=origen["numero"],
        fuente=fila["fuente"] or "", url=origen["url"] or fila["fuente_url"] or "",
        inicio=origen["inicio"], fin=origen["fin"], destacada=bool(origen["destacada"]), borrador=borrador,
        publico=(origen["publico"] if "publico" in origen.keys() else None) or fila["publico"] or "todos",
        origen=fila["origen"], actualizado=fila["actualizado_en"][:10],
    )


def _vencida(documento: Documento, hoy: str) -> bool:
    """Las fechas y las novedades dejan de mostrarse solas cuando pasa su día final."""
    return documento.tipo in ("fecha", "novedad") and bool(documento.fin) and documento.fin < hoy


def documentos_publicos(conexion: sqlite3.Connection, hoy: str) -> list[Documento]:
    filas = conexion.execute(_SELECT_DOC + " WHERE c.estado = 'publicado' AND c.reemplazado_por IS NULL").fetchall()
    return [d for d in map(_documento, filas) if not _vencida(d, hoy)]


def documentos_de_prueba(conexion: sqlite3.Connection, hoy: str) -> list[Documento]:
    """Lo que vería el público si se publicara todo lo que está en borrador o en revisión."""
    filas = conexion.execute(_SELECT_DOC + " WHERE c.estado != 'archivado'").fetchall()
    reemplazados = {f["reemplaza"] for f in filas if f["reemplaza"]}
    documentos = []
    for fila in filas:
        if fila["id"] in reemplazados or fila["reemplazado_por"]:
            continue
        if fila["pendiente"]:
            documentos.append(_documento(fila, json.loads(fila["pendiente"]), borrador=True))
        else:
            documentos.append(_documento(fila, borrador=fila["estado"] != "publicado"))
    return [d for d in documentos if not _vencida(d, hoy)]


def aviso_destacado(conexion: sqlite3.Connection, hoy: str) -> dict | None:
    """La novedad vigente que una dependencia marcó para mostrarse arriba en el chat, si la hay."""
    fila = conexion.execute(
        """SELECT titulo, url FROM contenidos WHERE tipo = 'novedad' AND estado = 'publicado' AND destacada = 1
           AND (fin IS NULL OR fin >= ?) AND (inicio IS NULL OR inicio <= ?) ORDER BY inicio DESC, id DESC LIMIT 1""",
        (hoy, hoy),
    ).fetchone()
    return dict(fila) if fila else None
