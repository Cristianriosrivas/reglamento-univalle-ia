"""
Fuentes oficiales en la web: páginas de la universidad y su canal de noticias.

El asistente las vuelve a leer cada cierto tiempo y, si algo cambió, actualiza lo que sabe y deja constancia en el
historial. Así responde con lo último que publicó la universidad sin que nadie tenga que copiarlo a mano.

Seguridad: solo se leen direcciones https de los dominios permitidos (por defecto, univalle.edu.co), con límite de
tamaño y de tiempo, y siguiendo redirecciones únicamente dentro de esos dominios.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from . import ajustes
from .config import DEPENDENCIAS, PUBLICOS, Config
from .contenidos import ErrorContenido
from .db import ahora, conectar, hoy, sumar_dias

logger = logging.getLogger("asistente.web")

MAX_BYTES = 3_000_000
ESPERA = 25
LARGO_PIEZA = 1400
DIAS_VIGENCIA_NOTICIA = 45
AUTOR = "Actualización automática"

# Páginas oficiales con las que arranca la demo: (nombre, dirección, tipo, dependencia, público).
FUENTES_INICIALES = (
    ("Preguntas frecuentes de Registro Académico", "https://registro.univalle.edu.co/preguntas-frecuentes/", "pagina", "Registro Académico", "todos"),
    ("Matrícula académica de pregrado", "https://registro.univalle.edu.co/estudiantes/matricula-pregrado/", "pagina", "Registro Académico", "estudiante"),
    ("Fechas de matrícula de pregrado", "https://registro.univalle.edu.co/estudiantes/fecha-de-matricula-pregrado/", "pagina", "Registro Académico", "estudiante"),
    ("Cancelación de semestre de pregrado", "https://registro.univalle.edu.co/m_canc_sem_preg/", "pagina", "Registro Académico", "estudiante"),
    ("Reingreso y traslado de pregrado", "https://registro.univalle.edu.co/estudiantes/estudiante-reingreso-pregrado/", "pagina", "Registro Académico", "estudiante"),
    ("Reingresos, traslados y transferencias", "https://registro.univalle.edu.co/reingresos-traslados-y-transferencias/", "pagina", "Registro Académico", "todos"),
    ("Grados de pregrado", "https://registro.univalle.edu.co/estudiantes/pregrado-grados/", "pagina", "Registro Académico", "estudiante"),
    ("Certificados académicos", "https://registro.univalle.edu.co/certificados/", "pagina", "Registro Académico", "todos"),
    ("Carné estudiantil", "https://registro.univalle.edu.co/estudiantes/carne-estudiantil/", "pagina", "Registro Académico", "estudiante"),
    ("Bajos rendimientos académicos", "https://registro.univalle.edu.co/bajos-rendimientos-academicos/", "pagina", "Registro Académico", "estudiante"),
    ("Solicitudes académicas de pregrado", "https://registro.univalle.edu.co/estudiantes/pregrado-solicitudes-academicas/", "pagina", "Registro Académico", "estudiante"),
    ("Paz y salvo", "https://registro.univalle.edu.co/paz-y-salvo/", "pagina", "Registro Académico", "estudiante"),
    ("Estudiantes admitidos de pregrado", "https://registro.univalle.edu.co/estudiantes-admitidos-pregrado/", "pagina", "Admisiones", "aspirante"),
    ("Calendarios académicos", "https://registro.univalle.edu.co/calendarios/", "pagina", "Registro Académico", "todos"),
    ("Noticias de la Universidad del Valle", "https://www.univalle.edu.co/?format=feed&type=rss", "noticias", "Comunicaciones", "todos"),
)


@dataclass
class Pieza:
    clave: str
    titulo: str
    texto: str
    url: str
    inicio: str | None = None
    fin: str | None = None


# ---------------------------------------------------------------- descarga segura


def permitida(url: str, dominios: list[str]) -> bool:
    partes = urlparse(url)
    host = (partes.hostname or "").lower()
    return partes.scheme == "https" and any(host == d or host.endswith("." + d) for d in dominios)


def descargar(http: httpx.Client, url: str, dominios: list[str]) -> tuple[str, bytes, str]:
    """Devuelve (dirección final, contenido, tipo). Solo sigue redirecciones que se queden en dominios permitidos."""
    actual = url
    for _ in range(4):
        if not permitida(actual, dominios):
            raise ErrorContenido("Solo se pueden leer páginas https de la universidad.")
        with http.stream("GET", actual, headers={"User-Agent": "AsistenteUnivalle/1.0"}, timeout=ESPERA, follow_redirects=False) as r:
            if r.status_code in (301, 302, 303, 307, 308):
                actual = urljoin(actual, r.headers.get("location", ""))
                continue
            if r.status_code != 200:
                raise ErrorContenido(f"La página respondió con el código {r.status_code}.")
            partes, total = [], 0
            for bloque in r.iter_bytes():
                total += len(bloque)
                if total > MAX_BYTES:
                    raise ErrorContenido("La página es demasiado grande.")
                partes.append(bloque)
            return actual, b"".join(partes), r.headers.get("content-type", "")
    raise ErrorContenido("La página redirige demasiadas veces.")


# ---------------------------------------------------------------- de HTML a texto


class _Texto(HTMLParser):
    """Convierte HTML en texto con estructura: títulos, listas y enlaces útiles se conservan."""

    _OMITIR = {"script", "style", "nav", "header", "footer", "form", "noscript", "svg", "button", "iframe"}
    _BLOQUE = {"p", "div", "br", "tr", "section", "article", "table", "ul", "ol", "dd", "dt", "blockquote"}

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.partes: list[str] = []
        self.omitiendo = 0
        self.enlace: str | None = None
        self.texto_enlace: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._OMITIR:
            self.omitiendo += 1
        elif self.omitiendo:
            return
        elif tag in ("h1", "h2", "h3", "h4"):
            self.partes.append("\n## ")
        elif tag == "li":
            self.partes.append("\n- ")
        elif tag in self._BLOQUE:
            self.partes.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            self.enlace = urljoin(self.base, href) if href and not href.startswith(("#", "mailto:", "javascript:")) else None
            self.texto_enlace = []

    def handle_endtag(self, tag):
        if tag in self._OMITIR:
            self.omitiendo = max(0, self.omitiendo - 1)
        elif self.omitiendo:
            return
        elif tag in ("h1", "h2", "h3", "h4", "p", "li", "tr"):
            self.partes.append("\n")
        elif tag == "a" and self.enlace:
            texto = " ".join("".join(self.texto_enlace).split())
            # Los enlaces a documentos y formularios son útiles en una respuesta: se conservan.
            if texto and self.enlace.startswith("http") and len(texto) <= 90:
                self.partes.append(f" ({self.enlace})")
            self.enlace = None

    def handle_data(self, data):
        if not self.omitiendo:
            self.partes.append(data)
            if self.enlace is not None:
                self.texto_enlace.append(data)

    def resultado(self) -> str:
        texto = "".join(self.partes)
        lineas = [" ".join(l.split()) for l in texto.splitlines()]
        limpias = []
        for linea in lineas:
            if linea in ("##", "-", "- ", ""):
                if limpias and limpias[-1] != "":
                    limpias.append("")
                continue
            limpias.append(linea)
        return "\n".join(limpias).strip()


def html_a_texto(contenido: str, base: str = "") -> str:
    for etiqueta in ("main", "article"):
        coincide = re.search(rf"<{etiqueta}\b.*?</{etiqueta}>", contenido, flags=re.S | re.I)
        if coincide:
            contenido = coincide.group(0)
            break
    lector = _Texto(base)
    lector.feed(contenido)
    return lector.resultado()


def _clave(titulo: str, usadas: set[str]) -> str:
    sin_tildes = unicodedata.normalize("NFKD", titulo.lower()).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", sin_tildes)[:60].strip("-") or "parte"
    clave, n = base, 2
    while clave in usadas:
        clave, n = f"{base}-{n}", n + 1
    usadas.add(clave)
    return clave


def _legible(texto: str) -> str:
    """Los subtítulos internos se muestran en negrita en el chat, no como «## …»."""
    texto = re.sub(r"^#{2,}\s*(.+?)\s*$", r"**\1**", texto, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", texto).strip()


def dividir_pagina(nombre: str, texto: str, url: str) -> list[Pieza]:
    """
    Parte una página en piezas citables. Las preguntas frecuentes («¿…?») quedan una por pieza, con su respuesta;
    lo demás se agrupa por secciones de un tamaño que la búsqueda maneja bien.
    """
    lineas = [l for l in texto.splitlines()]
    usadas: set[str] = set()
    preguntas = [i for i, l in enumerate(lineas) if re.match(r"^(##\s*)?¿.{8,}\?$", l.strip())]
    piezas: list[Pieza] = []
    if len(preguntas) >= 4:
        intro = "\n".join(lineas[: preguntas[0]]).strip()
        if len(intro) > 80:
            piezas.append(Pieza(_clave(nombre, usadas), nombre, _legible(intro), url))
        for n, i in enumerate(preguntas):
            fin = preguntas[n + 1] if n + 1 < len(preguntas) else len(lineas)
            pregunta = lineas[i].strip().lstrip("#").strip()
            respuesta = re.sub(r"^R/\s*", "", "\n".join(lineas[i + 1 : fin]).strip())
            if respuesta:
                piezas.append(Pieza(_clave(pregunta, usadas), pregunta, _legible(respuesta)[:6000], url))
        return piezas

    seccion, grupo = nombre, []

    def cerrar():
        cuerpo = "\n".join(grupo).strip()
        if len(cuerpo) >= 40:
            titulo = nombre if seccion == nombre else f"{nombre}: {seccion}"
            piezas.append(Pieza(_clave(titulo, usadas), titulo, _legible(cuerpo), url))

    for linea in lineas:
        if linea.startswith("## "):
            cerrar()
            seccion, grupo = linea[3:].strip() or nombre, []
            continue
        if sum(len(l) for l in grupo) + len(linea) > LARGO_PIEZA and grupo:
            cerrar()
            grupo = []
        grupo.append(linea)
    cerrar()
    return piezas


# ---------------------------------------------------------------- lectores


def _leer_wordpress(http: httpx.Client, url: str, dominios: list[str]) -> tuple[str, str, str] | None:
    """Si el sitio es WordPress, su API da el contenido limpio, sin menús: (título, html, dirección canónica)."""
    partes = urlparse(url)
    slug = [p for p in partes.path.split("/") if p]
    if not slug:
        return None
    api = f"{partes.scheme}://{partes.hostname}/wp-json/wp/v2/pages?slug={slug[-1]}&_fields=title,content,link"
    try:
        _, contenido, tipo = descargar(http, api, dominios)
        datos = json.loads(contenido)
    except (ErrorContenido, ValueError, httpx.HTTPError):
        return None
    if not isinstance(datos, list) or not datos:
        return None
    pagina = datos[0]
    return unescape(pagina["title"]["rendered"]), pagina["content"]["rendered"], pagina.get("link") or url


def leer_pagina(http: httpx.Client, nombre: str, url: str, dominios: list[str]) -> tuple[str, list[Pieza]]:
    wp = _leer_wordpress(http, url, dominios)
    if wp:
        _, html, enlace = wp
    else:
        enlace, contenido, _ = descargar(http, url, dominios)
        html = contenido.decode("utf-8", "replace")
    texto = html_a_texto(html, enlace)
    if len(texto) < 60:
        raise ErrorContenido("La página no tiene texto que se pueda leer.")
    return enlace, dividir_pagina(nombre, texto, enlace)


def leer_noticias(http: httpx.Client, url: str, dominios: list[str]) -> list[Pieza]:
    _, contenido, _ = descargar(http, url, dominios)
    if b"<!DOCTYPE" in contenido[:3000] and b"<rss" not in contenido[:3000]:
        raise ErrorContenido("La dirección no es un canal de noticias RSS.")
    if b"<!ENTITY" in contenido[:5000]:
        raise ErrorContenido("El canal de noticias tiene un formato no permitido.")
    try:
        raiz = ElementTree.fromstring(contenido)
    except ElementTree.ParseError as error:
        raise ErrorContenido("No se pudo leer el canal de noticias.") from error
    usadas: set[str] = set()
    piezas = []
    for item in raiz.iter("item"):
        titulo = " ".join((item.findtext("title") or "").split())
        enlace = (item.findtext("link") or "").strip()
        if not titulo or not enlace:
            continue
        resumen = html_a_texto(item.findtext("description") or "", enlace)
        resumen = re.sub(r"\s*\(https?://[^)]+\)", "", resumen)[:700].strip()
        try:
            fecha = parsedate_to_datetime(item.findtext("pubDate") or "").strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            fecha = hoy()
        piezas.append(
            Pieza(_clave(enlace, usadas), titulo, resumen or titulo, enlace, fecha, sumar_dias(fecha, DIAS_VIGENCIA_NOTICIA))
        )
    return piezas


# ---------------------------------------------------------------- sincronización


def _huella(piezas: list[Pieza]) -> str:
    return hashlib.sha256(json.dumps([p.__dict__ for p in piezas], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _registrar(conexion: sqlite3.Connection, contenido_id: int, accion: str, pieza: Pieza | None) -> None:
    datos = pieza.__dict__ if pieza else {}
    conexion.execute(
        "INSERT INTO versiones (contenido_id, accion, datos, autor, fecha) VALUES (?, ?, ?, ?, ?)",
        (contenido_id, accion, json.dumps(datos, ensure_ascii=False), AUTOR, ahora()),
    )


def aplicar(conexion: sqlite3.Connection, fuente: sqlite3.Row, piezas: list[Pieza]) -> dict:
    """Publica lo nuevo, actualiza lo que cambió y retira lo que ya no está en la página. Todo queda en el historial."""
    tipo = "novedad" if fuente["tipo"] == "noticias" else "pagina"
    prefijo = f"web{fuente['id']}:"
    existentes = {
        f["origen_ref"]: f
        for f in conexion.execute("SELECT * FROM contenidos WHERE origen = 'web' AND origen_ref LIKE ?", (prefijo + "%",))
    }
    cuenta = {"nuevas": 0, "actualizadas": 0, "retiradas": 0}
    vistas = set()
    for pieza in piezas:
        ref = prefijo + pieza.clave
        vistas.add(ref)
        fila = existentes.get(ref)
        valores = (pieza.titulo[:300], pieza.texto, pieza.url, pieza.inicio, pieza.fin)
        if fila is None:
            cursor = conexion.execute(
                """INSERT INTO contenidos (tipo, dependencia, titulo, texto, url, inicio, fin, publico, origen, origen_ref,
                                           estado, actualizado_por, actualizado_en)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'web', ?, 'publicado', ?, ?)""",
                (tipo, fuente["dependencia"], *valores, fuente["publico"], ref, AUTOR, ahora()),
            )
            _registrar(conexion, cursor.lastrowid, "importado de la web", pieza)
            cuenta["nuevas"] += 1
        elif (fila["titulo"], fila["texto"], fila["url"], fila["inicio"], fila["fin"]) != valores or fila["estado"] != "publicado":
            conexion.execute(
                """UPDATE contenidos SET titulo = ?, texto = ?, url = ?, inicio = ?, fin = ?, estado = 'publicado',
                   actualizado_por = ?, actualizado_en = ? WHERE id = ?""",
                (*valores, AUTOR, ahora(), fila["id"]),
            )
            _registrar(conexion, fila["id"], "actualizado desde la web", pieza)
            cuenta["actualizadas"] += 1
    if tipo == "pagina":
        # Una noticia vieja sale del canal pero sigue vigente hasta su fecha; una sección borrada de una página, no.
        for ref, fila in existentes.items():
            if ref not in vistas and fila["estado"] == "publicado":
                conexion.execute("UPDATE contenidos SET estado = 'archivado' WHERE id = ?", (fila["id"],))
                _registrar(conexion, fila["id"], "retirado: ya no está en la página", None)
                cuenta["retiradas"] += 1
    return cuenta


def sincronizar(conexion: sqlite3.Connection, fuente_id: int, http: httpx.Client, dominios: list[str]) -> dict:
    fuente = conexion.execute("SELECT * FROM fuentes_web WHERE id = ?", (fuente_id,)).fetchone()
    if not fuente:
        raise ErrorContenido("Esa fuente no existe.", 404)
    momento = ahora()
    try:
        if fuente["tipo"] == "noticias":
            piezas = leer_noticias(http, fuente["url"], dominios)
        else:
            _, piezas = leer_pagina(http, fuente["nombre"], fuente["url"], dominios)
    except (ErrorContenido, httpx.HTTPError) as error:
        mensaje = error.mensaje if isinstance(error, ErrorContenido) else "No se pudo conectar con la página."
        conexion.execute("UPDATE fuentes_web SET ultima_revision = ?, error = ? WHERE id = ?", (momento, mensaje, fuente_id))
        conexion.commit()
        return {"error": mensaje}
    huella = _huella(piezas)
    if huella == fuente["huella"]:
        conexion.execute("UPDATE fuentes_web SET ultima_revision = ?, error = '' WHERE id = ?", (momento, fuente_id))
        conexion.commit()
        return {"nuevas": 0, "actualizadas": 0, "retiradas": 0, "sin_cambios": True}
    cuenta = aplicar(conexion, fuente, piezas)
    conexion.execute(
        """UPDATE fuentes_web SET huella = ?, piezas = ?, ultima_revision = ?, ultimo_cambio = ?, error = '' WHERE id = ?""",
        (huella, len(piezas), momento, momento, fuente_id),
    )
    conexion.commit()
    if any(cuenta.values()):
        ajustes.subir_version(conexion)
    return cuenta


def agregar(conexion: sqlite3.Connection, datos: dict, dominios: list[str]) -> int:
    url = str(datos.get("url") or "").strip()
    nombre = str(datos.get("nombre") or "").strip()
    tipo = datos.get("tipo") or "pagina"
    if not permitida(url, dominios):
        raise ErrorContenido("Solo se pueden agregar páginas https de " + ", ".join(dominios) + ".")
    if not 3 <= len(nombre) <= 120:
        raise ErrorContenido("Ponle a la fuente un nombre de 3 a 120 caracteres.")
    if tipo not in ("pagina", "noticias"):
        raise ErrorContenido("El tipo debe ser página o noticias.")
    if datos.get("dependencia") not in DEPENDENCIAS:
        raise ErrorContenido("Elige una dependencia de la lista.")
    if (datos.get("publico") or "todos") not in PUBLICOS:
        raise ErrorContenido("Elige para quién es la fuente.")
    if conexion.execute("SELECT 1 FROM fuentes_web WHERE url = ?", (url,)).fetchone():
        raise ErrorContenido("Esa dirección ya está en la lista de fuentes.")
    cursor = conexion.execute(
        "INSERT INTO fuentes_web (url, nombre, tipo, dependencia, publico) VALUES (?, ?, ?, ?, ?)",
        (url, nombre, tipo, datos.get("dependencia"), datos.get("publico") or "todos"),
    )
    conexion.commit()
    return cursor.lastrowid


def cargar_iniciales(conexion: sqlite3.Connection) -> None:
    for nombre, url, tipo, dependencia, publico in FUENTES_INICIALES:
        conexion.execute(
            "INSERT OR IGNORE INTO fuentes_web (url, nombre, tipo, dependencia, publico) VALUES (?, ?, ?, ?, ?)",
            (url, nombre, tipo, dependencia, publico),
        )
    conexion.commit()


class Programador:
    """Revisa las fuentes al arrancar y luego cada cierto número de horas, en un hilo aparte."""

    def __init__(self, config: Config, al_cambiar):
        self.config = config
        self.al_cambiar = al_cambiar
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.http = httpx.Client(timeout=ESPERA)

    def iniciar(self) -> None:
        self._hilo = threading.Thread(target=self._bucle, name="fuentes-web", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()

    def revisar_todas(self) -> int:
        conexion = conectar(self.config.ruta_db)
        cambios = 0
        try:
            for fila in conexion.execute("SELECT id FROM fuentes_web WHERE activa = 1 ORDER BY id").fetchall():
                if self._parar.is_set():
                    break
                resultado = sincronizar(conexion, fila["id"], self.http, self.config.dominios_web)
                cambios += sum(resultado.get(k, 0) for k in ("nuevas", "actualizadas", "retiradas"))
        finally:
            conexion.close()
        return cambios

    def _bucle(self) -> None:
        if self._parar.wait(3):
            return
        while not self._parar.is_set():
            try:
                if self.revisar_todas():
                    self.al_cambiar()
            except Exception:  # noqa: BLE001 - un error de red nunca debe detener al asistente
                logger.exception("Falló la revisión de fuentes web")
            if self._parar.wait(max(1, self.config.actualizar_cada_horas) * 3600):
                return
