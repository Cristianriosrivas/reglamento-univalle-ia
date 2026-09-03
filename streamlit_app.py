"""
Agente Reglamento Univalle - Asistente basado en RAG (Retrieval-Augmented Generation)
que responde preguntas sobre el Reglamento Estudiantil de Pregrado de la
Universidad del Valle. Versión con Streamlit, pensada para desplegarse en
Streamlit Community Cloud.
"""

import os
from dotenv import load_dotenv
import streamlit as st

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_cohere import CohereEmbeddings, ChatCohere
from langchain_community.vectorstores import FAISS
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

# ---------------------------------------------------------------------------
# 1. Configuración de la página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Reglamento Univalle | Asistente Virtual",
    page_icon="📘",
    layout="wide",
)

PDF_PATH = os.environ.get("PDF_PATH", "reglamento_universitario.pdf")


def obtener_api_key():
    """
    Busca la API key de Cohere en este orden:
    1. Variables de entorno (útil en local, vía .env)
    2. st.secrets (así es como Streamlit Community Cloud guarda los secretos:
       se configura UNA sola vez en el panel del sitio, y desde ahí el agente
       la lee automáticamente en cada inicio, sin volver a escribirla nunca).
    """
    load_dotenv()
    key = os.environ.get("COHERE_API_KEY")
    if key:
        return key
    try:
        return st.secrets["COHERE_API_KEY"]
    except Exception:
        return None


COHERE_API_KEY = obtener_api_key()

if not COHERE_API_KEY:
    st.error(
        "⚠️ Falta configurar la API key de Cohere.\n\n"
        "- En local: crea un archivo `.env` (basado en `.env.example`) con tu key.\n"
        "- En Streamlit Community Cloud: ve a la configuración de tu app → "
        "**Settings → Secrets**, y agrega:\n\n"
        "```\nCOHERE_API_KEY = \"tu_key_aqui\"\n```"
    )
    st.stop()

os.environ["COHERE_API_KEY"] = COHERE_API_KEY


# ---------------------------------------------------------------------------
# 2. Cargamos el agente (con cache para no rehacer todo en cada interacción)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="Preparando el agente del Reglamento Univalle...")
def cargar_agente():
    if not os.path.exists(PDF_PATH):
        st.error(f"No se encontró el archivo '{PDF_PATH}'.")
        st.stop()

    loader = PyPDFLoader(PDF_PATH)
    paginas = loader.load()

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    fragmentos = text_splitter.split_documents(paginas)

    embeddings = CohereEmbeddings(model="embed-multilingual-v3.0")
    vectorstore = FAISS.from_documents(fragmentos, embeddings)
    retriever = vectorstore.as_retriever()

    llm = ChatCohere(model="command-a-03-2025")

    instrucciones = (
        "Eres un asistente virtual experto en el Reglamento Estudiantil de Pregrado "
        "de la Universidad del Valle (Univalle). Usa EXCLUSIVAMENTE los siguientes "
        "fragmentos del reglamento para responder. Cuando cites un artículo, "
        "menciona su número (por ejemplo 'Artículo 61'). Si una norma fue "
        "modificada por un acuerdo posterior (como el Acuerdo 006 de 2023 sobre "
        "bajos rendimientos académicos), prioriza siempre la versión más reciente. "
        "Si la respuesta no está en el texto, di amablemente que no tienes esa "
        "información y sugiere consultar directamente con la Dirección de Programa "
        "Académico o la División de Admisiones y Registro Académico. "
        "Responde de forma clara, profesional y en español.\n\n"
        "{context}"
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", instrucciones),
        ("human", "{input}"),
    ])

    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    return create_retrieval_chain(retriever, question_answer_chain)


agente_reglamento = cargar_agente()


# ---------------------------------------------------------------------------
# 3. Estilos - apariencia institucional Univalle (rojo vino + dorado)
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    :root {
        --uv-primary: #7a0c2e;
        --uv-primary-dark: #4a0719;
        --uv-gold: #d4a017;
    }
    #uv-header {
        background: linear-gradient(120deg, var(--uv-primary-dark), var(--uv-primary));
        border-radius: 14px;
        padding: 28px 32px;
        margin-bottom: 18px;
        color: white;
        text-align: center;
    }
    #uv-header h1 {
        margin: 0 0 6px 0;
        color: white;
    }
    #uv-header h1 span {
        color: var(--uv-gold);
    }
    #uv-header p {
        margin: 0;
        opacity: 0.9;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div id="uv-header">
        <h1>📘 Reglamento <span>Univalle</span></h1>
        <p>Asistente virtual sobre el Reglamento Estudiantil de Pregrado, disponible 24/7</p>
    </div>
    """,
    unsafe_allow_html=True,
)

EJEMPLOS = [
    "¿Cuáles son los deberes del estudiante?",
    "¿Qué pasa si incurro en bajo rendimiento académico por segunda vez?",
    "¿Cuál es el plazo para cancelar una asignatura?",
    "¿Cómo funciona la evaluación de habilitación?",
]

# ---------------------------------------------------------------------------
# 4. Panel lateral: categorías de ayuda y preguntas rápidas
# ---------------------------------------------------------------------------
pregunta_desde_boton = None
with st.sidebar:
    st.markdown("### 📖 Puedo ayudarte con")
    st.markdown(
        "- 🎓 Derechos y deberes del estudiante\n"
        "- 📝 Evaluaciones y calificaciones\n"
        "- 📉 Bajos rendimientos académicos\n"
        "- 🔁 Matrícula, adiciones y cancelaciones\n"
        "- 🔄 Reingresos, traslados y transferencias\n"
        "- ⚖️ Régimen disciplinario"
    )
    st.markdown("### 💬 Preguntas rápidas")
    for ejemplo in EJEMPLOS:
        if st.button(ejemplo, use_container_width=True):
            pregunta_desde_boton = ejemplo

# ---------------------------------------------------------------------------
# 5. Chat
# ---------------------------------------------------------------------------
if "mensajes" not in st.session_state:
    st.session_state.mensajes = []

for mensaje in st.session_state.mensajes:
    with st.chat_message(mensaje["role"]):
        st.markdown(mensaje["content"])

pregunta_escrita = st.chat_input("Escribe tu pregunta aquí...")
pregunta_final = pregunta_desde_boton or pregunta_escrita

if pregunta_final:
    st.session_state.mensajes.append({"role": "user", "content": pregunta_final})
    with st.chat_message("user"):
        st.markdown(pregunta_final)

    with st.chat_message("assistant"):
        with st.spinner("Consultando el Reglamento Estudiantil de Univalle..."):
            try:
                resultado = agente_reglamento.invoke({"input": pregunta_final})
                respuesta = resultado["answer"]
            except Exception as e:
                respuesta = f"Ocurrió un error al procesar tu pregunta: {e}"
        st.markdown(respuesta)

    st.session_state.mensajes.append({"role": "assistant", "content": respuesta})
