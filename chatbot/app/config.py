"""Configuración del asistente. Todo lo que cambia entre entornos sale de variables de entorno."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def _cargar_env(ruta: Path) -> None:
    """Lee un archivo .env simple; las variables ya definidas en el sistema tienen prioridad."""
    if not ruta.exists():
        return
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


def _entero(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


def _lista(nombre: str, defecto: str) -> list[str]:
    return [v.strip() for v in os.environ.get(nombre, defecto).split(",") if v.strip()]


@dataclass
class Config:
    ruta_db: Path = field(default_factory=lambda: Path(os.environ.get("RUTA_DB", RAIZ / "datos" / "asistente.db")))
    cohere_api_key: str = field(default_factory=lambda: os.environ.get("COHERE_API_KEY", ""))
    modelo_chat: str = field(default_factory=lambda: os.environ.get("COHERE_MODELO_CHAT", "command-a-03-2025"))
    modelo_embed: str = field(default_factory=lambda: os.environ.get("COHERE_MODELO_EMBED", "embed-multilingual-v3.0"))
    # Tope de gasto: al llegar al límite diario, el asistente responde sin IA en lugar de seguir cobrando.
    max_llamadas_ia_dia: int = field(default_factory=lambda: _entero("MAX_LLAMADAS_IA_DIA", 2000))
    limite_minuto: int = field(default_factory=lambda: _entero("LIMITE_PREGUNTAS_MINUTO", 12))
    limite_dia: int = field(default_factory=lambda: _entero("LIMITE_PREGUNTAS_DIA", 200))
    origenes: list[str] = field(default_factory=lambda: _lista("ORIGENES_PERMITIDOS", "http://localhost:5500,http://127.0.0.1:5500"))
    # Solo activar detrás de un proxy propio: si no, cualquiera puede falsear su IP y saltarse los límites.
    confiar_proxy: bool = field(default_factory=lambda: os.environ.get("CONFIAR_PROXY", "") == "1")
    cookie_segura: bool = field(default_factory=lambda: os.environ.get("COOKIE_SEGURA", "") == "1")
    demo_clave: str = field(default_factory=lambda: os.environ.get("DEMO_CLAVE", ""))
    url_politica_datos: str = field(
        default_factory=lambda: os.environ.get(
            "URL_POLITICA_DATOS",
            "https://registro.univalle.edu.co/wp-content/uploads/2024/05/R_3395_Actualizacion_Politica_Tratamiento_Datos.pdf",
        )
    )

    @property
    def ia_activa(self) -> bool:
        return bool(self.cohere_api_key)


# Cualquier sitio de la universidad puede usar el chat; el panel nunca se expone a otros orígenes.
ORIGEN_UNIVALLE = r"https://([a-z0-9-]+\.)*univalle\.edu\.co"

DEPENDENCIAS = ["Secretaría General", "Registro Académico", "Admisiones", "Bienestar Universitario"]
ROLES = {"admin": "Administrador", "aprobador": "Aprobador", "editor": "Editor"}
TIPOS = {"articulo": "Norma", "faq": "Pregunta frecuente", "fecha": "Fecha", "contacto": "Contacto"}


def cargar_config() -> Config:
    _cargar_env(RAIZ / ".env")
    return Config()
