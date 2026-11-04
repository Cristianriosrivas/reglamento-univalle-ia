https://reglamento-univalle-ia-d2u6pdect5emm4nbc9hkxe.streamlit.app/
# reglamento-univalle-ia

> **Nuevo:** en [`chatbot/`](chatbot/README.md) está la demo del chat flotante para las páginas de la Universidad, con panel para que los funcionarios actualicen el contenido.

Agente de inteligencia artificial basado en RAG (Retrieval-Augmented Generation) que responde preguntas sobre el **Reglamento Estudiantil de Pregrado de la Universidad del Valle** (Acuerdo 009 de 1997), incluyendo sus modificaciones vigentes como el **Acuerdo 006 de 2023**, que actualizó el Capítulo VIII sobre bajos rendimientos académicos.

Proyecto adaptado a partir de un agente RAG previo (LuminaStore), reutilizando la misma arquitectura para un caso de uso académico: consultar de forma conversacional un documento normativo extenso.

## Arquitectura de la solución

El agente sigue un flujo clásico de RAG (Retrieval-Augmented Generation):

1. **`reglamento_universitario.pdf`** — documento fuente con el Reglamento Estudiantil de Pregrado de Univalle (Acuerdo 009/1997 + Acuerdo 006/2023).
2. **PyPDFLoader** → carga el PDF y extrae su texto.
3. **RecursiveCharacterTextSplitter** → divide el texto en fragmentos de 1000 caracteres (200 de solapamiento).
4. **CohereEmbeddings** → convierte cada fragmento en un vector numérico.
5. **FAISS Vectorstore** → índice vectorial en memoria para búsqueda semántica.
6. **Retriever** → dada una pregunta, busca los artículos/fragmentos más relevantes.
7. **ChatCohere + Prompt** → el LLM redacta la respuesta usando SOLO esos fragmentos como contexto, citando el número de artículo cuando es posible y priorizando las versiones más recientes de las normas modificadas.
8. **Interfaz de chat** (Gradio o Streamlit) → el usuario pregunta y recibe la respuesta.

En resumen: cuando alguien hace una pregunta sobre el reglamento, el sistema busca los artículos del PDF más relacionados semánticamente con esa pregunta (no es una búsqueda de palabras exactas, sino de significado), y se los pasa al modelo de lenguaje para que redacte una respuesta basada únicamente en esa información — evitando que el modelo invente normas que no están en el documento.

## Tecnologías utilizadas

- **Python** — lenguaje principal del proyecto
- **LangChain / LangChain Classic** — orquestación del pipeline RAG
- **PyPDF** — lectura del documento PDF
- **Cohere (`embed-multilingual-v3.0`)** — generación de embeddings
- **Cohere (`command-a-03-2025`)** — modelo de lenguaje (LLM)
- **FAISS** — base de datos vectorial (búsqueda semántica)
- **Gradio** — interfaz de chat (`app.py`)
- **Streamlit** — interfaz de chat alternativa (`streamlit_app.py`), pensada para Streamlit Community Cloud

## Cómo ejecutar el proyecto

### Requisitos previos

1. Coloca el PDF del reglamento en la raíz del proyecto con el nombre `reglamento_universitario.pdf` (o ajusta la variable `PDF_PATH`).
2. Consigue una API key gratuita de Cohere en [dashboard.cohere.com](https://dashboard.cohere.com).

### Opción A: localmente con `app.py` (Gradio)

```bash
git clone https://github.com/Cristianriosrivas/reglamento-univalle-ia.git
cd reglamento-univalle-ia
pip install -r requirements.txt
cp .env.example .env
# Edita .env y pega tu COHERE_API_KEY
python app.py
```

Luego abre en tu navegador la URL que aparece en la terminal (por defecto `http://localhost:7860`).

### Opción B: localmente con `streamlit_app.py`

```bash
pip install -r requirements.txt
cp .env.example .env
# Edita .env y pega tu COHERE_API_KEY
streamlit run streamlit_app.py
```

### Opción C: Streamlit Community Cloud (despliegue)

1. Sube el repositorio (incluyendo `reglamento_universitario.pdf`) a GitHub.
2. Crea una nueva app en [share.streamlit.io](https://share.streamlit.io) apuntando a `streamlit_app.py`.
3. En **Settings → Secrets**, agrega:

   ```
   COHERE_API_KEY = "tu_key_aqui"
   ```

## Ejemplos de preguntas y respuestas

**Pregunta:** ¿Cuáles son los deberes del estudiante?

**Respuesta del agente:** Según el Artículo 8 del Reglamento, entre los deberes del estudiante están cumplir el Estatuto General y el Reglamento, tener un comportamiento respetuoso con la comunidad universitaria, abstenerse de actos de discriminación, dar buen uso a los bienes que le sean confiados, contribuir al mejoramiento del desempeño académico y abstenerse de asistir a la Universidad en estado de embriaguez o bajo el influjo de sustancias.

**Pregunta:** ¿Qué pasa si incurro en bajo rendimiento académico por segunda vez?

**Respuesta del agente:** De acuerdo con el Artículo 62 (modificado por el Acuerdo 006 de 2023), al estudiante que incurra en bajo rendimiento académico por segunda vez se le podrá autorizar la matrícula si cumple alguna de estas condiciones: haber asistido al acompañamiento ofrecido tras el primer bajo rendimiento, tener un promedio acumulado mínimo de 3.30, o tener un avance de al menos el 60% en las asignaturas del programa. Si se autoriza la matrícula y el estudiante no se matricula o cancela el periodo siguiente, solo podrá solicitar reingreso una vez dentro de los siguientes cuatro periodos académicos.

**Pregunta:** ¿Cuál es el plazo para cancelar una asignatura?

**Respuesta del agente:** El plazo máximo para la cancelación de asignaturas es la séptima semana del período académico vigente (Artículo 55), y el plazo máximo para la cancelación de la matrícula completa es la décima semana del mismo período.

**Pregunta:** ¿Cómo funciona la evaluación de habilitación?

**Respuesta del agente:** La habilitación es la evaluación que se hace al final de una asignatura a los estudiantes que no la aprobaron (Artículo 23). El estudiante puede presentar la evaluación de habilitación en la fecha fijada o, si la Universidad lo ofrece, tomar un curso de vacaciones en su lugar. Para habilitar se requiere que la asignatura sea habilitable, que se haya matriculado en el período académico inmediatamente anterior, y que la calificación obtenida no sea inferior a 2.0 (Artículo 30).

## ☁️ Notas sobre las fuentes normativas

El documento fuente incluye:
- El **Acuerdo 009 de 1997** (Reglamento Estudiantil de Pregrado original, 122 artículos).
- El **Acuerdo 006 de 2023**, que modificó el Capítulo VIII (Artículos 59 a 64) sobre bajos rendimientos académicos, vigente a partir del primer semestre de 2024.

El agente está instruido para priorizar siempre la versión más reciente de un artículo cuando existan modificaciones posteriores dentro del mismo documento.

## Estructura del repositorio

- `app.py` — script principal (agente + interfaz Gradio)
- `streamlit_app.py` — versión alternativa con interfaz Streamlit
- `requirements.txt` — dependencias del proyecto
- `.env.example` — plantilla de variables de entorno
- `.gitignore` — archivos excluidos de Git (incluye `.env`)
- `reglamento_universitario.pdf` — documento fuente del agente (Acuerdo 009/1997 + Acuerdo 006/2023)
- `README.md` — este archivo
