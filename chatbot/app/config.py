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


def _texto(nombre: str, defecto: str = "") -> str:
    return os.environ.get(nombre, defecto).strip()


def _entero(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(nombre, defecto))
    except ValueError:
        return defecto


def _lista(nombre: str, defecto: str) -> list[str]:
    return [v.strip() for v in os.environ.get(nombre, defecto).split(",") if v.strip()]


def _si(nombre: str, defecto: bool) -> bool:
    valor = os.environ.get(nombre)
    return defecto if valor is None else valor.strip().lower() in ("1", "si", "sí", "true", "yes")


@dataclass
class Proveedor:
    """Un servicio de IA. `tipo` es «cohere» o «openai» (formato compatible: Gemini, Groq, Ollama, OpenRouter)."""

    nombre: str
    tipo: str
    clave: str
    modelo: str
    url: str = ""


# Servicios con plan gratuito, en el orden en que se intentan si hay clave para ellos.
_GRATUITOS = (
    ("gemini", "openai", "GEMINI_API_KEY", "GEMINI_MODELO", "gemini-3.8-flash",
     "https://generativelanguage.googleapis.com/v1beta/openai/"),
    ("groq", "openai", "GROQ_API_KEY", "GROQ_MODELO", "llama-3.3-70b-versatile", "https://api.groq.com/openai/v1/"),
    ("cohere", "cohere", "COHERE_API_KEY", "COHERE_MODELO_CHAT", "command-a-03-2025", ""),
)


def _proveedores() -> list[Proveedor]:
    disponibles: dict[str, Proveedor] = {}
    for nombre, tipo, clave, modelo, defecto, url in _GRATUITOS:
        if _texto(clave):
            disponibles[nombre] = Proveedor(nombre, tipo, _texto(clave), _texto(modelo, defecto), url)
    # Un servicio propio o local (por ejemplo Ollama en http://localhost:11434/v1/), sin costo por uso.
    if _texto("IA_LOCAL_URL") and _texto("IA_LOCAL_MODELO"):
        disponibles["local"] = Proveedor(
            "local", "openai", _texto("IA_LOCAL_CLAVE", "local"), _texto("IA_LOCAL_MODELO"), _texto("IA_LOCAL_URL")
        )
    orden = _lista("IA_PROVEEDORES", "local,gemini,groq,cohere")
    return [disponibles[n] for n in orden if n in disponibles]


@dataclass
class Config:
    entorno: str = field(default_factory=lambda: _texto("ENTORNO", "desarrollo").lower())
    ruta_db: Path = field(default_factory=lambda: Path(os.environ.get("RUTA_DB", RAIZ / "datos" / "asistente.db")))
    proveedores: list[Proveedor] = field(default_factory=_proveedores)
    # «local» (gratis, sin límites, el modelo corre en el servidor), «cohere», «gemini» o «ninguna».
    busqueda_semantica: str = field(default_factory=lambda: _texto("BUSQUEDA_SEMANTICA", "auto").lower())
    modelo_local: str = field(
        default_factory=lambda: _texto("MODELO_BUSQUEDA_LOCAL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    )
    max_llamadas_ia_dia: int = field(default_factory=lambda: _entero("MAX_LLAMADAS_IA_DIA", 900))
    espera_ia: int = field(default_factory=lambda: _entero("ESPERA_IA_SEGUNDOS", 14))
    limite_minuto: int = field(default_factory=lambda: _entero("LIMITE_PREGUNTAS_MINUTO", 12))
    limite_dia: int = field(default_factory=lambda: _entero("LIMITE_PREGUNTAS_DIA", 200))
    origenes: list[str] = field(default_factory=lambda: _lista("ORIGENES_PERMITIDOS", "http://localhost:5500,http://127.0.0.1:5500"))
    # Solo activar detrás de un proxy propio: si no, cualquiera puede falsear su IP y saltarse los límites.
    confiar_proxy: bool = field(default_factory=lambda: _si("CONFIAR_PROXY", False))
    cookie_segura: bool = field(default_factory=lambda: _si("COOKIE_SEGURA", False))
    demo_clave: str = field(default_factory=lambda: _texto("DEMO_CLAVE"))
    # Primera cuenta de administración en servidores sin terminal (Hugging Face, Render…). Solo se usa si no hay ninguna.
    admin_correo: str = field(default_factory=lambda: _texto("ADMIN_CORREO"))
    admin_clave: str = field(default_factory=lambda: _texto("ADMIN_CLAVE"), repr=False)
    fuentes_web: bool = field(default_factory=lambda: _si("FUENTES_WEB", True))
    actualizar_cada_horas: int = field(default_factory=lambda: _entero("ACTUALIZAR_CADA_HORAS", 12))
    dominios_web: list[str] = field(default_factory=lambda: _lista("DOMINIOS_PERMITIDOS", "univalle.edu.co"))
    hilos: int = field(default_factory=lambda: _entero("HILOS_SERVIDOR", 80))
    url_politica_datos: str = field(
        default_factory=lambda: _texto(
            "URL_POLITICA_DATOS",
            "https://registro.univalle.edu.co/wp-content/uploads/2024/05/R_3395_Actualizacion_Politica_Tratamiento_Datos.pdf",
        )
    )
    url_calendarios: str = field(
        default_factory=lambda: _texto("URL_CALENDARIOS", "https://registro.univalle.edu.co/calendarios/")
    )

    def __post_init__(self) -> None:
        if self.produccion:
            # En producción las cookies solo viajan por HTTPS y no existen usuarios de prueba.
            self.cookie_segura = True
            self.demo_clave = ""

    @property
    def produccion(self) -> bool:
        return self.entorno == "produccion"

    @property
    def ia_activa(self) -> bool:
        return bool(self.proveedores)

    def proveedor(self, nombre: str) -> Proveedor | None:
        return next((p for p in self.proveedores if p.nombre == nombre), None)


# Cualquier sitio de la universidad puede usar el chat; el panel nunca se expone a otros orígenes.
ORIGEN_UNIVALLE = r"https://([a-z0-9-]+\.)*univalle\.edu\.co"

DEPENDENCIAS = ["Secretaría General", "Registro Académico", "Admisiones", "Bienestar Universitario", "Comunicaciones"]
ROLES = {"admin": "Administrador", "aprobador": "Aprobador", "editor": "Editor"}
TIPOS = {
    "articulo": "Norma",
    "faq": "Pregunta frecuente",
    "pagina": "Página oficial",
    "novedad": "Novedad",
    "fecha": "Fecha",
    "contacto": "Contacto",
}
PUBLICOS = {"todos": "Todos", "aspirante": "Aspirantes", "estudiante": "Estudiantes"}


def cargar_config() -> Config:
    _cargar_env(RAIZ / ".env")
    return Config()
