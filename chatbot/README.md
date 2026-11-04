# Asistente estudiantil (demo)

Prototipo de un chat flotante para las páginas de la Universidad del Valle. Responde dudas sobre el reglamento, matrículas e inscripciones citando la norma de cada respuesta, y los funcionarios lo actualizan desde un panel, sin programar.

> Es un prototipo independiente: no es un servicio oficial de la Universidad y requiere su autorización para instalarse en sus páginas.

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

- <http://localhost:8000/demo>: página de prueba con el chat.
- <http://localhost:8000/panel>: panel de funcionarios.

Usuarios de prueba (la contraseña es `DEMO_CLAVE`, en `chatbot/.env`):

| Correo | Rol | Puede |
|---|---|---|
| `editor.registro@demo.local` | Editor de Registro | Cambiar contenido de Registro y enviarlo a revisión |
| `aprobador.registro@demo.local` | Aprobador de Registro | Además, publicar y devolver cambios de Registro |
| `editor.admisiones@demo.local` | Editor de Admisiones | Lo mismo que el editor, pero en Admisiones |
| `aprobador.secretaria@demo.local` | Aprobador de Secretaría General | Publicar normas, como el Acuerdo 004 de 2024 |
| `admin@demo.local` | Administrador | Todo, en todas las dependencias |

Para volver al contenido inicial, detén el servidor y borra la carpeta `chatbot/datos`.

## Guion para mostrar la demo (5 minutos)

1. **El chat responde y cita.** En `/demo` pregunta «quiero cambiarme de carrera» y «¿Qué pasa si incurro en bajo rendimiento académico por segunda vez?». Abre el enlace de la fuente.
2. **Sabe qué no debe responder.** Pregunta «cuánto debo de matrícula» y «cuál es la capital de Francia».
3. **Un funcionario actualiza un dato.** Pregunta «¿Cuándo es la ceremonia de grado?». En el panel, como editor de Registro, busca «Ceremonia solemne», cambia la fecha y guarda. El chat público sigue igual.
4. **Se comprueba antes de publicar.** En «Probar el asistente», haz la misma pregunta: ya sale la fecha nueva. Envía el cambio a revisión.
5. **Alguien aprueba.** Entra como aprobador de Registro, abre «Revisión», compara y publica. El chat responde la fecha nueva, sin tocar código.
6. **Queda el rastro.** Muestra «Actividad» y el historial del contenido, desde donde se puede restaurar una versión anterior.

## Cómo funciona

```text
Página de Univalle (una línea <script>)
        │  pregunta
        ▼
API (FastAPI) ── quita datos personales ── busca en lo publicado
        │
        ├─ Pregunta frecuente aprobada → se responde tal cual, sin gastar IA
        ├─ Fecha o contacto publicado → se responde con el dato
        ├─ Norma, con clave de Cohere → la IA redacta y cita los artículos
        ├─ Norma, sin clave → cita el texto literal del artículo
        └─ Nada aplica → lo dice, remite a una oficina y anota la pregunta
        ▲
        │  publica
Panel de funcionarios (borrador → revisión → publicado, con historial)
```

Decisiones importantes:

- **Sin clave de Cohere también funciona.** Así la demo no depende de un servicio de pago, y si la IA se cae o llega al tope diario, el chat sigue respondiendo.
- **La versión vigente manda.** Los artículos 59 a 64 del Acuerdo 009 quedan reemplazados por los del Acuerdo 006 de 2023: el asistente ya no los usa, pero se conservan como antecedente.
- **Las fechas vencen solas.** Por eso la cancelación del 30 de octubre ya no se muestra.
- **Los datos personales no salen.** Correos, números de documento y nombres se quitan antes de buscar, de enviar la pregunta a la IA y de guardarla.
- **Los PDF se revisan al subirlos.** El panel corrige acentos dañados, quita encabezados, separa por artículos y avisa si el archivo es un escaneo.

## Instalarlo en una página

```html
<script src="https://SERVIDOR/widget.js" defer></script>
```

Atributos opcionales: `data-color`, `data-titulo` y `data-etiqueta` (déjalo vacío para quitar «Prototipo de demostración»).

| Sitio | Plataforma | Qué se necesita |
|---|---|---|
| `www.univalle.edu.co` | Joomla | Agregar la línea a la plantilla |
| `registro.univalle.edu.co` | WordPress | Agregar la línea a la plantilla |
| `admisiones.univalle.edu.co` | Política de seguridad (CSP) estricta | Además, autorizar el dominio del chat en esa política |

Los sitios `*.univalle.edu.co` ya tienen permiso para usar la API. Otros se agregan en `ORIGENES_PERMITIDOS`.

## Contenido incluido

| Fuente | Estado | Nota |
|---|---|---|
| Acuerdo 009 de 1997 | Publicado | 122 artículos, del PDF oficial, con el parágrafo 2 del artículo 83 actualizado por el Acuerdo 006 de 2005 |
| Acuerdo 006 de 2023 | Publicado | Artículos 59 a 64. El original es un escaneo: se cotejó el texto con él |
| Resolución 080 de 2024 | Publicado | Reglamento de inscripción y admisión |
| Resolución 066 de 2024 | Publicado | Lineamientos de acompañamiento |
| Acuerdo 004 de 2024 | En revisión | Medida transitoria ya vencida. Se dejó así para mostrar la aprobación |
| Preguntas, contactos y fechas | Publicado | **Son contenido de ejemplo:** falta que cada dependencia los valide |

El mapa completo de normas está en la página de [Normatividad de Registro Académico](https://registro.univalle.edu.co/normatividad/). No todo está cargado: faltan, por ejemplo, posgrados, matrícula financiera y derechos pecuniarios.

## Pruebas

```bash
.venv\Scripts\python -m pip install -r chatbot\requirements-dev.txt
```

```bash
cd chatbot && ..\.venv\Scripts\python -m pytest
```

Incluyen un banco de preguntas (`tests/test_asistente.py`). Si cambias la búsqueda, ahí se ve si alguna respuesta empeora. Estas pruebas simulan a Cohere para no gastar llamadas.

## Modo con IA

Con `COHERE_API_KEY` en `chatbot/.env`, el asistente redacta en lenguaje sencillo y entiende preguntas dichas de otra forma. Se probó contra Cohere real con preguntas difíciles y trampas:

- **Modelo:** se mantiene `command-a-03-2025`. Los modelos más rápidos (`command-r-08-2024` y `command-r7b-12-2024`) inventaron conclusiones sobre casos personales.
- **Velocidad:** las preguntas frecuentes aprobadas son instantáneas y no usan la IA. Las redactadas tardaron de 3 a 28 segundos con una clave de prueba, y algunas agotaron la espera. En ese caso el chat cita el artículo o pide reintentar. Para una presentación, ensaya con las preguntas frecuentes.
- **Límite:** una clave de prueba da 1.000 llamadas al mes por servicio y no se permite en producción.
- **Precisión:** la IA puede equivocarse al parafrasear. Por eso cada respuesta redactada avisa que debe verificarse en la fuente, y conviene revisar con la dependencia un banco de preguntas reales antes de abrirlo al público.

## Antes de pasar a producción

- Usar una **clave de producción** de Cohere y medir de nuevo la velocidad. Recalibrar `UMBRAL_VECTOR` con preguntas reales: el valor actual sale de unas 20 preguntas de prueba.
- Cambiar el login por **Google con el correo institucional** y quitar los usuarios de prueba.
- Migrar de **SQLite a PostgreSQL con pgvector**, y los límites de uso a un almacén compartido, si hay varios servidores.
- Servir por **HTTPS** en un subdominio de la Universidad, con `COOKIE_SEGURA=1` y `CONFIAR_PROXY=1` detrás del proxy.
- Hacer que **cada dependencia valide** el contenido y probar con preguntas reales de estudiantes.
- Revisión de **Jurídica** por datos personales: la [Resolución 3395 de 2022](https://registro.univalle.edu.co/wp-content/uploads/2024/05/R_3395_Actualizacion_Politica_Tratamiento_Datos.pdf) es la política de la Universidad, y las preguntas viajarían a un proveedor externo.
- Sumar **OCR**: varios acuerdos oficiales son escaneos y hoy hay que pegar su texto a mano.
