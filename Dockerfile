# Servidor completo del asistente: chat, panel de funcionarios y lectura de páginas oficiales.
#   docker build -t asistente-univalle .
#   docker run -p 8000:8000 -v asistente-datos:/srv/datos --env-file chatbot/.env asistente-univalle
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RUTA_DB=/srv/datos/asistente.db \
    PORT=8000

WORKDIR /srv
COPY chatbot/requirements.txt .
RUN pip install -r requirements.txt

COPY chatbot/app ./app
COPY chatbot/web ./web
COPY chatbot/fuentes ./fuentes

# Sin privilegios de administrador; uid 1000 es el que esperan Hugging Face Spaces y la mayoría de servidores.
RUN useradd --create-home --uid 1000 asistente && mkdir -p /srv/datos && chown -R asistente /srv/datos
USER asistente
VOLUME ["/srv/datos"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/salud', timeout=4)"

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
