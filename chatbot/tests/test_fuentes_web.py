"""Lectura de las páginas oficiales y del canal de noticias, sin salir a internet: las respuestas se simulan."""
import json

import httpx
import pytest

from app import fuentes_web as W
from app.contenidos import ErrorContenido

DOMINIOS = ["univalle.edu.co"]
URL = "https://registro.univalle.edu.co/becas-deportivas/"

PREGUNTAS_HTML = """
<h2>Becas deportivas</h2>
<p>La Universidad apoya a quienes la representan en competencias oficiales.</p>
<p><strong>¿Quién puede pedir la beca de excelencia deportiva?</strong></p>
<p>R/ Los estudiantes de pregrado que representen a la Universidad en torneos oficiales.</p>
<p><strong>¿Cuándo se abre la convocatoria de becas deportivas?</strong></p>
<p>En la tercera semana de cada período académico.</p>
<p><strong>¿Qué documentos necesito para la beca deportiva?</strong></p>
<p>La certificación del entrenador y el horario de clases.</p>
<p><strong>¿La beca deportiva cubre la matrícula completa?</strong></p>
<p>Cubre el 50 % del valor de la <a href="/matricula-financiera/">matrícula financiera</a>.</p>
<p><strong>¿Dónde entrego los documentos de la beca deportiva?</strong></p>
<p>En la oficina de deportes de Bienestar Universitario.</p>
<script>alert('no')</script>
"""

RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>Noticias</title>
<item><title>Nueva sede en el Pacífico</title><link>https://www.univalle.edu.co/noticias/sede</link>
<description>&lt;p&gt;La Universidad abre una sede nueva.&lt;/p&gt;</description>
<pubDate>Fri, 13 Nov 2026 10:00:00 -0500</pubDate></item>
<item><title>Sin enlace</title><description>No debe entrar</description></item>
</channel></rss>"""


def wordpress(html: str, titulo: str = "Becas deportivas"):
    """Responde como la API de WordPress del sitio de Registro."""

    def manejar(peticion: httpx.Request) -> httpx.Response:
        if "/wp-json/wp/v2/pages" in str(peticion.url):
            return httpx.Response(200, json=[{"title": {"rendered": titulo}, "content": {"rendered": html}, "link": URL}])
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(manejar))


def fuente(conexion, url=URL, tipo="pagina"):
    return W.agregar(
        conexion, {"url": url, "nombre": "Becas deportivas", "tipo": tipo, "dependencia": "Bienestar Universitario", "publico": "estudiante"},
        DOMINIOS,
    )


@pytest.mark.parametrize(
    "url,permitida",
    [
        ("https://registro.univalle.edu.co/x/", True),
        ("https://univalle.edu.co/", True),
        ("http://registro.univalle.edu.co/x/", False),
        ("https://univalle.edu.co.sitio-falso.com/", False),
        ("https://sitio-falso.com/univalle.edu.co", False),
        ("file:///etc/passwd", False),
        ("https://127.0.0.1/", False),
    ],
)
def test_solo_lee_paginas_https_de_la_universidad(url, permitida):
    assert W.permitida(url, DOMINIOS) is permitida


def test_no_sigue_redirecciones_fuera_de_la_universidad():
    def manejar(peticion):
        return httpx.Response(302, headers={"location": "https://sitio-falso.com/robar"})

    with pytest.raises(ErrorContenido):
        W.descargar(httpx.Client(transport=httpx.MockTransport(manejar)), URL, DOMINIOS)


def test_rechaza_paginas_gigantes(monkeypatch):
    monkeypatch.setattr(W, "MAX_BYTES", 1000)
    cliente = httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, content=b"x" * 5000)))
    with pytest.raises(ErrorContenido, match="grande"):
        W.descargar(cliente, URL, DOMINIOS)


def test_html_a_texto_quita_scripts_y_conserva_enlaces():
    texto = W.html_a_texto(PREGUNTAS_HTML, URL)
    assert "alert" not in texto
    assert "## Becas deportivas" in texto
    assert "https://registro.univalle.edu.co/matricula-financiera/" in texto


def test_una_pagina_de_preguntas_queda_una_pieza_por_pregunta():
    piezas = W.dividir_pagina("Becas deportivas", W.html_a_texto(PREGUNTAS_HTML, URL), URL)
    preguntas = [p for p in piezas if p.titulo.startswith("¿")]
    assert len(preguntas) == 5
    assert preguntas[0].titulo == "¿Quién puede pedir la beca de excelencia deportiva?"
    assert preguntas[0].texto.startswith("Los estudiantes de pregrado")  # sin el «R/»
    assert len({p.clave for p in piezas}) == len(piezas)


def test_una_pagina_larga_se_parte_por_secciones():
    texto = "## Requisitos\n" + "Debes cumplir con el paso uno. " * 30 + "\n## Costos\n" + "El valor depende del estrato. " * 10
    piezas = W.dividir_pagina("Grados", texto, URL)
    assert [p.titulo for p in piezas] == ["Grados: Requisitos", "Grados: Costos"]


def test_lee_el_canal_de_noticias_con_vigencia():
    cliente = httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, content=RSS.encode())))
    piezas = W.leer_noticias(cliente, "https://www.univalle.edu.co/?format=feed&type=rss", DOMINIOS)
    assert len(piezas) == 1
    assert piezas[0].titulo == "Nueva sede en el Pacífico"
    assert piezas[0].texto == "La Universidad abre una sede nueva."
    assert (piezas[0].inicio, piezas[0].fin) == ("2026-11-13", "2026-12-28")


def test_el_canal_de_noticias_no_acepta_entidades_xml():
    bomba = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>'
    cliente = httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, content=bomba)))
    with pytest.raises(ErrorContenido):
        W.leer_noticias(cliente, "https://www.univalle.edu.co/rss", DOMINIOS)


def test_sincronizar_publica_actualiza_y_retira(conexion):
    fuente_id = fuente(conexion)
    primera = W.sincronizar(conexion, fuente_id, wordpress(PREGUNTAS_HTML), DOMINIOS)
    assert primera["nuevas"] >= 4
    publicadas = conexion.execute(
        "SELECT titulo, publico, estado FROM contenidos WHERE origen = 'web' AND origen_ref LIKE ?", (f"web{fuente_id}:%",)
    ).fetchall()
    assert {f["estado"] for f in publicadas} == {"publicado"}
    assert {f["publico"] for f in publicadas} == {"estudiante"}

    # Lo mismo otra vez: no se toca nada.
    assert W.sincronizar(conexion, fuente_id, wordpress(PREGUNTAS_HTML), DOMINIOS)["sin_cambios"] is True

    # La página cambió una respuesta y quitó una pregunta.
    cambiada = PREGUNTAS_HTML.replace("tercera semana", "quinta semana").replace(
        "<p><strong>¿La beca deportiva cubre la matrícula completa?</strong></p>", ""
    ).replace("<p>Cubre el 50 % del valor", "<p>Además, cubre el 50 % del valor")
    cuenta = W.sincronizar(conexion, fuente_id, wordpress(cambiada), DOMINIOS)
    assert cuenta["actualizadas"] >= 1
    assert cuenta["retiradas"] == 1
    convocatoria = conexion.execute(
        "SELECT id, texto FROM contenidos WHERE titulo = '¿Cuándo se abre la convocatoria de becas deportivas?'"
    ).fetchone()
    assert "quinta semana" in convocatoria["texto"]
    historial = [v["accion"] for v in conexion.execute("SELECT accion FROM versiones WHERE contenido_id = ? ORDER BY id", (convocatoria["id"],))]
    assert historial == ["importado de la web", "actualizado desde la web"]


def test_si_la_pagina_falla_se_conserva_lo_publicado(conexion):
    fuente_id = fuente(conexion)
    W.sincronizar(conexion, fuente_id, wordpress(PREGUNTAS_HTML), DOMINIOS)
    caida = httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(500)))
    resultado = W.sincronizar(conexion, fuente_id, caida, DOMINIOS)
    assert "500" in resultado["error"]
    assert conexion.execute("SELECT error FROM fuentes_web WHERE id = ?", (fuente_id,)).fetchone()["error"]
    vigentes = conexion.execute(
        "SELECT COUNT(*) FROM contenidos WHERE origen_ref LIKE ? AND estado = 'publicado'", (f"web{fuente_id}:%",)
    ).fetchone()[0]
    assert vigentes >= 4


@pytest.mark.parametrize(
    "datos,mensaje",
    [
        ({"url": "https://google.com/"}, "https"),
        ({"nombre": "x"}, "nombre"),
        ({"dependencia": "Oficina inventada"}, "dependencia"),
        ({"url": "https://registro.univalle.edu.co/calendarios/"}, "ya está"),
    ],
)
def test_valida_las_fuentes_nuevas(conexion, datos, mensaje):
    base = {"url": URL, "nombre": "Becas deportivas", "tipo": "pagina", "dependencia": "Bienestar Universitario"}
    with pytest.raises(ErrorContenido, match=mensaje):
        W.agregar(conexion, {**base, **datos}, DOMINIOS)


def test_la_carga_inicial_trae_registro_y_noticias(conexion):
    fuentes = {f["url"]: f for f in conexion.execute("SELECT * FROM fuentes_web")}
    assert len(fuentes) == len(W.FUENTES_INICIALES)
    assert fuentes["https://www.univalle.edu.co/?format=feed&type=rss"]["tipo"] == "noticias"
    assert all(W.permitida(url, DOMINIOS) for url in fuentes)


def test_un_canal_de_noticias_crea_novedades(conexion):
    fuente_id = fuente(conexion, url="https://www.univalle.edu.co/noticias/rss", tipo="noticias")
    cliente = httpx.Client(transport=httpx.MockTransport(lambda p: httpx.Response(200, content=RSS.encode())))
    assert W.sincronizar(conexion, fuente_id, cliente, DOMINIOS)["nuevas"] == 1
    fila = conexion.execute("SELECT tipo, fin FROM contenidos WHERE origen_ref LIKE ?", (f"web{fuente_id}:%",)).fetchone()
    assert (fila["tipo"], fila["fin"]) == ("novedad", "2026-12-28")


def test_wordpress_vacio_lee_la_pagina_normal(conexion):
    def manejar(peticion: httpx.Request) -> httpx.Response:
        if "/wp-json/" in str(peticion.url):
            return httpx.Response(200, content=json.dumps([]).encode())
        return httpx.Response(200, content=f"<html><body><main>{PREGUNTAS_HTML}</main></body></html>".encode())

    enlace, piezas = W.leer_pagina(httpx.Client(transport=httpx.MockTransport(manejar)), "Becas", URL, DOMINIOS)
    assert enlace == URL
    assert len([p for p in piezas if p.titulo.startswith("¿")]) == 5
