# Asistente virtual de la Universidad del Valle

**Pruébalo en línea:** <https://reglamento-univalle-ia-d2u6pdect5emm4nbc9hkxe.streamlit.app/>

Un asistente con inteligencia artificial que responde a **aspirantes** y **estudiantes** de la Universidad del Valle sobre admisiones, inscripciones, matrícula, reglamento estudiantil, trámites, grados y novedades. Cada respuesta dice de qué norma o página oficial sale, y los funcionarios lo mantienen al día desde un panel, sin programar.

> Prototipo académico independiente: no es un servicio oficial de la Universidad del Valle.

## Por qué es distinto

- **Responde con fuentes, no con suposiciones.** Primero usa respuestas aprobadas por las dependencias, el texto vigente de las normas y las páginas oficiales. La IA solo redacta a partir de esos fragmentos y, si no hay fuente, lo dice y remite a la oficina correcta.
- **Se mantiene al día solo.** Lee las páginas de Registro Académico y las noticias de la Universidad cada pocas horas; si algo cambia, la respuesta cambia y queda registrado.
- **Los funcionarios tienen el control.** Un panel con editores y aprobadores por dependencia, revisión antes de publicar, historial con restauración, avisos destacados, usuarios, ajustes y estadísticas de uso.
- **Atiende a quien quiere entrar y a quien ya estudia**, con sugerencias y prioridades distintas para cada uno.
- **Costo cero.** Funciona con los planes gratuitos de Gemini, Groq o Cohere, o con un modelo propio. Si se acaba la cuota, sigue respondiendo sin IA.
- **Cuida los datos personales.** Quita correos, documentos, celulares y nombres antes de buscar o consultar la IA, y no guarda conversaciones.
- **Se instala con una línea** en cualquier página de la Universidad (Joomla o WordPress).

## Cómo está hecho

```text
chatbot/                  Servidor completo: chat flotante, API y panel de funcionarios
  app/                    Motor (FastAPI, SQLite, búsqueda BM25 + vectores, cadena de IA gratuita)
  web/widget.js           El chat que se pega en las páginas
  web/panel/              Panel de funcionarios
  fuentes/                Normas oficiales: Acuerdos 009/1997, 006/2023, 004/2024 y Resoluciones 080 y 066 de 2024
  tests/                  Casi 200 pruebas automáticas, sin internet ni gasto de IA
streamlit_app.py          Versión de solo chat para Streamlit Community Cloud, con el mismo motor
Dockerfile                Imagen del servidor completo
```

La búsqueda combina palabras clave (BM25 con raíces del español y sinónimos estudiantiles: «materia» es «asignatura», «retirar» es «cancelar», «cambiarme de carrera» es «traslado») y búsqueda por significado. La respuesta se elige en este orden: novedades vigentes, respuesta aprobada, fecha publicada, redacción con IA a partir de normas y páginas oficiales, texto literal si no hay IA, y, si nada aplica, una remisión honesta a la oficina correspondiente. La pregunta queda anotada, sin datos personales, para que alguien la responda.

## Cómo ejecutarlo

### Servidor completo (chat + panel)

Ver [`chatbot/README.md`](chatbot/README.md): arranque local, cuentas de prueba, guion de demostración de 5 minutos y cómo publicarlo con Docker o gratis en Hugging Face Spaces.

### Versión Streamlit

```bash
pip install -r requirements.txt
```

```bash
streamlit run streamlit_app.py
```

En Streamlit Community Cloud, apunta la app a `streamlit_app.py` y agrega en **Settings → Secrets** al menos una clave gratuita, por ejemplo:

```toml
GEMINI_API_KEY = "tu_clave"
```

Sin claves también funciona: responde con las respuestas aprobadas, las páginas oficiales y el texto de las normas.

## Ejemplos

| Pregunta | Qué hace el asistente |
|---|---|
| ¿Qué pasa si incurro en bajo rendimiento académico por segunda vez? | Responde con el **Artículo 62 del Acuerdo 006 de 2023**, la versión vigente, y no con la de 1997. |
| ¿Cómo saco el carné estudiantil? | Responde con la página oficial de Registro Académico y la enlaza. |
| ¿Cuánto cuesta la inscripción? (aspirante) | Explica dónde se publica el valor, según la Resolución 080 de 2024. |
| ¿Qué novedades hay? | Lista los avisos vigentes y las noticias recientes de la Universidad. |
| ¿Cómo cancelo una materia? | Cita el Artículo 55 y, si Registro publicó una ampliación del plazo, la agrega. |
| ¿Cuánto debo de matrícula? | Aclara que no tiene acceso a datos personales y remite a la oficina. |
| ¿Cuál es la capital de Francia? | Dice que está fuera de su tema. |

## Autor

Desarrollado por [Cristianriosrivas](https://github.com/Cristianriosrivas).
