"""
Servicios de IA, todos con opción gratuita:

- Redacción: una cadena de proveedores (Gemini, Groq, Cohere o un modelo local como Ollama). Si uno falla, tarda o
  se queda sin cuota, se intenta el siguiente; si ninguno responde, el asistente sigue funcionando sin IA.
- Búsqueda por significado: un modelo local (gratis, sin límites y sin enviar datos a nadie) o, si no está
  instalado, los vectores de Cohere o Gemini.

Ningún error de un servicio externo se propaga: siempre se devuelve None y quien llama decide qué hacer.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from array import array
from math import sqrt

import httpx

from .config import RAIZ, Config, Proveedor

logger = logging.getLogger("asistente.ia")

URL_COHERE_CHAT = "https://api.cohere.com/v2/chat"
URL_COHERE_EMBED = "https://api.cohere.com/v2/embed"
TAMANO_LOTE = 96
LIMITE_CADENA_SEGUNDOS = 26  # el chat espera 35 s: después de esto no se prueba otro proveedor


def _unitario(valores) -> array:
    """Normaliza el vector: así el producto punto ya es la similitud del coseno."""
    valores = [float(v) for v in valores]
    norma = sqrt(sum(v * v for v in valores)) or 1.0
    return array("f", (v / norma for v in valores))


def _post(http: httpx.Client, url: str, clave: str, cuerpo: dict, espera: float, quien: str) -> dict | None:
    try:
        respuesta = http.post(url, json=cuerpo, headers={"Authorization": f"Bearer {clave}"}, timeout=espera)
        respuesta.raise_for_status()
        return respuesta.json()
    except (httpx.HTTPError, ValueError) as error:
        # Nunca se registra el cuerpo: lleva la pregunta de la persona.
        codigo = getattr(getattr(error, "response", None), "status_code", "sin respuesta")
        logger.warning("%s no respondió (%s, %s)", quien, type(error).__name__, codigo)
        return None


# ---------------------------------------------------------------- redacción


class ClienteIA:
    def __init__(self, config: Config, http: httpx.Client | None = None):
        self.config = config
        self.http = http or httpx.Client(timeout=config.espera_ia)
        self.proveedores: list[Proveedor] = list(config.proveedores)
        self.busqueda = crear_busqueda_semantica(config, self.http)
        self.ultimo_proveedor = ""

    @property
    def activa(self) -> bool:
        return bool(self.proveedores)

    def describir(self) -> dict:
        return {
            "proveedores": [{"nombre": p.nombre, "modelo": p.modelo} for p in self.proveedores],
            "busqueda": self.busqueda.describir(),
        }

    def chat(self, sistema: str, usuario: str) -> str | None:
        inicio = time.monotonic()
        for proveedor in self.proveedores:
            if time.monotonic() - inicio > LIMITE_CADENA_SEGUNDOS:
                break
            if proveedor.tipo == "cohere":
                texto = self._chat_cohere(proveedor, sistema, usuario)
            else:
                texto = self._chat_openai(proveedor, sistema, usuario)
            if texto:
                self.ultimo_proveedor = proveedor.nombre
                return texto
        return None

    def _chat_cohere(self, p: Proveedor, sistema: str, usuario: str) -> str | None:
        datos = _post(
            self.http, URL_COHERE_CHAT, p.clave,
            {
                "model": p.modelo, "temperature": 0.1, "max_tokens": 500,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
            },
            self.config.espera_ia, p.nombre,
        )
        try:
            partes = datos["message"]["content"]
            return "".join(x.get("text", "") for x in partes if x.get("type") == "text").strip() or None
        except (TypeError, KeyError, AttributeError):
            return None

    def _chat_openai(self, p: Proveedor, sistema: str, usuario: str) -> str | None:
        """Formato compatible con OpenAI: lo hablan Gemini, Groq, OpenRouter y Ollama."""
        datos = _post(
            self.http, p.url.rstrip("/") + "/chat/completions", p.clave,
            {
                "model": p.modelo, "temperature": 0.1, "max_tokens": 600,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
            },
            self.config.espera_ia, p.nombre,
        )
        try:
            return (datos["choices"][0]["message"]["content"] or "").strip() or None
        except (TypeError, KeyError, IndexError, AttributeError):
            return None

    def vectores(self, textos: list[str], tipo: str) -> list[array] | None:
        return self.busqueda.vectores(textos, tipo)


# ---------------------------------------------------------------- búsqueda por significado


class BusquedaSemantica:
    """Sin búsqueda por significado: el asistente usa solo palabras clave y respuestas aprobadas."""

    nombre = "ninguna"
    modelo = ""
    remota = False  # si cada consulta gasta una llamada de un servicio externo
    umbral = 1.1  # parecido mínimo para pasarle un fragmento a la IA
    umbral_literal = 1.1  # parecido mínimo para citar un artículo sin IA

    @property
    def disponible(self) -> bool:
        return self.nombre != "ninguna"

    def describir(self) -> dict:
        return {"nombre": self.nombre, "modelo": self.modelo, "remota": self.remota}

    def huella(self, texto: str) -> str:
        return hashlib.sha256(f"{self.nombre}:{self.modelo}\n{texto}".encode()).hexdigest()

    def vectores(self, textos: list[str], tipo: str) -> list[array] | None:
        return None


class BusquedaLocal(BusquedaSemantica):
    """Un modelo multilingüe pequeño que corre en el propio servidor: gratis, sin cuotas y sin enviar datos."""

    nombre = "local"
    # Calibrados con preguntas del tema y ajenas (ver README, sección de calibración).
    umbral = 0.52
    umbral_literal = 0.66

    def __init__(self, modelo: str):
        self.modelo = modelo
        self._modelo = None
        self._candado = threading.Lock()
        self._fallo = False

    def _cargar(self):
        with self._candado:
            if self._modelo is None and not self._fallo:
                try:
                    from fastembed import TextEmbedding

                    self._modelo = TextEmbedding(model_name=self.modelo, cache_dir=str(RAIZ / "datos" / "modelos"))
                except Exception as error:  # noqa: BLE001 - sin modelo, se sigue con palabras clave
                    self._fallo = True
                    logger.warning("No se pudo cargar el modelo local de búsqueda (%s)", type(error).__name__)
            return self._modelo

    def vectores(self, textos: list[str], tipo: str) -> list[array] | None:
        modelo = self._cargar()
        if modelo is None or not textos:
            return None
        try:
            return [_unitario(v) for v in modelo.embed(textos, batch_size=32)]
        except Exception as error:  # noqa: BLE001
            logger.warning("El modelo local de búsqueda falló (%s)", type(error).__name__)
            return None


class BusquedaCohere(BusquedaSemantica):
    nombre = "cohere"
    remota = True
    # Calibrados con Cohere real: las preguntas del tema dieron 0.56-0.79 y las ajenas 0.34-0.52.
    umbral = 0.53
    umbral_literal = 0.65

    def __init__(self, http: httpx.Client, clave: str, modelo: str, espera: int):
        self.http, self.clave, self.modelo, self.espera = http, clave, modelo, espera

    def vectores(self, textos: list[str], tipo: str) -> list[array] | None:
        """`tipo` es search_document al indexar y search_query al preguntar."""
        if not textos:
            return None
        salida: list[array] = []
        for inicio in range(0, len(textos), TAMANO_LOTE):
            datos = _post(
                self.http, URL_COHERE_EMBED, self.clave,
                {"model": self.modelo, "input_type": tipo, "embedding_types": ["float"], "texts": textos[inicio : inicio + TAMANO_LOTE]},
                max(self.espera, 30), "cohere (vectores)",
            )
            try:
                salida.extend(_unitario(v) for v in datos["embeddings"]["float"])
            except (TypeError, KeyError):
                return None
        return salida


class BusquedaCompatible(BusquedaSemantica):
    """Vectores por el formato compatible con OpenAI (por ejemplo, Gemini). Umbrales aún sin calibrar con datos reales."""

    remota = True
    umbral = 0.6
    umbral_literal = 0.75

    def __init__(self, http: httpx.Client, nombre: str, url: str, clave: str, modelo: str, espera: int):
        self.http, self.nombre, self.url, self.clave, self.modelo, self.espera = http, nombre, url, clave, modelo, espera

    def vectores(self, textos: list[str], tipo: str) -> list[array] | None:
        if not textos:
            return None
        salida: list[array] = []
        for inicio in range(0, len(textos), 64):
            datos = _post(
                self.http, self.url.rstrip("/") + "/embeddings", self.clave,
                {"model": self.modelo, "input": textos[inicio : inicio + 64]}, max(self.espera, 30), f"{self.nombre} (vectores)",
            )
            try:
                salida.extend(_unitario(x["embedding"]) for x in sorted(datos["data"], key=lambda x: x.get("index", 0)))
            except (TypeError, KeyError):
                return None
        return salida


def _hay_modelo_local() -> bool:
    try:
        import fastembed  # noqa: F401

        return True
    except ImportError:
        return False


def crear_busqueda_semantica(config: Config, http: httpx.Client) -> BusquedaSemantica:
    eleccion = config.busqueda_semantica
    if eleccion == "auto":
        if _hay_modelo_local():
            eleccion = "local"
        elif config.proveedor("cohere"):
            eleccion = "cohere"
        else:
            eleccion = "ninguna"
    if eleccion == "local" and _hay_modelo_local():
        return BusquedaLocal(config.modelo_local)
    cohere = config.proveedor("cohere")
    if eleccion == "cohere" and cohere:
        return BusquedaCohere(http, cohere.clave, os.environ.get("COHERE_MODELO_EMBED", "embed-multilingual-v3.0"), config.espera_ia)
    gemini = config.proveedor("gemini")
    if eleccion == "gemini" and gemini:
        return BusquedaCompatible(
            http, "gemini", gemini.url, gemini.clave, os.environ.get("GEMINI_MODELO_VECTORES", "gemini-embedding-001"), config.espera_ia
        )
    return BusquedaSemantica()
