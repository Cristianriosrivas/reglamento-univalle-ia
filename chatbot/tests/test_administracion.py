"""Modo de administración: usuarios, ajustes, novedades, páginas oficiales y estadísticas, por la API del panel."""
import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.main import crear_app
from conftest import CLAVE, entrar
from test_fuentes_web import PREGUNTAS_HTML, URL, wordpress

PANEL = {"X-Panel": "1"}
ADMIN = "admin@demo.local"
EDITOR = "editor.registro@demo.local"
APROBADOR = "aprobador.registro@demo.local"


def post(cliente, ruta, datos=None):
    return cliente.post("/api/panel" + ruta, json=datos if datos is not None else {}, headers=PANEL)


def preguntar(cliente, pregunta, perfil=None):
    return cliente.post("/api/chat", json={"pregunta": pregunta, "perfil": perfil}).json()


def id_usuario(cliente, correo):
    return next(u["id"] for u in cliente.get("/api/panel/usuarios").json() if u["correo"] == correo)


def publicar_novedad(cliente, **campos):
    datos = {
        "tipo": "novedad", "dependencia": "Registro Académico", "titulo": "Plazo extendido para cancelar asignaturas",
        "texto": "Registro Académico extendió hasta el **5 de diciembre de 2026** el plazo para cancelar asignaturas.",
        "fin": "2026-12-05", "destacada": True, "publico": "estudiante", **campos,
    }
    nuevo = post(cliente, "/contenidos", datos)
    assert nuevo.status_code == 200, nuevo.text
    assert post(cliente, f"/contenidos/{nuevo.json()['id']}/publicar").status_code == 200
    return nuevo.json()["id"]


# ----- Usuarios -----
def test_una_cuenta_nueva_debe_cambiar_su_clave_temporal(cliente):
    entrar(cliente, ADMIN)
    creada = post(cliente, "/usuarios", {"correo": "Nueva.Persona@correounivalle.edu.co", "nombre": "Nueva Persona", "rol": "editor", "dependencia": "Admisiones"})
    assert creada.status_code == 200
    temporal = creada.json()["clave_temporal"]
    assert len(temporal) >= 10

    entrada = cliente.post("/api/panel/entrar", json={"correo": "nueva.persona@correounivalle.edu.co", "clave": temporal}, headers=PANEL)
    assert entrada.json()["debe_cambiar_clave"] is True
    assert cliente.get("/api/panel/yo").json()["debe_cambiar_clave"] is True
    assert cliente.get("/api/panel/contenidos").status_code == 403  # nada más hasta cambiarla

    assert post(cliente, "/mi-clave", {"actual": temporal, "nueva": "corta1"}).status_code == 400
    assert post(cliente, "/mi-clave", {"actual": temporal, "nueva": "soloLetrasLargas"}).status_code == 400
    assert post(cliente, "/mi-clave", {"actual": "equivocada", "nueva": "MiClaveNueva2026"}).status_code == 403
    assert post(cliente, "/mi-clave", {"actual": temporal, "nueva": "MiClaveNueva2026"}).status_code == 200
    assert cliente.get("/api/panel/contenidos").status_code == 200


def test_solo_un_administrador_maneja_usuarios_y_ajustes(cliente):
    entrar(cliente, APROBADOR)
    assert cliente.get("/api/panel/usuarios").status_code == 403
    assert post(cliente, "/usuarios", {"correo": "x@y.co", "nombre": "Alguien", "rol": "admin"}).status_code == 403
    assert post(cliente, "/ajustes", {"nombre": "Otro nombre"}).status_code == 403
    assert cliente.get("/api/panel/ajustes").status_code == 200  # puede verlos


def test_siempre_queda_un_administrador(cliente):
    entrar(cliente, ADMIN)
    admin = id_usuario(cliente, ADMIN)
    degradar = post(cliente, f"/usuarios/{admin}", {"rol": "editor", "dependencia": "Admisiones"})
    assert degradar.status_code == 400
    assert "administrador" in degradar.json()["detail"]
    assert post(cliente, f"/usuarios/{admin}", {"activo": False}).status_code == 400


def test_desactivar_una_cuenta_cierra_su_sesion(cliente):
    entrar(cliente, EDITOR)
    token = cliente.cookies.get("sesion_panel")
    entrar(cliente, ADMIN)
    assert post(cliente, f"/usuarios/{id_usuario(cliente, EDITOR)}", {"activo": False}).status_code == 200
    cliente.cookies.clear()
    cliente.cookies.set("sesion_panel", token)
    assert cliente.get("/api/panel/yo").status_code == 401
    respuesta = cliente.post("/api/panel/entrar", json={"correo": EDITOR, "clave": CLAVE}, headers=PANEL)
    assert respuesta.status_code == 401


def test_cambiar_el_rol_obliga_a_entrar_de_nuevo(cliente):
    entrar(cliente, EDITOR)
    token = cliente.cookies.get("sesion_panel")
    entrar(cliente, ADMIN)
    post(cliente, f"/usuarios/{id_usuario(cliente, EDITOR)}", {"rol": "aprobador"})
    cliente.cookies.clear()
    cliente.cookies.set("sesion_panel", token)
    assert cliente.get("/api/panel/yo").status_code == 401
    assert entrar(cliente, EDITOR).get("/api/panel/yo").json()["rol"] == "aprobador"


def test_restablecer_la_clave(cliente):
    entrar(cliente, ADMIN)
    temporal = post(cliente, f"/usuarios/{id_usuario(cliente, EDITOR)}/clave").json()["clave_temporal"]
    cliente.cookies.clear()
    assert cliente.post("/api/panel/entrar", json={"correo": EDITOR, "clave": CLAVE}, headers=PANEL).status_code == 401
    assert entrar(cliente, EDITOR, temporal).get("/api/panel/yo").json()["debe_cambiar_clave"] is True


@pytest.mark.parametrize(
    "datos,mensaje",
    [
        ({"correo": "no-es-correo", "nombre": "Alguien", "rol": "editor", "dependencia": "Admisiones"}, "correo"),
        ({"correo": EDITOR, "nombre": "Alguien", "rol": "editor", "dependencia": "Admisiones"}, "Ya existe"),
        ({"correo": "a@b.co", "nombre": "Alguien", "rol": "superusuario"}, "rol"),
        ({"correo": "a@b.co", "nombre": "Alguien", "rol": "editor"}, "dependencia"),
    ],
)
def test_valida_las_cuentas_nuevas(cliente, datos, mensaje):
    entrar(cliente, ADMIN)
    respuesta = post(cliente, "/usuarios", datos)
    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]


# ----- Ajustes -----
def test_los_ajustes_cambian_el_chat_al_instante(cliente):
    entrar(cliente, ADMIN)
    guardados = post(cliente, "/ajustes", {
        "nombre": "Búho Univalle", "bienvenida": "¡Hola! Pregúntame lo que quieras de la Universidad.",
        "sugerencias_estudiante": "¿Cómo cancelo una materia?\n\n¿Qué es el bajo rendimiento?",
    })
    assert guardados.status_code == 200
    config = cliente.get("/api/config").json()
    assert config["nombre"] == "Búho Univalle"
    assert config["sugerencias"]["estudiante"] == ["¿Cómo cancelo una materia?", "¿Qué es el bajo rendimiento?"]
    assert len(config["sugerencias"]["aspirante"]) == 4


@pytest.mark.parametrize(
    "datos",
    [{"nombre": ""}, {"nombre": "x" * 80}, {"max_llamadas_ia_dia": -5}, {"sugerencias_aspirante": ["x" * 200]}, {"clave_secreta": "1"}],
)
def test_rechaza_ajustes_invalidos(cliente, datos):
    entrar(cliente, ADMIN)
    assert post(cliente, "/ajustes", datos).status_code == 400


# ----- Novedades -----
def test_una_novedad_destacada_aparece_en_el_chat_y_en_las_respuestas(cliente):
    entrar(cliente, ADMIN)
    publicar_novedad(cliente)
    aviso = cliente.get("/api/config").json()["aviso"]
    assert aviso["titulo"] == "Plazo extendido para cancelar asignaturas"

    novedades = preguntar(cliente, "¿Qué novedades hay?", "estudiante")
    assert novedades["tipo"] == "novedades"
    assert "Plazo extendido" in novedades["respuesta"]

    # La norma dice «séptima semana», pero este semestre hay un aviso que la cambia: se dicen las dos cosas.
    plazo = preguntar(cliente, "¿Cuál es el plazo para cancelar una asignatura?", "estudiante")
    assert "séptima semana" in plazo["respuesta"]
    assert "Importante — Plazo extendido para cancelar asignaturas" in plazo["respuesta"]
    assert "Plazo extendido para cancelar asignaturas" in [f["titulo"] for f in plazo["fuentes"]]

    # Una pregunta de otro tema no arrastra el aviso.
    assert "Importante" not in preguntar(cliente, "¿Qué es una homologación?", "estudiante")["respuesta"]


def test_una_novedad_vencida_deja_de_mostrarse(cliente):
    entrar(cliente, ADMIN)
    publicar_novedad(cliente, inicio="2026-10-01", fin="2026-11-10")
    assert cliente.get("/api/config").json()["aviso"] is None
    assert "Plazo extendido" not in preguntar(cliente, "¿Cuál es el plazo para cancelar una asignatura?")["respuesta"]


def test_una_novedad_programada_no_se_adelanta(cliente):
    entrar(cliente, ADMIN)
    publicar_novedad(cliente, inicio="2026-11-20", fin="2026-12-05")
    assert cliente.get("/api/config").json()["aviso"] is None


# ----- Perfiles -----
def test_el_perfil_debe_ser_valido(cliente):
    assert cliente.post("/api/chat", json={"pregunta": "hola", "perfil": "rector"}).status_code == 422
    assert cliente.post("/api/chat", json={"pregunta": "hola", "perfil": "aspirante"}).status_code == 200


def test_la_prueba_privada_acepta_perfil(cliente):
    entrar(cliente, EDITOR)
    respuesta = post(cliente, "/probar", {"pregunta": "¿Cuánto cuesta la inscripción?", "perfil": "aspirante"})
    assert respuesta.status_code == 200
    assert "Admisiones" in respuesta.json()["respuesta"]


# ----- Valoraciones y estadísticas -----
def test_valoraciones_y_estadisticas(cliente):
    respuesta = preguntar(cliente, "¿Cuál es el plazo para cancelar una asignatura?")
    preguntar(cliente, "cuál es la capital de Francia")
    for util in (True, False):
        valoracion = cliente.post("/api/valoracion", json={
            "pregunta": "Soy Ana Ruiz, código 202012345 ¿plazo para cancelar?", "tipo": respuesta["tipo"],
            "fuentes": [f["titulo"] for f in respuesta["fuentes"]], "util": util,
        })
        assert valoracion.status_code == 200

    entrar(cliente, EDITOR)
    datos = cliente.get("/api/panel/estadisticas", params={"dias": 14}).json()
    assert len(datos["dias"]) == 14
    assert datos["dias"][-1] == {"dia": "2026-11-16", "preguntas": 2, "ia": 0, "sin_respuesta": 0}
    assert datos["preguntas"] == 2
    assert datos["tipos"]["aprobada"] == 1
    assert datos["tipos"]["fuera_de_tema"] == 1
    assert datos["sin_ia"] == 50
    assert datos["valoraciones"] == {"utiles": 1, "total": 2, "porcentaje": 50}
    mala = datos["mal_valoradas"][0]
    assert mala["pregunta"] == "Soy [nombre], código [número] ¿plazo para cancelar?"
    assert mala["fuentes"] == ["Acuerdo 009 de 1997"]


def test_la_prueba_privada_no_cuenta_en_las_estadisticas(cliente):
    entrar(cliente, EDITOR)
    post(cliente, "/probar", {"pregunta": "¿Cuál es el plazo para cancelar una asignatura?"})
    assert cliente.get("/api/panel/estadisticas").json()["preguntas"] == 0


def test_estado_de_la_ia_sin_claves(cliente):
    entrar(cliente, EDITOR)
    estado = cliente.get("/api/panel/ia").json()
    assert estado == {"proveedores": [], "busqueda": {"nombre": "ninguna", "modelo": "", "remota": False}}


# ----- Páginas oficiales desde el panel -----
@pytest.fixture
def cliente_web(config):
    with TestClient(crear_app(config, http_web=wordpress(PREGUNTAS_HTML))) as abierto:
        yield abierto


def test_agregar_una_pagina_oficial_la_vuelve_respuesta(cliente_web):
    pregunta = "¿Quién puede pedir la beca de excelencia deportiva?"
    assert "torneos oficiales" not in preguntar(cliente_web, pregunta)["respuesta"]

    entrar(cliente_web, ADMIN)
    agregada = post(cliente_web, "/fuentes-web", {"nombre": "Becas deportivas", "url": URL, "dependencia": "Bienestar Universitario", "publico": "estudiante"})
    assert agregada.status_code == 200, agregada.text
    assert agregada.json()["nuevas"] >= 4
    respuesta = preguntar(cliente_web, pregunta, "estudiante")
    assert "torneos oficiales" in respuesta["respuesta"]
    assert respuesta["fuentes"][0]["url"] == URL

    # Lo que viene de la web no se edita en el panel: se corrige en la página.
    contenido = cliente_web.get("/api/panel/contenidos", params={"origen": "web", "q": "excelencia deportiva"}).json()["items"][0]
    assert contenido["fuente"] == "Becas deportivas"

    # Pausar la fuente la saca del asistente.
    assert post(cliente_web, f"/fuentes-web/{agregada.json()['id']}/activa", {"activa": False}).status_code == 200
    assert "torneos oficiales" not in preguntar(cliente_web, pregunta)["respuesta"]


def test_un_editor_no_agrega_paginas(cliente_web):
    entrar(cliente_web, EDITOR)
    respuesta = post(cliente_web, "/fuentes-web", {"nombre": "Becas", "url": URL, "dependencia": "Registro Académico"})
    assert respuesta.status_code == 403


def test_no_se_agregan_paginas_de_otros_sitios(cliente_web):
    entrar(cliente_web, ADMIN)
    respuesta = post(cliente_web, "/fuentes-web", {"nombre": "Otra", "url": "https://sitio-falso.com/", "dependencia": "Registro Académico"})
    assert respuesta.status_code == 400


# ----- Producción -----
def test_en_produccion_no_hay_cuentas_de_prueba_y_la_cookie_es_segura(tmp_path):
    config = Config(
        entorno="produccion", ruta_db=tmp_path / "produccion.db", proveedores=[], demo_clave=CLAVE,
        busqueda_semantica="ninguna", fuentes_web=False, cookie_segura=False,
    )
    assert config.demo_clave == "" and config.cookie_segura is True
    with TestClient(crear_app(config)) as cliente:
        assert cliente.post("/api/panel/entrar", json={"correo": ADMIN, "clave": CLAVE}, headers=PANEL).status_code == 401
        assert "12 de diciembre" in preguntar(cliente, "¿Cuándo es la ceremonia de grado?")["respuesta"]


@pytest.mark.parametrize("clave,entra", [("ClaveSegura2026", True), ("corta", False)])
def test_la_primera_cuenta_de_administracion_desde_variables(tmp_path, clave, entra):
    config = Config(
        entorno="produccion", ruta_db=tmp_path / "servidor.db", proveedores=[], busqueda_semantica="ninguna",
        fuentes_web=False, admin_correo="jefe@correounivalle.edu.co", admin_clave=clave,
    )
    assert clave not in repr(config)
    with TestClient(crear_app(config)) as cliente:
        respuesta = cliente.post("/api/panel/entrar", json={"correo": "jefe@correounivalle.edu.co", "clave": clave}, headers=PANEL)
    assert (respuesta.status_code == 200) is entra


def test_crear_el_primer_administrador_desde_la_consola(tmp_path, monkeypatch, capsys):
    from app import admin, db

    ruta = tmp_path / "nueva.db"
    monkeypatch.setattr(admin, "cargar_config", lambda: Config(ruta_db=ruta, proveedores=[], fuentes_web=False))
    monkeypatch.setattr("getpass.getpass", lambda *_: "ClaveSegura2026")
    assert admin.main(["crear", "--correo", "jefe@correounivalle.edu.co", "--nombre", "Jefe de Registro"]) == 0
    conexion = db.conectar(ruta)
    fila = conexion.execute("SELECT rol, debe_cambiar_clave FROM usuarios WHERE correo = 'jefe@correounivalle.edu.co'").fetchone()
    assert (fila["rol"], fila["debe_cambiar_clave"]) == ("admin", 0)


def test_las_respuestas_del_panel_no_se_guardan_en_cache(cliente):
    entrar(cliente, EDITOR)
    assert cliente.get("/api/panel/resumen").headers["cache-control"] == "no-store"
