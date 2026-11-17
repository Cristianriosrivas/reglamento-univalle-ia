"""
Asistente virtual de la Universidad del Valle — versión para Streamlit Community Cloud.

Usa el mismo motor que el chat flotante de `chatbot/`: respuestas aprobadas por las dependencias, texto literal de
las normas, páginas oficiales de Registro Académico y noticias de la Universidad. La IA (Gemini, Groq o Cohere, con
su plan gratuito) solo redacta a partir de esas fuentes; sin clave, el asistente igual responde.

El panel de funcionarios necesita el servidor completo: ver `chatbot/README.md`.
"""
from __future__ import annotations

import html
import os
import sys
from pathlib import Path

import streamlit as st

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ / "chatbot"))

st.set_page_config(page_title="Asistente Univalle", page_icon="🎓", layout="centered")


def _secretos_al_entorno() -> None:
    """En Streamlit Community Cloud las claves se guardan en Settings → Secrets; el motor las lee del entorno."""
    try:
        for clave, valor in st.secrets.items():
            if isinstance(valor, (str, int, float, bool)):
                os.environ.setdefault(clave, str(valor))
    except Exception:  # noqa: BLE001 - sin secrets.toml se usan las variables del sistema o chatbot/.env
        pass


_secretos_al_entorno()

from app import ajustes, semilla  # noqa: E402
from app import contenidos as C  # noqa: E402
from app import fuentes_web as W  # noqa: E402
from app.asistente import Asistente, registrar_valoracion  # noqa: E402
from app.config import cargar_config  # noqa: E402
from app.db import conectar, hoy, inicializar  # noqa: E402

PERFILES = {"estudiante": "Ya soy estudiante", "aspirante": "Quiero estudiar en Univalle"}
VALORABLES = {"aprobada", "ia", "norma", "calendario", "novedades"}


@st.cache_resource(show_spinner="Preparando el asistente…")
def motor():
    """Se crea una vez por servidor: base de datos, índice de búsqueda y lectura periódica de páginas oficiales."""
    config = cargar_config()
    inicializar(config.ruta_db)
    conexion = conectar(config.ruta_db)
    semilla.cargar_si_vacia(conexion, "")  # sin cuentas de prueba: aquí no hay panel
    asistente = Asistente(config)
    asistente.indice_publico(conexion)
    conexion.close()
    if config.fuentes_web:
        W.Programador(config, asistente.invalidar).iniciar()
    return config, asistente


config, asistente = motor()
conexion = conectar(config.ruta_db)
valores = ajustes.todos(conexion)

st.markdown(
    """
    <style>
    .uv-cabecera { padding: 22px 26px; border-radius: 14px; margin-bottom: 14px; color: #fff;
                   background: linear-gradient(120deg, #4a0719, #7a0c2e); }
    .uv-cabecera h1 { margin: 0 0 4px; padding: 0; color: #fff; font-size: 1.9rem; }
    .uv-cabecera p { margin: 0; opacity: .9; }
    .uv-aviso { padding: 10px 14px; border-radius: 10px; margin-bottom: 12px; background: #fdf3dc; color: #5f4000; }
    .uv-aviso a { color: #5f4000; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    f"""<div class="uv-cabecera"><h1>{html.escape(valores["nombre"])}</h1>
    <p>Admisiones, matrícula, reglamento, trámites, grados y novedades de la Universidad del Valle.</p></div>""",
    unsafe_allow_html=True,
)

aviso = C.aviso_destacado(conexion, hoy())
if aviso:
    url = aviso["url"] or ""
    enlace = f' <a href="{html.escape(url)}" target="_blank">Ver más</a>' if url.startswith("https://") else ""
    st.markdown(f'<div class="uv-aviso"><strong>Aviso:</strong> {html.escape(aviso["titulo"])}.{enlace}</div>', unsafe_allow_html=True)

if "mensajes" not in st.session_state:
    st.session_state.mensajes = []
if "perfil" not in st.session_state:
    st.session_state.perfil = "estudiante"

perfil = st.radio(
    "¿Quién pregunta?", list(PERFILES), format_func=PERFILES.get, horizontal=True, key="perfil", label_visibility="collapsed"
)

pregunta_sugerida = None
with st.sidebar:
    st.markdown("### Preguntas frecuentes")
    for sugerencia in valores[f"sugerencias_{perfil}"]:
        if st.button(sugerencia, use_container_width=True):
            pregunta_sugerida = sugerencia
    st.divider()
    st.markdown("### Cómo responde")
    st.markdown(
        "1. Busca primero en las **respuestas aprobadas** por las dependencias y en las **páginas oficiales**.\n"
        "2. Si no hay una respuesta directa, cita el **texto de la norma**.\n"
        "3. La IA solo redacta a partir de esas fuentes, y cada respuesta dice de dónde sale."
    )
    estado = asistente.ia.describir()
    nombres = ", ".join(p["nombre"].capitalize() for p in estado["proveedores"]) or "sin IA (respuestas oficiales)"
    paginas = conexion.execute("SELECT COUNT(*) FROM fuentes_web WHERE activa = 1 AND ultima_revision != '' AND error = ''").fetchone()[0]
    st.caption(f"Redacción: {nombres}. Páginas oficiales leídas: {paginas}.")
    st.caption("Orientación general: confirma siempre con la fuente oficial. No escribas datos personales.")
    if st.button("Nueva conversación", use_container_width=True):
        st.session_state.mensajes = []
        st.rerun()


def mostrar(indice: int, mensaje: dict) -> None:
    with st.chat_message("user" if mensaje["rol"] == "usuario" else "assistant"):
        st.markdown(mensaje["texto"])
        fuentes = mensaje.get("fuentes") or []
        if fuentes:
            enlaces = [f"[{f['titulo']}]({f['url']})" if (f.get("url") or "").startswith("https://") else f["titulo"] for f in fuentes]
            st.caption("Fuente: " + " · ".join(enlaces))
        if mensaje.get("tipo") == "ia":
            st.caption("Redactado con IA a partir de las fuentes. Verifícalo en el enlace.")
        if mensaje.get("tipo") in VALORABLES and "util" not in mensaje:
            columnas = st.columns([1, 1, 6])
            for columna, (etiqueta, util) in zip(columnas, (("👍 Sí", True), ("👎 No", False))):
                if columna.button(etiqueta, key=f"valorar-{indice}-{util}", help="¿Te sirvió esta respuesta?"):
                    registrar_valoracion(conexion, mensaje["pregunta"], mensaje["tipo"], [f["titulo"] for f in fuentes], util)
                    mensaje["util"] = util
                    st.rerun()
        elif "util" in mensaje:
            st.caption("¡Gracias por tu opinión!")


if not st.session_state.mensajes:
    with st.chat_message("assistant"):
        st.markdown(valores["bienvenida"])

for i, mensaje in enumerate(st.session_state.mensajes):
    mostrar(i, mensaje)

pregunta = pregunta_sugerida or st.chat_input("Escribe tu pregunta…", max_chars=500)
if pregunta:
    historial = [{"rol": m["rol"], "texto": m["texto"][:600]} for m in st.session_state.mensajes[-6:]]
    st.session_state.mensajes.append({"rol": "usuario", "texto": pregunta})
    with st.spinner("Revisando las fuentes oficiales…"):
        respuesta = asistente.responder(conexion, pregunta, historial, perfil=perfil)
    st.session_state.mensajes.append(
        {"rol": "asistente", "texto": respuesta.respuesta, "tipo": respuesta.tipo, "fuentes": respuesta.fuentes, "pregunta": pregunta}
    )
    st.rerun()

conexion.close()
