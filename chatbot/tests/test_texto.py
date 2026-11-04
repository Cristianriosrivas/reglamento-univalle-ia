import io
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app import semilla
from app import texto as T

FUENTES = Path(__file__).resolve().parent.parent / "fuentes"


def test_repara_el_dano_del_pdf_oficial():
    limpio, reparadas = T.reparar_acentos("El perodo acadØmico serÆ la sØptima semana, aæo œnico")
    assert "académico será la séptima" in limpio
    assert "año único" in limpio
    assert reparadas == 5


def test_repara_el_dano_mac_roman():
    limpio, _ = T.reparar_acentos("La matrÌcula acadÈmica de la InstituciÛn y dem·s")
    assert limpio == "La matrícula académica de la Institución y demás"


def test_no_toca_un_texto_sano():
    original = "La calificación del 18° período, con «comillas» y 3ª opción."
    assert T.reparar_acentos(original) == (original, 0)


def test_acuerdo_009_tiene_los_122_articulos():
    extraido = T.extraer_pdf((FUENTES / "acuerdo_009_1997.pdf").read_bytes())
    segmentos = T.segmentar(extraido.texto)
    assert [s.numero for s in segmentos] == list(range(1, 123))
    assert len({s.capitulo for s in segmentos}) == 19
    assert not any(c in s.texto for s in segmentos for c in "ÆØœ˝")


def test_une_palabras_partidas_y_quita_encabezados():
    extraido = T.extraer_pdf((FUENTES / "acuerdo_009_1997.pdf").read_bytes())
    articulo_5 = next(s for s in T.segmentar(extraido.texto) if s.numero == 5)
    assert "Director del Programa" in articulo_5.texto
    assert "Direc-" not in articulo_5.texto
    assert "UNIVERSIDAD DEL VALLE" not in extraido.texto.split("ARTICULO 5o")[1][:600]


def test_lee_pdf_oficial_cifrado():
    extraido = T.extraer_pdf((FUENTES / "resolucion_080_2024.pdf").read_bytes())
    segmentos = T.segmentar(extraido.texto)
    assert len(segmentos) == 40
    assert segmentos[1].capitulo.startswith("Capítulo Primero")


def test_avisa_si_el_pdf_es_un_escaneo():
    escritor = PdfWriter()
    escritor.add_blank_page(200, 200)
    salida = io.BytesIO()
    escritor.write(salida)
    extraido = T.extraer_pdf(salida.getvalue())
    assert extraido.es_escaneo
    assert "escaneo" in extraido.advertencias[0]


def test_lee_word():
    documento = (
        '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        "<w:p><w:r><w:t>ARTÍCULO 1. Primera norma.</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>ARTÍCULO 2. Segunda norma.</w:t></w:r></w:p></w:body></w:document>"
    )
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as archivo:
        archivo.writestr("word/document.xml", documento)
    segmentos = T.segmentar(T.extraer("norma.docx", salida.getvalue()).texto)
    assert [s.numero for s in segmentos] == [1, 2]


def test_rechaza_word_con_entidades():
    salida = io.BytesIO()
    with zipfile.ZipFile(salida, "w") as archivo:
        archivo.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "b">]><x/>')
    with pytest.raises(ValueError):
        T.extraer("malicioso.docx", salida.getvalue())


def test_rechaza_formatos_desconocidos():
    with pytest.raises(ValueError):
        T.extraer("virus.exe", b"MZ")


def test_sin_articulos_corta_por_secciones():
    segmentos = T.segmentar("Primer párrafo de una circular.\nSegundo párrafo de la circular.")
    assert segmentos[0].titulo == "Sección 1"
    assert segmentos[0].numero is None


def test_se_aplica_la_modificacion_del_paragrafo_83(conexion):
    texto = conexion.execute("SELECT texto FROM contenidos WHERE titulo = 'Artículo 83' AND fuente_id = 1").fetchone()["texto"]
    assert "técnico superior" in texto
    assert "(Modificado por el Acuerdo 006 de 2005)" in texto
    assert "de licenciatura" not in texto


def test_sin_erratas_del_impreso(conexion):
    textos = " ".join(f["texto"] for f in conexion.execute("SELECT texto FROM contenidos"))
    for mal, _ in semilla._ERRATAS:
        assert mal not in textos
