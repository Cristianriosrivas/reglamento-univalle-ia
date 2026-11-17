"""
Convierte documentos normativos (PDF, Word o texto) en piezas limpias que el asistente pueda citar.

Existe porque los PDF reales de la universidad traen problemas que un cargador genérico no ve:
- acentos dañados por una mala conversión («acadØmico», «matrÌcula»);
- encabezados y números de página mezclados dentro del texto;
- palabras partidas con guion al final de la línea;
- escaneos sin capa de texto, que hay que avisar en lugar de cargar vacíos.
"""
from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from xml.etree import ElementTree

from pypdf import PdfReader

# Los dos daños de codificación encontrados en documentos reales de Univalle.
_DANOS = {
    "pdf-impresion": {"Æ": "á", "Ø": "é", "œ": "ú", "æ": "ñ", "˝": "Í", "`": "Á"},
    "mac-roman": {"·": "á", "È": "é", "Ì": "í", "Û": "ó", "˙": "ú", "Ò": "ñ", "Õ": "Í", "£": "Á"},
}
_MINUSCULAS_DANADAS = {nombre: "".join(c for c, r in mapa.items() if r.islower()) for nombre, mapa in _DANOS.items()}
_CONTROL = {"\x93": "“", "\x94": "”", "\x95": "•", "\x96": "–", "\xa0": " ", "\xad": ""}

_MIN_SINTOMAS = 3
_MIN_CHARS_PAGINA = 40
_LARGO_SECCION = 900


@dataclass
class Extraccion:
    texto: str
    paginas: int = 1
    paginas_sin_texto: int = 0
    acentos_reparados: int = 0
    advertencias: list[str] = field(default_factory=list)

    @property
    def es_escaneo(self) -> bool:
        return self.paginas > 0 and self.paginas_sin_texto == self.paginas


@dataclass
class Segmento:
    titulo: str
    texto: str
    numero: int | None = None
    capitulo: str = ""


def _sintomas(texto: str, nombre: str) -> int:
    """Cuenta letras dañadas dentro de palabras: «acadØmico», «dem·s», «ser·»."""
    letras = re.escape(_MINUSCULAS_DANADAS[nombre])
    return len(re.findall(rf"[a-záéíóúñ][{letras}](?:[a-záéíóúñ]|\b)", texto))


def reparar_acentos(texto: str) -> tuple[str, int]:
    """Repara el daño de codificación más probable y devuelve el texto y cuántas letras corrigió."""
    texto = texto.translate(str.maketrans(_CONTROL))
    nombre = max(_DANOS, key=lambda n: _sintomas(texto, n))
    if _sintomas(texto, nombre) < _MIN_SINTOMAS:
        return texto, 0
    mapa = _DANOS[nombre]
    reparadas = sum(texto.count(c) for c in mapa)
    # En este daño la Ó quedó como comilla de cierre; solo se toca entre mayúsculas.
    texto = re.sub(r"(?<=[A-Z])”(?=[A-Z])", "Ó", texto)
    return texto.translate(str.maketrans(mapa)), reparadas


def _lineas_repetidas(paginas: list[list[str]]) -> set[str]:
    """Encabezados y pies: líneas que se repiten en muchas páginas, sin contar los números."""
    if len(paginas) < 4:
        return set()
    conteo: Counter[str] = Counter()
    for pag in paginas:
        conteo.update({_huella(l) for l in pag if l})
    minimo = max(3, len(paginas) // 5)
    return {h for h, n in conteo.items() if n >= minimo and h and len(h) < 70}


def _huella(linea: str) -> str:
    return re.sub(r"\d+", "", linea).strip().upper()


def _unir_parrafos(lineas: list[str]) -> str:
    texto = "\n".join(lineas)
    texto = re.sub(r"(?<=[a-záéíóúñ])-\n(?=[a-záéíóúñ])", "", texto)
    # Las líneas se unen salvo que empiecen una pieza de la norma o un literal.
    inicio = r"(?:[a-z]\.\s|[a-z]\)\s|\d{1,2}\.\s|PAR[ÁA]GRAFO|ART[ÍI]CULO\s|CAP[ÍI]TULO\s|T[ÍI]TULO\s)"
    texto = re.sub(rf"\n(?!{inicio})", " ", texto)
    return re.sub(r"[ \t]+", " ", texto).strip()


def extraer_pdf(contenido: bytes, ignorar: tuple[str, ...] = ()) -> Extraccion:
    lector = PdfReader(io.BytesIO(contenido))
    crudas = [(pagina.extract_text() or "") for pagina in lector.pages]
    sin_texto = sum(len(t.strip()) < _MIN_CHARS_PAGINA for t in crudas)
    # Se repara el documento completo: una página corta no da síntomas suficientes por sí sola.
    limpio, reparadas = reparar_acentos("\f".join(crudas))
    paginas = [[linea.strip() for linea in pagina.splitlines()] for pagina in limpio.split("\f")]

    repetidas = _lineas_repetidas(paginas)
    lineas: list[str] = []
    for pagina in paginas:
        for linea in pagina:
            if not linea or re.fullmatch(r"\d{1,3}", linea) or linea in ignorar or _huella(linea) in repetidas:
                continue
            lineas.append(linea)

    resultado = Extraccion(_unir_parrafos(lineas), len(crudas), sin_texto, reparadas)
    if resultado.es_escaneo:
        resultado.advertencias.append(
            "Este PDF es un escaneo y no tiene texto. Pega el texto del documento o pásalo antes por un OCR."
        )
    elif sin_texto:
        resultado.advertencias.append(f"{sin_texto} de {len(crudas)} páginas no tienen texto y no se cargaron.")
    if reparadas:
        resultado.advertencias.append(f"Se corrigieron {reparadas} letras con acentos dañados. Revisa el resultado.")
    return resultado


def extraer_docx(contenido: bytes) -> Extraccion:
    """Lee el texto de un .docx sin dependencias: es un zip con XML."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as archivo:
        info = archivo.getinfo("word/document.xml")
        if info.file_size > 30_000_000:
            raise ValueError("El documento es demasiado grande.")
        xml = archivo.read(info)
    if b"<!DOCTYPE" in xml[:2000] or b"<!ENTITY" in xml[:2000]:
        raise ValueError("El documento tiene un formato no permitido.")
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    raiz = ElementTree.fromstring(xml)
    lineas = []
    for parrafo in raiz.iter(f"{w}p"):
        texto = "".join(nodo.text or "" for nodo in parrafo.iter(f"{w}t")).strip()
        if texto:
            lineas.append(texto)
    limpio, reparadas = reparar_acentos("\n".join(lineas))
    return Extraccion(limpio, acentos_reparados=reparadas)


def extraer_texto(contenido: bytes) -> Extraccion:
    try:
        crudo = contenido.decode("utf-8")
    except UnicodeDecodeError:
        crudo = contenido.decode("cp1252", errors="replace")
    limpio, reparadas = reparar_acentos(crudo)
    return Extraccion(limpio.strip(), acentos_reparados=reparadas)


def extraer(nombre: str, contenido: bytes) -> Extraccion:
    """Elige el lector según la extensión del archivo."""
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if extension == "pdf":
        return extraer_pdf(contenido)
    if extension == "docx":
        return extraer_docx(contenido)
    if extension in ("txt", "md"):
        return extraer_texto(contenido)
    raise ValueError("Formato no admitido. Sube un PDF, un Word (.docx) o un archivo de texto.")


_ARTICULO = re.compile(r"^ART[ÍI]CULO\s+([lI\d](?:\s?[lI\d])*)\s*[oº°]?\s*[.\-–:]\s*(.*)$", re.S)
_CAPITULO = re.compile(r"^CAP[ÍI]TULO\s+([IVXLC]+|[A-ZÁÉÍÓÚ]+)\b[:.]?\s*(.*)$", re.S)
_CIERRE = re.compile(r"\bCOMUN[ÍI]QUESE\b|\bPUBL[ÍI]QUESE\b", re.I)


def segmentar(texto: str, etiqueta: str = "Artículo") -> list[Segmento]:
    """Separa una norma por artículos. Si no los tiene, la corta en secciones por párrafos."""
    cierre = _CIERRE.search(texto)
    cuerpo = texto[: cierre.start()] if cierre else texto

    segmentos: list[Segmento] = []
    capitulo = ""
    actual: Segmento | None = None
    for bloque in cuerpo.split("\n"):
        bloque = bloque.strip()
        if not bloque:
            continue
        coincide_cap = _CAPITULO.match(bloque)
        if coincide_cap:
            nombre = coincide_cap.group(2).strip()
            ordinal = coincide_cap.group(1)
            ordinal = ordinal if re.fullmatch(r"[IVXLC]+", ordinal) else ordinal.capitalize()
            capitulo = f"Capítulo {ordinal}" + (f": {_titulo_frase(nombre)}" if nombre else "")
            continue
        coincide = _ARTICULO.match(bloque)
        if coincide:
            # En el impreso de 1997 el «11» aparece con eles: «ARTICULO l l o.».
            numero = int(re.sub(r"\s", "", coincide.group(1)).replace("l", "1").replace("I", "1"))
            actual = Segmento(f"{etiqueta} {numero}", coincide.group(2).strip(), numero, capitulo)
            segmentos.append(actual)
        elif actual:
            actual.texto += "\n" + bloque

    if segmentos:
        return segmentos
    return _por_secciones(cuerpo)


def _titulo_frase(mayusculas: str) -> str:
    """«DE LOS BAJOS RENDIMIENTOS» -> «De los bajos rendimientos»."""
    texto = re.sub(r"\s+", " ", mayusculas).strip()
    return texto[:1].upper() + texto[1:].lower() if texto.isupper() else texto


def _por_secciones(texto: str) -> list[Segmento]:
    secciones: list[Segmento] = []
    grupo = ""
    for parrafo in re.split(r"\n+", texto):
        if grupo and len(grupo) + len(parrafo) > _LARGO_SECCION:
            secciones.append(Segmento(f"Sección {len(secciones) + 1}", grupo.strip()))
            grupo = ""
        grupo += parrafo + "\n"
    if grupo.strip():
        secciones.append(Segmento(f"Sección {len(secciones) + 1}", grupo.strip()))
    return secciones


def sin_acentos(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")
