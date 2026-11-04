"""Cliente de Cohere. Ante cualquier fallo devuelve None y el asistente responde sin IA."""
from __future__ import annotations

import logging
from array import array
from math import sqrt

import httpx

from .config import Config

logger = logging.getLogger("asistente.ia")

URL_CHAT = "https://api.cohere.com/v2/chat"
URL_EMBED = "https://api.cohere.com/v2/embed"
TAMANO_LOTE = 96
ESPERA_SEGUNDOS = 28


class ClienteIA:
    def __init__(self, config: Config, http: httpx.Client | None = None):
        self.config = config
        self.http = http or httpx.Client(timeout=ESPERA_SEGUNDOS)

    @property
    def activa(self) -> bool:
        return self.config.ia_activa

    def _post(self, url: str, cuerpo: dict) -> dict | None:
        try:
            respuesta = self.http.post(url, json=cuerpo, headers={"Authorization": f"Bearer {self.config.cohere_api_key}"})
            respuesta.raise_for_status()
            return respuesta.json()
        except (httpx.HTTPError, ValueError) as error:
            # Nunca se registra el cuerpo: lleva la pregunta de la persona.
            codigo = getattr(getattr(error, "response", None), "status_code", "sin respuesta")
            logger.warning("Cohere no respondió (%s, %s)", type(error).__name__, codigo)
            return None

    def chat(self, sistema: str, usuario: str) -> str | None:
        if not self.activa:
            return None
        datos = self._post(
            URL_CHAT,
            {
                "model": self.config.modelo_chat,
                "temperature": 0.1,
                "max_tokens": 500,
                "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": usuario}],
            },
        )
        try:
            partes = datos["message"]["content"]
            texto = "".join(p.get("text", "") for p in partes if p.get("type") == "text").strip()
        except (TypeError, KeyError, AttributeError):
            return None
        return texto or None

    def vectores(self, textos: list[str], tipo: str) -> list[array] | None:
        """`tipo` es search_document al indexar y search_query al preguntar."""
        if not self.activa or not textos:
            return None
        salida: list[array] = []
        for inicio in range(0, len(textos), TAMANO_LOTE):
            datos = self._post(
                URL_EMBED,
                {
                    "model": self.config.modelo_embed,
                    "input_type": tipo,
                    "embedding_types": ["float"],
                    "texts": textos[inicio : inicio + TAMANO_LOTE],
                },
            )
            try:
                salida.extend(_unitario(v) for v in datos["embeddings"]["float"])
            except (TypeError, KeyError):
                return None
        return salida


def _unitario(valores: list[float]) -> array:
    """Normaliza el vector: así el producto punto ya es la similitud del coseno."""
    norma = sqrt(sum(v * v for v in valores)) or 1.0
    return array("f", (v / norma for v in valores))
