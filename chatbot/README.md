# Asistente virtual de la Universidad del Valle

Un chat flotante para las páginas de la Universidad que responde a **aspirantes** y **estudiantes** sobre admisiones, matrícula, reglamento, trámites, grados y novedades. Cada respuesta cita su fuente oficial. Los funcionarios la mantienen al día desde un panel, sin programar, y el asistente además lee solo las páginas oficiales y las noticias de la Universidad.

> Es un prototipo independiente: no es un servicio oficial de la Universidad y requiere su autorización para instalarse en sus páginas.

## Lo que hace

| | |
|---|---|
| **Dos públicos** | Al abrir el chat pregunta si la persona quiere estudiar en Univalle o ya es estudiante, y ajusta sugerencias y respuestas. |
| **Se actualiza solo** | Lee 14 páginas de Registro Académico y el canal de noticias de la Universidad al arrancar y cada 12 horas. Si una página cambia, la respuesta cambia y queda en el historial. |
| **Modo de administración** | Editores y aprobadores por dependencia, revisión antes de publicar, historial con restauración, usuarios, ajustes del chat, estadísticas y preguntas por mejorar. |
| **Avisos y novedades** | Una dependencia publica una novedad con fecha de vencimiento; si la marca como destacada aparece arriba en el chat, y se suma a las respuestas del mismo tema. |
| **IA gratuita y opcional** | Gemini, Groq, Cohere o un modelo propio, en cadena: si uno falla o se queda sin cuota, responde el siguiente. Sin ninguno, igual responde. |
| **No inventa** | Primero usa respuestas aprobadas, fechas y páginas oficiales; la IA solo redacta a partir de esos fragmentos y, si no hay fuente, lo dice. |
| **Cuida los datos** | Quita correos, documentos, celulares y nombres antes de buscar, de llamar a la IA y de guardar estadísticas. No guarda conversaciones. |

## Cómo arrancarlo

Desde la raíz del repositorio, en Windows:

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r chatbot\requirements.txt
```

```bash
copy chatbot\.env.example chatbot\.env
```

```bash
.venv\Scripts\python -m uvicorn app.main:app --app-dir chatbot --port 8000
```

La primera vez tarda unos 30 segundos porque carga las normas. Después abre:

- <http://localhost:8000/demo>: página de prueba con el chat y el guion de la demostración.
- <http://localhost:8000/panel>: panel de funcionarios.

En macOS o Linux cambia `.venv\Scripts\python` por `.venv/bin/python` y `copy` por `cp`.

### Cuentas de prueba

Solo existen con `ENTORNO=desarrollo`. La contraseña es `DEMO_CLAVE`, en `chatbot/.env`.

| Correo | Rol | Puede |
|---|---|---|
| `editor.registro@demo.local` | Editor de Registro | Cambiar contenido de Registro y enviarlo a revisión |
| `aprobador.registro@demo.local` | Aprobador de Registro | Además, publicar, devolver cambios y agregar páginas oficiales de Registro |
| `editor.admisiones@demo.local` | Editor de Admisiones | Lo mismo que el editor, para aspirantes |
| `aprobador.secretaria@demo.local` | Aprobador de Secretaría General | Publicar normas, como el Acuerdo 004 de 2024 |
| `admin@demo.local` | Administrador | Todo: usuarios, ajustes y todas las dependencias |

Para volver al contenido inicial, detén el servidor y borra la carpeta `chatbot/datos`.

## Guion para mostrar la demo (5 minutos)

1. **El chat responde y cita.** En `/demo` elige «Ya soy estudiante» y pregunta «¿Qué pasa si incurro en bajo rendimiento académico por segunda vez?» y «¿Cómo saco el carné estudiantil?» (esta sale de la página oficial). Abre el enlace de la fuente.
2. **Atiende a quien quiere entrar.** Reinicia el chat, elige «Quiero estudiar en Univalle» y usa las sugerencias.
3. **Sabe qué no debe responder.** Pregunta «cuánto debo de matrícula» y «cuál es la capital de Francia».
4. **Un funcionario actualiza un dato.** Pregunta «¿Cuándo es la ceremonia de grado?». En el panel, como editor de Registro, busca «Ceremonia», cambia la fecha y guarda. Compruébalo en «Probar el asistente» y envíalo a revisión. Como aprobador, publícalo en «Revisión»: el chat responde la fecha nueva.
5. **Un aviso para todos.** Como administrador crea una novedad («Plazo extendido para cancelar asignaturas»), márcala como aviso destacado y publícala. Abre el chat: aparece arriba, y «¿Cómo cancelo una materia?» ahora responde la norma **y** el aviso.
6. **Las páginas oficiales y los números.** En «Páginas oficiales» pulsa «Leer ahora»; en «Inicio» están las preguntas por día, cuántas se resolvieron sin IA y cuántas sirvieron; en «Por mejorar», lo que no encontró respuesta, con un botón para crearla.

## Cómo funciona

```text
Página de Univalle (una línea <script>)            Páginas de Registro y noticias
        │  pregunta + perfil                                  │ cada 12 horas
        ▼                                                     ▼
API (FastAPI) ── quita datos personales ── busca en todo lo publicado (palabras + significado)
        │
        ├─ Novedades → las vigentes, de la más reciente a la más antigua
        ├─ Pregunta frecuente o fecha aprobada → se responde tal cual, sin gastar IA
        ├─ Norma o página oficial → la IA gratuita redacta con esos fragmentos y los cita
        ├─ Sin IA (o se cayó, o llegó al tope) → cita el texto literal
        ├─ Hay un aviso vigente del mismo tema → se agrega a la respuesta
        └─ Nada aplica → lo dice, remite a una oficina y anota la pregunta para mejorar
        ▲
        │  publica
Panel de funcionarios (borrador → revisión → publicado, con historial, usuarios, ajustes y estadísticas)
```

Decisiones importantes:

- **La versión vigente manda.** Los artículos 59 a 64 del Acuerdo 009 quedan reemplazados por los del Acuerdo 006 de 2023: el asistente ya no los usa, pero se conservan como antecedente.
- **Las fechas y novedades vencen solas**, con la hora de Colombia.
- **Lo que viene de una página oficial no se edita en el panel**: se corrige en la página, y en la siguiente lectura el asistente lo toma. Si no debe usarse, se pausa la fuente.
- **Solo lee `https://` de `univalle.edu.co`**, con límite de tamaño y sin seguir redirecciones a otros sitios.
- **Los PDF se revisan al subirlos.** El panel corrige acentos dañados, quita encabezados, separa por artículos y avisa si el archivo es un escaneo.

## IA gratuita

Todas son opcionales y se configuran en `chatbot/.env` (ver `chatbot/.env.example`):

| Servicio | Variable | Para qué |
|---|---|---|
| Google Gemini (plan gratuito) | `GEMINI_API_KEY` | Redactar (`gemini-3.8-flash`) |
| Groq (plan gratuito) | `GROQ_API_KEY` | Redactar (`llama-3.3-70b-versatile`) |
| Cohere (clave de prueba) | `COHERE_API_KEY` | Redactar y buscar por significado |
| Modelo propio, p. ej. Ollama | `IA_LOCAL_URL`, `IA_LOCAL_MODELO` | Redactar sin enviar datos fuera de la Universidad |
| `fastembed` (opcional) | `pip install fastembed` | Buscar por significado en el propio servidor, gratis y sin límites |

- **Cuota.** El tope diario (`MAX_LLAMADAS_IA_DIA`, ajustable desde el panel) cuenta las redacciones y las búsquedas por significado en servicios externos. Al llegar al tope, el chat sigue respondiendo sin IA.
- **Velocidad.** Las respuestas aprobadas y las novedades son instantáneas. Las redactadas tardaron de 3 a 7 segundos en las pruebas con Cohere; con una clave de prueba, a veces bastante más.
- **Precisión.** La IA puede equivocarse al parafrasear. Por eso cada respuesta redactada avisa que debe verificarse en la fuente.

## Instalarlo en una página

```html
<script src="https://SERVIDOR/widget.js" defer></script>
```

Atributos opcionales: `data-color`, `data-perfil` (`aspirante` o `estudiante`, para saltar la pregunta inicial; útil en el sitio de Admisiones) y `data-etiqueta` (déjalo vacío para quitar «Prototipo de demostración»). El nombre, la bienvenida y las sugerencias se cambian en **Ajustes** del panel.

| Sitio | Plataforma | Qué se necesita |
|---|---|---|
| `www.univalle.edu.co` | Joomla | Agregar la línea a la plantilla |
| `registro.univalle.edu.co` | WordPress | Agregar la línea a la plantilla |
| `admisiones.univalle.edu.co` | Política de seguridad (CSP) estricta | Además, autorizar el dominio del chat en esa política |

Los sitios `https://*.univalle.edu.co` ya tienen permiso para usar la API. Otros se agregan en `ORIGENES_PERMITIDOS`.

## Publicarlo

**En un servidor de la Universidad (recomendado).** Con Docker, desde la raíz del repositorio:

```bash
docker build -t asistente-univalle .
```

```bash
docker run -d -p 8000:8000 -v asistente-datos:/srv/datos --env-file chatbot/.env -e ENTORNO=produccion asistente-univalle
```

El volumen `asistente-datos` conserva la base de datos entre reinicios. Detrás del proxy HTTPS de la Universidad, agrega `CONFIAR_PROXY=1`. Crea la primera cuenta con:

```bash
docker exec -it CONTENEDOR python -m app.admin crear --correo persona@correounivalle.edu.co --nombre "Nombre"
```

**Gratis, para una demostración pública.** En [Hugging Face Spaces](https://huggingface.co/new-space) crea un Space de tipo *Docker*, sube a él este repositorio y pon al inicio de su `README.md` el encabezado `sdk: docker` con `app_port: 8000`. En *Settings → Variables and secrets* agrega `ENTORNO=produccion`, `ADMIN_CORREO`, `ADMIN_CLAVE` y la clave de IA que quieras. Ojo: en el plan gratuito el disco no es permanente; al reiniciarse, el asistente vuelve al contenido inicial y relee las páginas oficiales, pero se pierden los cambios hechos en el panel.

**Solo el chat, sin panel.** La versión de Streamlit de la raíz (`streamlit_app.py`) usa el mismo motor; ver el [README principal](../README.md).

## Contenido incluido

| Fuente | Estado | Nota |
|---|---|---|
| Acuerdo 009 de 1997 | Publicado | 122 artículos, del PDF oficial, con el parágrafo 2 del artículo 83 actualizado por el Acuerdo 006 de 2005 |
| Acuerdo 006 de 2023 | Publicado | Artículos 59 a 64. El original es un escaneo: se cotejó el texto con él |
| Resolución 080 de 2024 | Publicado | Reglamento de inscripción y admisión |
| Resolución 066 de 2024 | Publicado | Lineamientos de acompañamiento |
| Acuerdo 004 de 2024 | En revisión | Medida transitoria ya vencida. Se dejó así para mostrar la aprobación |
| 14 páginas de Registro Académico | Se leen solas | Preguntas frecuentes, matrícula, cancelaciones, reingresos, grados, certificados, carné, calendarios y más |
| Noticias de la Universidad | Se leen solas | Canal RSS de univalle.edu.co; cada noticia vence a los 45 días |
| Preguntas, contactos y fechas de ejemplo | Publicado | **Son contenido de ejemplo:** falta que cada dependencia los valide |

## Pruebas

```bash
.venv\Scripts\python -m pip install -r chatbot\requirements-dev.txt
```

```bash
cd chatbot && ..\.venv\Scripts\python -m pytest
```

Son casi 200 pruebas, que no salen a internet ni gastan llamadas de IA: un banco de preguntas reales (`tests/test_asistente.py`), el flujo de publicación, el modo de administración, la lectura de páginas oficiales con respuestas simuladas, la cadena de servicios de IA y la protección de datos personales. Si cambias la búsqueda, el banco de preguntas muestra si alguna respuesta empeora.

## Antes de pasar a producción

- Cambiar el inicio de sesión por **Google con el correo institucional**.
- Si hay varios servidores, migrar de **SQLite a PostgreSQL** y los límites de uso a un almacén compartido.
- Hacer que **cada dependencia valide** el contenido de ejemplo y probar con preguntas reales de estudiantes y aspirantes.
- Revisión de **Jurídica** por datos personales: la [Resolución 3395 de 2022](https://registro.univalle.edu.co/wp-content/uploads/2024/05/R_3395_Actualizacion_Politica_Tratamiento_Datos.pdf) es la política de la Universidad, y las preguntas (ya sin datos personales) viajarían a un proveedor de IA. Con un modelo propio (`IA_LOCAL_URL`) no salen de la Universidad.
- Sumar **OCR**: varios acuerdos oficiales son escaneos y hoy hay que pegar su texto a mano.
