"""Cadena de servicios de IA gratuitos, configuración y piezas de búsqueda, sin llamadas reales."""
import json

import httpx
import pytest

from app import db
from app.busqueda import Documento, Indice
from app.config import Config, Proveedor
from app.ia import ClienteIA
from app.seguridad import anonimizar

GEMINI = Proveedor("gemini", "openai", "clave-gemini", "gemini-flash", "https://gemini.prueba/v1beta/openai/")
GROQ = Proveedor("groq", "openai", "clave-groq", "llama", "https://groq.prueba/openai/v1/")
COHERE = Proveedor("cohere", "cohere", "clave-cohere", "command")


def cliente_ia(proveedores, respuestas):
    """`respuestas` dice, por servicio, qué devuelve. Se registran las llamadas para revisarlas."""
    llamadas = []

    def manejar(peticion: httpx.Request) -> httpx.Response:
        llamadas.append(peticion)
        servicio = {"gemini.prueba": "gemini", "groq.prueba": "groq", "api.cohere.com": "cohere"}[peticion.url.host]
        return respuestas[servicio](json.loads(peticion.content))

    config = Config(proveedores=proveedores, busqueda_semantica="ninguna", fuentes_web=False)
    return ClienteIA(config, httpx.Client(transport=httpx.MockTransport(manejar))), llamadas


def openai(texto):
    return lambda cuerpo: httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": texto}}]})


def falla(codigo):
    return lambda cuerpo: httpx.Response(codigo, json={"error": "sin cuota"})


def test_si_un_servicio_se_queda_sin_cuota_responde_el_siguiente():
    ia, llamadas = cliente_ia([GEMINI, GROQ, COHERE], {"gemini": falla(429), "groq": openai("Respuesta de Groq"), "cohere": falla(500)})
    assert ia.chat("sistema", "pregunta") == "Respuesta de Groq"
    assert ia.ultimo_proveedor == "groq"
    assert [l.url.host for l in llamadas] == ["gemini.prueba", "groq.prueba"]  # Cohere ni se intenta
    assert llamadas[0].headers["authorization"] == "Bearer clave-gemini"
    assert llamadas[1].headers["authorization"] == "Bearer clave-groq"
    pedido = json.loads(llamadas[1].content)
    assert pedido["model"] == "llama"
    assert pedido["messages"][0] == {"role": "system", "content": "sistema"}
    assert str(llamadas[1].url) == "https://groq.prueba/openai/v1/chat/completions"


def test_si_todos_fallan_devuelve_none():
    ia, _ = cliente_ia([GEMINI, COHERE], {"gemini": falla(503), "cohere": falla(429)})
    assert ia.chat("sistema", "pregunta") is None


def test_una_respuesta_vacia_cuenta_como_fallo():
    ia, _ = cliente_ia([GEMINI, GROQ], {"gemini": openai("   "), "groq": openai("Hola")})
    assert ia.chat("s", "p") == "Hola"


def test_respuesta_malformada_no_rompe():
    ia, _ = cliente_ia([GEMINI], {"gemini": lambda c: httpx.Response(200, json={"inesperado": True})})
    assert ia.chat("s", "p") is None


def test_describir_nunca_muestra_claves():
    ia, _ = cliente_ia([GEMINI, GROQ, COHERE], {})
    texto = json.dumps(ia.describir())
    assert "gemini" in texto and "groq" in texto
    assert "clave-" not in texto


def test_orden_de_proveedores_desde_el_entorno(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("GROQ_API_KEY", "q")
    monkeypatch.setenv("IA_LOCAL_URL", "http://localhost:11434/v1/")
    monkeypatch.setenv("IA_LOCAL_MODELO", "llama3.2")
    monkeypatch.setenv("IA_PROVEEDORES", "groq,local,gemini")
    config = Config()
    assert [p.nombre for p in config.proveedores] == ["groq", "local", "gemini"]
    assert config.proveedor("local").url == "http://localhost:11434/v1/"
    assert config.ia_activa


def test_sin_claves_no_hay_ia(monkeypatch):
    assert Config().proveedores == []
    assert Config().ia_activa is False


def test_produccion_endurece_la_configuracion():
    config = Config(entorno="produccion", demo_clave="algo", cookie_segura=False, proveedores=[], fuentes_web=False)
    assert config.produccion and config.cookie_segura and config.demo_clave == ""


def test_el_dia_se_puede_fijar_para_demostraciones(monkeypatch):
    monkeypatch.setenv("FECHA_HOY", "2027-02-01")
    assert db.hoy() == "2027-02-01"
    monkeypatch.delenv("FECHA_HOY")
    assert len(db.hoy()) == 10
    assert db.sumar_dias("2026-12-28", 5) == "2027-01-02"


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("mi cédula es 1.144.555.777", "mi cédula es [número]"),
        ("escríbeme al 300 123 4567", "escríbeme al [número]"),
        ("mi correo es ana@gmail.com", "mi correo es [correo]"),
        ("Soy Ana María Pérez", "Soy [nombre]"),
        ("Soy estudiante de Medicina", "Soy estudiante de Medicina"),
        ("el artículo 62 del Acuerdo 009 de 1997", "el artículo 62 del Acuerdo 009 de 1997"),
        ("¿la matrícula cuesta 1.300.000 pesos?", "¿la matrícula cuesta 1.300.000 pesos?"),
        ("pagué $1.300.000", "pagué $1.300.000"),
        ("del 5 al 19 de noviembre de 2026", "del 5 al 19 de noviembre de 2026"),
    ],
)
def test_anonimizar_protege_datos_sin_dañar_la_pregunta(texto, esperado):
    assert anonimizar(texto) == esperado


def test_el_perfil_prioriza_el_contenido_de_su_publico():
    documentos = [
        Documento(1, "faq", "¿Qué documentos necesito para la matrícula?", "Para estudiantes antiguos: paz y salvo.", publico="estudiante"),
        Documento(2, "faq", "¿Qué documentos necesito para la matrícula?", "Para admitidos: documento y diploma.", publico="aspirante"),
    ]
    indice = Indice(documentos)
    assert indice.buscar("documentos para la matrícula", perfil="aspirante")[0].documento.id == 2
    assert indice.buscar("documentos para la matrícula", perfil="estudiante")[0].documento.id == 1
