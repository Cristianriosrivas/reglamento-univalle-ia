"""Comprueba el flujo completo por la API, como lo usan el chat y el panel."""
import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import crear_app
from conftest import CLAVE, ORIGEN_EXTERNO, entrar

PANEL = {"X-Panel": "1"}
EDITOR = "editor.registro@demo.local"
APROBADOR = "aprobador.registro@demo.local"
ADMIN = "admin@demo.local"
PREGUNTA_FECHA = "¿Cuándo es la ceremonia de grado?"


def preguntar(cliente, pregunta=PREGUNTA_FECHA):
    return cliente.post("/api/chat", json={"pregunta": pregunta}).json()


def id_de(cliente, q):
    return cliente.get("/api/panel/contenidos", params={"q": q}).json()["items"][0]["id"]


def accion(cliente, contenido_id, nombre, datos=None):
    return cliente.post(f"/api/panel/contenidos/{contenido_id}/{nombre}", json=datos or {}, headers=PANEL)


def editar_fecha(cliente, contenido_id, fecha="2026-12-19"):
    return cliente.post(f"/api/panel/contenidos/{contenido_id}", json={"inicio": fecha, "fin": fecha}, headers=PANEL)


# ----- Público -----
def test_paginas_y_widget(cliente):
    assert cliente.get("/demo").status_code == 200
    assert cliente.get("/panel").status_code == 200
    widget = cliente.get("/widget.js")
    assert widget.status_code == 200
    assert "javascript" in widget.headers["content-type"]
    assert widget.headers["cross-origin-resource-policy"] == "cross-origin"


def test_config_trae_sugerencias_y_politica(cliente):
    datos = cliente.get("/api/config").json()
    assert len(datos["sugerencias"]) == 4
    assert datos["politica"].startswith("https://registro.univalle.edu.co/")


def test_chat_responde_con_fuentes(cliente):
    datos = preguntar(cliente)
    assert "12 de diciembre" in datos["respuesta"]
    assert datos["fuentes"][0]["url"].startswith("https://")


def test_rechaza_preguntas_vacias_y_gigantes(cliente):
    assert cliente.post("/api/chat", json={"pregunta": ""}).status_code == 422
    assert cliente.post("/api/chat", json={"pregunta": "x" * 3000}).status_code == 422


def test_limite_de_preguntas(ruta_db):
    config = Config(ruta_db=ruta_db, limite_minuto=2, limite_dia=100, origenes=[])
    with TestClient(crear_app(config)) as cliente:
        assert cliente.post("/api/chat", json={"pregunta": "hola"}).status_code == 200
        assert cliente.post("/api/chat", json={"pregunta": "hola"}).status_code == 200
        bloqueada = cliente.post("/api/chat", json={"pregunta": "hola"})
    assert bloqueada.status_code == 429
    assert "Espera" in bloqueada.json()["detail"]


@pytest.mark.parametrize(
    "origen,permitido",
    [
        (ORIGEN_EXTERNO, True),
        ("https://www.univalle.edu.co", True),
        ("https://registro.univalle.edu.co", True),
        ("https://univalle.edu.co.sitio-falso.com", False),
        ("http://www.univalle.edu.co", False),
        ("https://evil.example", False),
    ],
)
def test_cors_solo_para_sitios_permitidos(cliente, origen, permitido):
    respuesta = cliente.options(
        "/api/chat", headers={"Origin": origen, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    )
    assert (respuesta.headers.get("access-control-allow-origin") == origen) is permitido


def test_cors_no_permite_la_cabecera_del_panel(cliente):
    respuesta = cliente.options(
        "/api/panel/entrar",
        headers={"Origin": ORIGEN_EXTERNO, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-panel"},
    )
    assert respuesta.status_code == 400


# ----- Acceso al panel -----
def test_el_panel_exige_sesion(cliente):
    assert cliente.get("/api/panel/contenidos").status_code == 401
    assert cliente.post("/api/panel/contenidos", json={}, headers=PANEL).status_code == 401


def test_clave_incorrecta(cliente):
    respuesta = cliente.post("/api/panel/entrar", json={"correo": EDITOR, "clave": "mala"}, headers=PANEL)
    assert respuesta.status_code == 401


def test_bloquea_ataques_de_fuerza_bruta(cliente):
    for _ in range(6):
        cliente.post("/api/panel/entrar", json={"correo": EDITOR, "clave": "mala"}, headers=PANEL)
    respuesta = cliente.post("/api/panel/entrar", json={"correo": EDITOR, "clave": CLAVE}, headers=PANEL)
    assert respuesta.status_code == 429


def test_sin_cabecera_del_panel_no_se_puede_escribir(cliente):
    entrar(cliente, EDITOR)
    assert cliente.post("/api/panel/salir").status_code == 403


def test_la_cookie_es_segura_contra_scripts_y_otros_sitios(cliente):
    respuesta = cliente.post("/api/panel/entrar", json={"correo": EDITOR, "clave": CLAVE}, headers=PANEL)
    cabecera = respuesta.headers["set-cookie"].lower()
    assert "httponly" in cabecera
    assert "samesite=strict" in cabecera


def test_salir_invalida_la_sesion(cliente):
    entrar(cliente, EDITOR)
    token = cliente.cookies.get("sesion_panel")
    cliente.post("/api/panel/salir", headers=PANEL)
    cliente.cookies.set("sesion_panel", token)
    assert cliente.get("/api/panel/yo").status_code == 401


def test_panel_con_cabeceras_de_seguridad(cliente):
    respuesta = cliente.get("/panel")
    assert "default-src 'self'" in respuesta.headers["content-security-policy"]
    assert respuesta.headers["x-frame-options"] == "DENY"


# ----- Flujo de publicación -----
def test_flujo_completo_de_una_actualizacion(cliente):
    assert "12 de diciembre" in preguntar(cliente)["respuesta"]

    entrar(cliente, EDITOR)
    contenido = id_de(cliente, "Ceremonia solemne")
    assert editar_fecha(cliente, contenido).status_code == 200

    # Mientras no se publique, el público sigue viendo la fecha anterior.
    assert "12 de diciembre" in preguntar(cliente)["respuesta"]

    # La prueba privada ya usa el cambio.
    prueba = cliente.post("/api/panel/probar", json={"pregunta": PREGUNTA_FECHA}, headers=PANEL).json()
    assert "19 de diciembre" in prueba["respuesta"]
    assert prueba["fuentes"][0]["borrador"] is True

    assert accion(cliente, contenido, "enviar").status_code == 200
    assert accion(cliente, contenido, "publicar").status_code == 403

    entrar(cliente, APROBADOR)
    assert accion(cliente, contenido, "publicar").status_code == 200
    assert "19 de diciembre" in preguntar(cliente)["respuesta"]

    versiones = cliente.get(f"/api/panel/contenidos/{contenido}").json()["versiones"]
    assert [v["accion"] for v in versiones[:3]] == ["publicado", "enviado a revisión", "editado"]
    assert versiones[0]["autor"] == "Aprobador de Registro"


def test_restaurar_una_version_anterior(cliente):
    entrar(cliente, APROBADOR)
    contenido = id_de(cliente, "Ceremonia solemne")
    editar_fecha(cliente, contenido)
    accion(cliente, contenido, "publicar")
    original = cliente.get(f"/api/panel/contenidos/{contenido}").json()["versiones"][-1]
    assert original["accion"] == "carga inicial"

    assert accion(cliente, contenido, f"restaurar/{original['id']}").status_code == 200
    assert "19 de diciembre" in preguntar(cliente)["respuesta"]  # restaurar también pasa por aprobación
    accion(cliente, contenido, "publicar")
    assert "12 de diciembre" in preguntar(cliente)["respuesta"]


def test_devolver_exige_una_explicacion(cliente):
    entrar(cliente, EDITOR)
    contenido = id_de(cliente, "Ceremonia solemne")
    editar_fecha(cliente, contenido)
    accion(cliente, contenido, "enviar")
    entrar(cliente, APROBADOR)
    assert accion(cliente, contenido, "devolver", {"nota": "no"}).status_code == 400
    assert accion(cliente, contenido, "devolver", {"nota": "La fecha no coincide con la resolución"}).status_code == 200
    datos = cliente.get(f"/api/panel/contenidos/{contenido}").json()
    assert datos["pendiente_estado"] == "borrador"
    assert "resolución" in datos["nota_revision"]


def test_descartar_cambios(cliente):
    entrar(cliente, EDITOR)
    contenido = id_de(cliente, "Ceremonia solemne")
    editar_fecha(cliente, contenido)
    assert accion(cliente, contenido, "descartar").status_code == 200
    assert cliente.get(f"/api/panel/contenidos/{contenido}").json()["tiene_cambios"] is False


def test_un_editor_no_toca_otra_dependencia(cliente):
    entrar(cliente, "editor.admisiones@demo.local")
    contenido = id_de(cliente, "Ceremonia solemne")
    respuesta = editar_fecha(cliente, contenido)
    assert respuesta.status_code == 403
    assert "Registro Académico" in respuesta.json()["detail"]


def test_un_aprobador_no_publica_en_otra_dependencia(cliente):
    entrar(cliente, "aprobador.secretaria@demo.local")
    assert accion(cliente, id_de(cliente, "Ceremonia solemne"), "publicar").status_code == 403


def test_retirar_saca_el_contenido_del_asistente(cliente):
    entrar(cliente, APROBADOR)
    contenido = id_de(cliente, "Ceremonia solemne")
    assert accion(cliente, contenido, "archivar").status_code == 200
    assert "12 de diciembre" not in preguntar(cliente)["respuesta"]


def test_crear_y_publicar_una_pregunta_frecuente(cliente):
    pregunta = "¿Dónde queda el laboratorio de idiomas de la sede?"
    entrar(cliente, APROBADOR)
    respuesta = cliente.post(
        "/api/panel/contenidos",
        json={"tipo": "faq", "titulo": pregunta, "texto": "En el edificio de prueba."},
        headers=PANEL,
    )
    assert respuesta.status_code == 200
    assert "edificio de prueba" not in preguntar(cliente, pregunta)["respuesta"]
    accion(cliente, respuesta.json()["id"], "publicar")
    assert "edificio de prueba" in preguntar(cliente, pregunta)["respuesta"]


@pytest.mark.parametrize(
    "cambios,mensaje",
    [
        ({"titulo": "x"}, "título"),
        ({"texto": ""}, "texto"),
        ({"url": "javascript:alert(1)"}, "enlace"),
        ({"fin": "31/12/2026"}, "formato"),
        ({"fin": ""}, "finalización"),
        ({"inicio": "2026-12-20", "fin": "2026-12-01"}, "posterior"),
    ],
)
def test_valida_lo_que_se_guarda(cliente, cambios, mensaje):
    entrar(cliente, EDITOR)
    contenido = id_de(cliente, "Ceremonia solemne")
    respuesta = cliente.post(f"/api/panel/contenidos/{contenido}", json=cambios, headers=PANEL)
    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]


def test_json_invalido_no_tumba_el_panel(cliente):
    entrar(cliente, EDITOR)
    cabeceras = {**PANEL, "Content-Type": "application/json"}
    assert cliente.post("/api/panel/contenidos", content="{no es json", headers=cabeceras).status_code == 422


@pytest.mark.parametrize("campo,valor", [("reemplaza", 999999), ("fuente_id", 999999), ("numero", "x")])
def test_rechaza_referencias_invalidas(cliente, campo, valor):
    entrar(cliente, ADMIN)
    respuesta = cliente.post(
        "/api/panel/contenidos",
        json={"tipo": "articulo", "dependencia": "Secretaría General", "titulo": "Artículo 1", "texto": "Texto de prueba", campo: valor},
        headers=PANEL,
    )
    assert respuesta.status_code == 400


def test_una_segunda_edicion_no_pierde_la_primera(cliente):
    entrar(cliente, EDITOR)
    contenido = id_de(cliente, "Ceremonia solemne")
    editar_fecha(cliente, contenido)
    cliente.post(f"/api/panel/contenidos/{contenido}", json={"texto": "Descripción nueva de la ceremonia"}, headers=PANEL)
    vista = cliente.get(f"/api/panel/contenidos/{contenido}").json()["vista"]
    assert vista["fin"] == "2026-12-19"
    assert vista["texto"] == "Descripción nueva de la ceremonia"


def test_la_norma_nueva_reemplaza_a_la_anterior(cliente):
    entrar(cliente, ADMIN)
    anterior = cliente.get("/api/panel/contenidos", params={"q": "reconocerá y apoyará la existencia de Consejos Estudiantiles en los"}).json()["items"][0]
    nuevo = cliente.post(
        "/api/panel/contenidos",
        json={
            "tipo": "articulo", "dependencia": "Secretaría General", "titulo": "Artículo 14 — Acuerdo de prueba",
            "texto": "Texto nuevo de prueba sobre consejos estudiantiles.", "numero": 14, "reemplaza": anterior["id"],
        },
        headers=PANEL,
    ).json()["id"]
    accion(cliente, nuevo, "publicar")
    respuesta = preguntar(cliente, "artículo 14")
    assert "Texto nuevo de prueba" in respuesta["respuesta"]


def test_acuerdo_en_revision_no_llega_al_publico(cliente):
    entrar(cliente, ADMIN)
    en_revision = cliente.get("/api/panel/contenidos", params={"estado": "revision"}).json()
    assert en_revision["total"] == 2
    assert all("Acuerdo 004 de 2024" in i["titulo"] for i in en_revision["items"])
    assert "febrero - junio de 2024" not in preguntar(cliente, "suspensión transitoria artículos 62 63 febrero junio 2024")["respuesta"]


# ----- Importar -----
def test_importar_crea_borradores_que_no_llegan_al_publico(cliente):
    entrar(cliente, EDITOR)
    texto = "ARTÍCULO 1. Los estudiantes de intercambio lunar deberán registrarse.\nARTÍCULO 2. Otra disposición sobre astronautas."
    vista = cliente.post("/api/panel/importar", files={"archivo": ("norma.txt", texto.encode())}, headers=PANEL).json()
    assert [s["numero"] for s in vista["segmentos"]] == [1, 2]

    confirmacion = cliente.post(
        "/api/panel/importar/confirmar",
        json={"nombre": "Acuerdo 099 de 2026", "dependencia": "Registro Académico", "segmentos": vista["segmentos"]},
        headers=PANEL,
    )
    assert confirmacion.json() == {"creados": 2}
    assert "lunar" not in preguntar(cliente, "intercambio lunar astronautas")["respuesta"]
    borradores = cliente.get("/api/panel/contenidos", params={"estado": "borrador"}).json()
    assert borradores["total"] == 2


def test_importar_no_recorta_articulos_largos(cliente):
    entrar(cliente, EDITOR)
    texto = "ARTÍCULO 1. " + "palabra " * 3000
    vista = cliente.post("/api/panel/importar", files={"archivo": ("norma.txt", texto.encode())}, headers=PANEL).json()
    assert len(vista["segmentos"][0]["texto"]) > 20_000
    respuesta = cliente.post(
        "/api/panel/importar/confirmar",
        json={"nombre": "Acuerdo largo", "dependencia": "Registro Académico", "segmentos": vista["segmentos"]},
        headers=PANEL,
    )
    assert respuesta.json() == {"creados": 1}


def test_el_articulo_mas_largo_se_puede_editar(cliente):
    entrar(cliente, ADMIN)
    contenido = id_de(cliente, "grupos poblaciones especiales")
    respuesta = cliente.post(f"/api/panel/contenidos/{contenido}", json={"capitulo": "Capítulo de prueba"}, headers=PANEL)
    assert respuesta.status_code == 200


def test_importar_avisa_del_formato_no_admitido(cliente):
    entrar(cliente, EDITOR)
    respuesta = cliente.post("/api/panel/importar", files={"archivo": ("a.exe", b"MZ")}, headers=PANEL)
    assert respuesta.status_code == 400
    assert "PDF" in respuesta.json()["detail"]


def test_importar_un_pdf_danado_no_tumba_el_panel(cliente):
    entrar(cliente, EDITOR)
    respuesta = cliente.post("/api/panel/importar", files={"archivo": ("a.pdf", b"esto no es un pdf")}, headers=PANEL)
    assert respuesta.status_code == 400


def test_no_se_importa_a_otra_dependencia(cliente):
    entrar(cliente, EDITOR)
    respuesta = cliente.post(
        "/api/panel/importar/confirmar",
        json={"nombre": "Acuerdo 099", "dependencia": "Admisiones", "segmentos": [{"titulo": "Artículo 1", "texto": "Texto de prueba"}]},
        headers=PANEL,
    )
    assert respuesta.status_code == 403


# ----- Preguntas sin respuesta y resumen -----
def test_preguntas_sin_respuesta_se_agrupan_y_se_resuelven(cliente):
    pregunta = "¿representantes estudiantiles de bienestar deportivo en la sede?"
    tipos = {preguntar(cliente, pregunta)["tipo"] for _ in range(2)}
    entrar(cliente, EDITOR)
    filas = cliente.get("/api/panel/sin-respuesta").json()
    if "sin_informacion" in tipos:
        assert filas[0]["veces"] == 2
        assert cliente.post(f"/api/panel/sin-respuesta/{filas[0]['id']}/resolver", headers=PANEL).status_code == 200
        assert cliente.get("/api/panel/sin-respuesta").json() == []


def test_resumen(cliente):
    preguntar(cliente)
    entrar(cliente, EDITOR)
    datos = cliente.get("/api/panel/resumen").json()
    assert datos["preguntas_hoy"] == 1
    assert datos["publicados"]["faq"] == 28
    assert datos["en_revision"] == 2
    assert datos["ia"] is False
