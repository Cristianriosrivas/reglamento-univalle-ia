"""Carga inicial de la demo: normas oficiales, preguntas frecuentes, contactos, fechas y usuarios de prueba."""
from __future__ import annotations

import json
import re
import sqlite3

from . import texto as T
from .config import RAIZ
from .db import ahora
from .seguridad import crear_hash

FUENTES = RAIZ / "fuentes"
_REGISTRO = "https://registro.univalle.edu.co/wp-content/uploads"

NORMAS = {
    "acuerdo_009_1997": {
        "nombre": "Acuerdo 009 de 1997",
        "dependencia": "Secretaría General",
        "url": f"{_REGISTRO}/2024/05/acuerdo_009.pdf",
        "nota": "Reglamento Estudiantil de Pregrado.",
    },
    "acuerdo_006_2023": {
        "nombre": "Acuerdo 006 de 2023",
        "dependencia": "Secretaría General",
        "url": f"{_REGISTRO}/2024/05/Acuerdo_006_Modifica_el_Acuerdo_009_Bajos_Rendimientos_Academicos.pdf",
        "nota": "Modifica el Capítulo VIII (bajos rendimientos). El original es un escaneo; texto cotejado con él.",
    },
    "resolucion_080_2024": {
        "nombre": "Resolución 080 de 2024",
        "dependencia": "Admisiones",
        "url": f"{_REGISTRO}/2024/05/RCA_080_Reglamento_inscripcion_y_admision-Pregrado.pdf",
        "nota": "Reglamento de Inscripción y Admisión a Pregrado.",
    },
    "resolucion_066_2024": {
        "nombre": "Resolución 066 de 2024",
        "dependencia": "Secretaría General",
        "url": f"{_REGISTRO}/2024/05/RCA-066-Lineamientos-acompanamiento-estudiantil.pdf",
        "nota": "Lineamientos del acompañamiento estudiantil.",
    },
    "acuerdo_004_2024": {
        "nombre": "Acuerdo 004 de 2024",
        "dependencia": "Secretaría General",
        "url": f"{_REGISTRO}/2024/09/Ac_004-modif_BajoRendimientoAcad.pdf",
        "nota": "Suspensión transitoria de los artículos 62 y 63 para febrero-junio de 2024. Transcrito de un escaneo.",
    },
}

# Erratas del impreso original que afectan la lectura.
_ERRATAS = (
    ("Acuerdo 5deroga", "Acuerdo deroga"),
    ("profesore soal a Universidad", "profesores o a la Universidad"),
    ("profeso ryal a División", "profesor y a la División"),
    ("estudianteyal a División", "estudiante y a la División"),
    ("PARAG RAFO", "PARÁGRAFO"),
    ("matrícula extemporáneo", "matrícula extemporánea"),
    ("cancelación- extemporáneo", "cancelación extemporánea"),
)
# El impreso de 1997 escribe los títulos en mayúsculas sin tilde.
_TILDES_CAPITULOS = (
    ("evaluacion", "evaluación"), ("matricula", "matrícula"), ("representacion", "representación"),
    ("estimulos", "estímulos"), ("academicos", "académicos"), ("regimen", "régimen"),
)
_CAPITULO_8_VIGENTE = "Capítulo VIII: De los bajos rendimientos académicos"

# El Acuerdo 006 de 2005 cambió este parágrafo, pero la edición impresa aún trae el texto anterior.
_PARAGRAFO_83 = (
    "PARÁGRAFO 2. Las solicitudes de ingreso de personas que ya posean un título de nivel técnico superior, "
    "tecnólogo o profesional, se asimilarán a transferencia para efectos de su tramitación. Para estos casos el "
    "título debe haber sido expedido por una institución de educación superior debidamente registrada. "
    "(Modificado por el Acuerdo 006 de 2005)."
)

USUARIOS = (
    ("admin@demo.local", "Administración del sistema", "admin", ""),
    ("editor.registro@demo.local", "Editor de Registro", "editor", "Registro Académico"),
    ("aprobador.registro@demo.local", "Aprobador de Registro", "aprobador", "Registro Académico"),
    ("editor.admisiones@demo.local", "Editor de Admisiones", "editor", "Admisiones"),
    ("aprobador.secretaria@demo.local", "Aprobador de Secretaría General", "aprobador", "Secretaría General"),
)


def _corregir(texto: str) -> str:
    for mal, bien in _ERRATAS:
        texto = texto.replace(mal, bien)
    texto = texto.replace("PARAGRAFO", "PARÁGRAFO")
    return re.sub(r"(?<=\w)\s+(?=[.,;](?:\s|$))", "", texto)


def _capitulo(nombre: str) -> str:
    for mal, bien in _TILDES_CAPITULOS:
        nombre = nombre.replace(mal, bien)
    return nombre


def _insertar(conexion: sqlite3.Connection, **campos) -> int:
    campos.setdefault("estado", "publicado")
    campos.setdefault("actualizado_por", "Carga inicial")
    campos.setdefault("actualizado_en", ahora())
    columnas = ", ".join(campos)
    marcas = ", ".join("?" for _ in campos)
    cursor = conexion.execute(f"INSERT INTO contenidos ({columnas}) VALUES ({marcas})", tuple(campos.values()))
    fila = {k: campos.get(k) for k in ("titulo", "texto", "capitulo", "numero", "url", "inicio", "fin")}
    conexion.execute(
        "INSERT INTO versiones (contenido_id, accion, datos, autor, fecha) VALUES (?, 'carga inicial', ?, 'Carga inicial', ?)",
        (cursor.lastrowid, json.dumps(fila, ensure_ascii=False), ahora()),
    )
    return cursor.lastrowid


def _cargar_fuentes(conexion: sqlite3.Connection) -> dict[str, int]:
    ids = {}
    for clave, datos in NORMAS.items():
        cursor = conexion.execute(
            "INSERT INTO fuentes (nombre, dependencia, url, nota) VALUES (?, ?, ?, ?)",
            (datos["nombre"], datos["dependencia"], datos["url"], datos["nota"]),
        )
        ids[clave] = cursor.lastrowid
    return ids


def _segmentos(clave: str) -> list[T.Segmento]:
    pdf = FUENTES / f"{clave}.pdf"
    if pdf.exists():
        extraido = T.extraer_pdf(pdf.read_bytes(), ignorar=("Artículo transitorio",))
        return T.segmentar(extraido.texto)
    return T.segmentar((FUENTES / f"{clave}.txt").read_text(encoding="utf-8"))


def _cargar_acuerdo_009(conexion: sqlite3.Connection, fuente_id: int) -> dict[int, int]:
    norma = NORMAS["acuerdo_009_1997"]
    ids = {}
    for segmento in _segmentos("acuerdo_009_1997"):
        texto = _corregir(segmento.texto)
        if segmento.numero == 83:
            texto = re.sub(r"PARÁGRAFO 2\..*?(?=\nPARÁGRAFO 3)", _PARAGRAFO_83, texto, flags=re.S)
        ids[segmento.numero] = _insertar(
            conexion, tipo="articulo", dependencia=norma["dependencia"], fuente_id=fuente_id, titulo=segmento.titulo,
            texto=texto, capitulo=_capitulo(segmento.capitulo), numero=segmento.numero, url=norma["url"],
        )
    return ids


def _cargar_acuerdo_006(conexion: sqlite3.Connection, fuente_id: int, previos: dict[int, int]) -> None:
    """Los artículos 59 a 64 reemplazan a los de 1997: el asistente ya no responde con la versión anterior."""
    norma = NORMAS["acuerdo_006_2023"]
    for segmento in _segmentos("acuerdo_006_2023"):
        anterior = previos[segmento.numero]
        nuevo = _insertar(
            conexion, tipo="articulo", dependencia=norma["dependencia"], fuente_id=fuente_id, titulo=segmento.titulo,
            texto=segmento.texto, capitulo=_CAPITULO_8_VIGENTE, numero=segmento.numero, url=norma["url"], reemplaza=anterior,
        )
        conexion.execute("UPDATE contenidos SET reemplazado_por = ? WHERE id = ?", (nuevo, anterior))


def _cargar_norma(conexion: sqlite3.Connection, clave: str, fuente_id: int, estado: str = "publicado") -> None:
    norma = NORMAS[clave]
    for segmento in _segmentos(clave):
        nombre = norma["nombre"]
        _insertar(
            conexion, tipo="articulo", dependencia=norma["dependencia"], fuente_id=fuente_id,
            titulo=f"{segmento.titulo} de la {nombre}" if nombre.startswith("Resolución") else f"{segmento.titulo} del {nombre}",
            texto=_corregir(segmento.texto), capitulo=segmento.capitulo, url=norma["url"], estado=estado,
            actualizado_por="Carga inicial",
        )


def _cargar_ejemplos(conexion: sqlite3.Connection, fuentes: dict[str, int]) -> None:
    datos = json.loads((FUENTES / "contenido_inicial.json").read_text(encoding="utf-8"))
    for tipo in ("faq", "contacto", "fecha"):
        for item in datos[tipo]:
            clave = item.get("fuente")
            _insertar(
                conexion, tipo=tipo, dependencia=item["dependencia"], titulo=item["titulo"], texto=item["texto"],
                fuente_id=fuentes.get(clave), url=item.get("url") or (NORMAS[clave]["url"] if clave else ""),
                inicio=item.get("inicio"), fin=item.get("fin"), destacada=1 if item.get("destacada") else 0,
            )


def _cargar_usuarios(conexion: sqlite3.Connection, clave: str) -> None:
    hash_clave = crear_hash(clave)
    for correo, nombre, rol, dependencia in USUARIOS:
        conexion.execute(
            "INSERT INTO usuarios (correo, nombre, rol, dependencia, clave_hash) VALUES (?, ?, ?, ?, ?)",
            (correo, nombre, rol, dependencia, hash_clave),
        )


def cargar_si_vacia(conexion: sqlite3.Connection, clave_demo: str) -> bool:
    if conexion.execute("SELECT 1 FROM contenidos LIMIT 1").fetchone():
        return False
    fuentes = _cargar_fuentes(conexion)
    articulos = _cargar_acuerdo_009(conexion, fuentes["acuerdo_009_1997"])
    _cargar_acuerdo_006(conexion, fuentes["acuerdo_006_2023"], articulos)
    _cargar_norma(conexion, "resolucion_080_2024", fuentes["resolucion_080_2024"])
    _cargar_norma(conexion, "resolucion_066_2024", fuentes["resolucion_066_2024"])
    # Queda en revisión a propósito: en la demo muestra el flujo de aprobación con una norma real.
    _cargar_norma(conexion, "acuerdo_004_2024", fuentes["acuerdo_004_2024"], estado="revision")
    _cargar_ejemplos(conexion, fuentes)
    if clave_demo:
        _cargar_usuarios(conexion, clave_demo)
    conexion.commit()
    return True
