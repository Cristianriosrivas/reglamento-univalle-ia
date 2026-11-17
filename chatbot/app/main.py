"""
API del asistente.

- /api/chat, /api/config y /api/valoracion son públicas: las usa el chat flotante desde las páginas de la universidad.
- /api/panel/* exige sesión: es lo que usan los funcionarios para administrar el contenido.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import anyio.to_thread
import httpx
from fastapi import Body, Cookie, Depends, FastAPI, File, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import ajustes as A
from . import contenidos as C
from . import fuentes_web as W
from . import seguridad as S
from . import semilla
from . import texto as T
from . import usuarios as U
from .asistente import MAX_PREGUNTA, Asistente, fecha_legible, registrar_valoracion
from .config import DEPENDENCIAS, ORIGEN_UNIVALLE, PUBLICOS, RAIZ, ROLES, TIPOS, Config, cargar_config
from .db import conectar, hoy, inicializar, leer_metrica, sumar_dias

logger = logging.getLogger("asistente.api")

WEB = RAIZ / "web"
COOKIE = "sesion_panel"
MAX_ARCHIVO = 15 * 1024 * 1024
POR_PAGINA = 25
CSP_PANEL = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
TIPOS_RESPUESTA = ("aprobada", "novedades", "ia", "norma", "calendario", "personal", "sin_informacion", "reintentar", "fuera_de_tema", "saludo", "apoyo")


class MensajeHistorial(BaseModel):
    rol: Literal["usuario", "asistente"]
    texto: str = Field(max_length=2000)


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=2, max_length=2000)
    historial: list[MensajeHistorial] = Field(default_factory=list, max_length=20)
    perfil: Literal["aspirante", "estudiante"] | None = None


class Valoracion(BaseModel):
    pregunta: str = Field(min_length=2, max_length=2000)
    tipo: str = Field(max_length=30)
    fuentes: list[str] = Field(default_factory=list, max_length=5)
    util: bool


class Credenciales(BaseModel):
    correo: str = Field(max_length=200)
    clave: str = Field(max_length=200)


class CambioClave(BaseModel):
    actual: str = Field(max_length=200)
    nueva: str = Field(max_length=200)


class Nota(BaseModel):
    nota: str = Field(default="", max_length=500)


class SegmentoImportado(BaseModel):
    titulo: str = Field(max_length=300)
    texto: str = Field(max_length=C.MAX_TEXTO)
    capitulo: str = Field(default="", max_length=300)
    numero: int | None = None


class Importacion(BaseModel):
    nombre: str = Field(min_length=3, max_length=200)
    dependencia: str
    url: str = Field(default="", max_length=500)
    publico: Literal["todos", "aspirante", "estudiante"] = "todos"
    segmentos: list[SegmentoImportado] = Field(min_length=1, max_length=400)


class FuenteNueva(BaseModel):
    url: str = Field(max_length=500)
    nombre: str = Field(max_length=120)
    tipo: Literal["pagina", "noticias"] = "pagina"
    dependencia: str
    publico: Literal["todos", "aspirante", "estudiante"] = "todos"


def crear_app(
    config: Config | None = None, asistente: Asistente | None = None, http_web: httpx.Client | None = None
) -> FastAPI:
    config = config or cargar_config()
    asistente = asistente or Asistente(config)
    limite_chat = S.Limitador([(config.limite_minuto, 60), (config.limite_dia, 86_400)])
    limite_valoracion = S.Limitador([(30, 60)])
    limite_login = S.Limitador([(6, 600)])
    programador = W.Programador(config, asistente.invalidar) if config.fuentes_web else None
    http_web = http_web or httpx.Client(timeout=W.ESPERA)

    @asynccontextmanager
    async def ciclo(_: FastAPI):
        # Cada pregunta con IA ocupa un hilo mientras espera al proveedor: se amplía el límite por defecto.
        anyio.to_thread.current_default_thread_limiter().total_tokens = max(40, config.hilos)
        inicializar(config.ruta_db)
        conexion = conectar(config.ruta_db)
        if semilla.cargar_si_vacia(conexion, config.demo_clave):
            logger.info("Base de datos creada con el contenido inicial")
        if not conexion.execute("SELECT 1 FROM usuarios WHERE activo = 1 AND rol = 'admin'").fetchone():
            if config.admin_correo and config.admin_clave:
                try:
                    U.crear_administrador(conexion, config.admin_correo, "Administración", config.admin_clave)
                    logger.info("Cuenta de administración creada con ADMIN_CORREO")
                except C.ErrorContenido as error:
                    logger.warning("No se pudo crear la cuenta de ADMIN_CORREO: %s", error.mensaje)
            else:
                logger.warning("No hay administradores. Crea uno con: python -m app.admin crear --correo ... --nombre ...")
        # Se prepara el índice al arrancar para que la primera persona no espere.
        await run_in_threadpool(asistente.indice_publico, conexion)
        conexion.close()
        if programador:
            programador.iniciar()
        yield
        if programador:
            programador.detener()

    app = FastAPI(title="Asistente Univalle", docs_url=None, redoc_url=None, openapi_url=None, lifespan=ciclo)
    app.state.asistente = asistente
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.origenes,
        allow_origin_regex=ORIGEN_UNIVALLE,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def cabeceras(request: Request, siguiente):
        respuesta = await siguiente(request)
        ruta = request.url.path
        respuesta.headers["X-Content-Type-Options"] = "nosniff"
        respuesta.headers["Referrer-Policy"] = "same-origin"
        if ruta.startswith("/panel"):
            respuesta.headers["Content-Security-Policy"] = CSP_PANEL
            respuesta.headers["X-Frame-Options"] = "DENY"
        if ruta == "/widget.js":
            respuesta.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
            respuesta.headers["Cache-Control"] = "public, max-age=300"
        if ruta.startswith("/api/panel"):
            respuesta.headers["Cache-Control"] = "no-store"
        return respuesta

    @app.exception_handler(C.ErrorContenido)
    async def error_contenido(_: Request, error: C.ErrorContenido):
        return JSONResponse({"detail": error.mensaje}, status_code=error.codigo)

    def db() -> Iterator:
        conexion = conectar(config.ruta_db)
        try:
            yield conexion
        finally:
            conexion.close()

    def ip_de(request: Request) -> str:
        if config.confiar_proxy:
            reenviada = request.headers.get("x-forwarded-for", "")
            if reenviada:
                return reenviada.split(",")[0].strip()
        return request.client.host if request.client else "desconocida"

    def sesion(sesion_panel: str | None = Cookie(default=None), conexion=Depends(db)) -> dict:
        usuario = S.usuario_de_sesion(conexion, sesion_panel)
        if not usuario:
            raise HTTPException(401, "Inicia sesión para continuar.")
        return usuario

    def usuario_actual(usuario: dict = Depends(sesion)) -> dict:
        """Quien entra con una contraseña temporal debe cambiarla antes de hacer cualquier otra cosa."""
        if usuario["debe_cambiar_clave"]:
            raise HTTPException(403, "Cambia tu contraseña temporal para continuar.")
        return usuario

    def solo_admin(usuario: dict = Depends(usuario_actual)) -> dict:
        if usuario["rol"] != "admin":
            raise HTTPException(403, "Solo un administrador puede hacer esto.")
        return usuario

    def peticion_del_panel(x_panel: str | None = Header(default=None)) -> None:
        """Otro sitio no puede enviar esta cabecera sin permiso de CORS: bloquea peticiones falsificadas."""
        if x_panel != "1":
            raise HTTPException(403, "Petición no permitida.")

    def archivos(ruta: str) -> Path:
        return WEB / ruta

    # ----- Páginas -----
    @app.get("/", include_in_schema=False)
    def inicio():
        return RedirectResponse("/demo")

    @app.get("/demo", include_in_schema=False)
    def demo():
        return FileResponse(archivos("demo/index.html"))

    @app.get("/widget.js", include_in_schema=False)
    def widget():
        return FileResponse(archivos("widget.js"), media_type="application/javascript")

    @app.get("/panel", include_in_schema=False)
    def panel():
        return FileResponse(archivos("panel/index.html"))

    @app.get("/panel/{nombre}", include_in_schema=False)
    def panel_estaticos(nombre: str):
        permitidos = {"panel.js": "application/javascript", "panel.css": "text/css"}
        if nombre not in permitidos:
            raise HTTPException(404)
        return FileResponse(archivos(f"panel/{nombre}"), media_type=permitidos[nombre])

    # ----- Chat público -----
    @app.get("/salud")
    def salud():
        return {"estado": "ok", "ia": config.ia_activa, "busqueda": asistente.ia.busqueda.nombre}

    @app.get("/api/config")
    def configuracion(conexion=Depends(db)):
        valores = A.todos(conexion)
        return {
            "nombre": valores["nombre"],
            "bienvenida": valores["bienvenida"],
            "sugerencias": {"aspirante": valores["sugerencias_aspirante"], "estudiante": valores["sugerencias_estudiante"]},
            "aviso": C.aviso_destacado(conexion, hoy()),
            "maximo": MAX_PREGUNTA,
            "politica": config.url_politica_datos,
        }

    @app.post("/api/chat")
    def chat(datos: Pregunta, request: Request, conexion=Depends(db)):
        if not limite_chat.permitir(ip_de(request)):
            raise HTTPException(429, "Has hecho muchas preguntas seguidas. Espera un momento e inténtalo de nuevo.")
        historial = [m.model_dump() for m in datos.historial]
        return asistente.responder(conexion, datos.pregunta, historial, perfil=datos.perfil).como_dict()

    @app.post("/api/valoracion")
    def valorar(datos: Valoracion, request: Request, conexion=Depends(db)):
        if not limite_valoracion.permitir(ip_de(request)):
            raise HTTPException(429, "Gracias, ya recibimos tus valoraciones.")
        registrar_valoracion(conexion, datos.pregunta, datos.tipo, datos.fuentes, datos.util)
        return {"ok": True}

    # ----- Sesión del panel -----
    @app.post("/api/panel/entrar", dependencies=[Depends(peticion_del_panel)])
    def entrar(datos: Credenciales, request: Request, respuesta: Response, conexion=Depends(db)):
        clave_limite = f"{ip_de(request)}:{datos.correo.lower()}"
        if not limite_login.permitir(clave_limite):
            raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")
        fila = conexion.execute(
            "SELECT * FROM usuarios WHERE correo = ? AND activo = 1", (datos.correo.strip().lower(),)
        ).fetchone()
        if not fila or not S.verificar_clave(datos.clave, fila["clave_hash"]):
            raise HTTPException(401, "Correo o contraseña incorrectos.")
        limite_login.reiniciar(clave_limite)
        token = S.abrir_sesion(conexion, fila["id"])
        respuesta.set_cookie(
            COOKIE, token, httponly=True, samesite="strict", secure=config.cookie_segura,
            max_age=int(S.DURACION_SESION.total_seconds()), path="/",
        )
        return {"nombre": fila["nombre"], "rol": fila["rol"], "debe_cambiar_clave": bool(fila["debe_cambiar_clave"])}

    @app.post("/api/panel/salir", dependencies=[Depends(peticion_del_panel)])
    def salir(respuesta: Response, sesion_panel: str | None = Cookie(default=None), conexion=Depends(db)):
        S.cerrar_sesion(conexion, sesion_panel)
        respuesta.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/panel/yo")
    def yo(usuario: dict = Depends(sesion)):
        return {
            **usuario,
            "debe_cambiar_clave": bool(usuario["debe_cambiar_clave"]),
            "nombre_rol": ROLES[usuario["rol"]],
            "puede_publicar": usuario["rol"] in ("admin", "aprobador"),
            "dependencias": DEPENDENCIAS,
            "tipos": TIPOS,
            "publicos": PUBLICOS,
            "roles": ROLES,
            "ia": config.ia_activa,
        }

    @app.post("/api/panel/mi-clave", dependencies=[Depends(peticion_del_panel)])
    def mi_clave(datos: CambioClave, usuario: dict = Depends(sesion), conexion=Depends(db)):
        U.cambiar_propia_clave(conexion, usuario["id"], datos.actual, datos.nueva)
        return {"ok": True}

    # ----- Estadísticas -----
    @app.get("/api/panel/resumen")
    def resumen(usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        conteos = dict(
            conexion.execute(
                """SELECT tipo, COUNT(*) FROM contenidos
                   WHERE estado = 'publicado' AND reemplazado_por IS NULL GROUP BY tipo"""
            ).fetchall()
        )
        valores = A.todos(conexion)
        tope = valores["max_llamadas_ia_dia"]
        return {
            "publicados": conteos,
            "en_revision": conexion.execute(
                "SELECT COUNT(*) FROM contenidos WHERE estado = 'revision' OR pendiente_estado = 'revision'"
            ).fetchone()[0],
            "borradores": conexion.execute(
                "SELECT COUNT(*) FROM contenidos WHERE estado = 'borrador' OR pendiente_estado = 'borrador'"
            ).fetchone()[0],
            "sin_respuesta": conexion.execute("SELECT COUNT(*) FROM sin_respuesta WHERE resuelta = 0").fetchone()[0],
            "fuentes_con_error": conexion.execute(
                "SELECT COUNT(*) FROM fuentes_web WHERE activa = 1 AND error != ''"
            ).fetchone()[0],
            "preguntas_hoy": leer_metrica(conexion, "preguntas"),
            "llamadas_ia_hoy": leer_metrica(conexion, "llamadas_ia"),
            "tope_ia": config.max_llamadas_ia_dia if tope is None else tope,
            "ia": config.ia_activa and bool(valores["ia_activa"]),
            "ia_configurada": config.ia_activa,
        }

    @app.get("/api/panel/estadisticas")
    def estadisticas(dias: int = Query(14, ge=1, le=90), usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        hasta = hoy()
        desde = sumar_dias(hasta, -(dias - 1))
        filas = conexion.execute("SELECT dia, clave, valor FROM metricas WHERE dia BETWEEN ? AND ?", (desde, hasta)).fetchall()
        por_dia: dict[str, dict] = {sumar_dias(desde, i): {} for i in range(dias)}
        totales: dict[str, int] = {}
        for f in filas:
            por_dia.setdefault(f["dia"], {})[f["clave"]] = f["valor"]
            totales[f["clave"]] = totales.get(f["clave"], 0) + f["valor"]
        valoraciones = conexion.execute(
            "SELECT SUM(util), COUNT(*) FROM valoraciones WHERE dia BETWEEN ? AND ?", (desde, hasta)
        ).fetchone()
        utiles, total_val = valoraciones[0] or 0, valoraciones[1] or 0
        malas = conexion.execute(
            "SELECT fecha, pregunta, tipo, fuentes FROM valoraciones WHERE util = 0 ORDER BY id DESC LIMIT 15"
        ).fetchall()
        preguntas = totales.get("preguntas", 0)
        respondidas_sin_ia = sum(totales.get(f"respuestas_{t}", 0) for t in ("aprobada", "novedades", "norma", "calendario", "personal"))
        return {
            "dias": [
                {
                    "dia": dia,
                    "preguntas": v.get("preguntas", 0),
                    "ia": v.get("respuestas_ia", 0),
                    "sin_respuesta": v.get("respuestas_sin_informacion", 0),
                }
                for dia, v in sorted(por_dia.items())
            ],
            "tipos": {t: totales.get(f"respuestas_{t}", 0) for t in TIPOS_RESPUESTA},
            "proveedores": {k[3:]: v for k, v in totales.items() if k.startswith("ia_")},
            "preguntas": preguntas,
            "sin_ia": round(100 * respondidas_sin_ia / preguntas) if preguntas else None,
            "valoraciones": {"utiles": utiles, "total": total_val, "porcentaje": round(100 * utiles / total_val) if total_val else None},
            "mal_valoradas": [{**dict(m), "fuentes": json.loads(m["fuentes"])} for m in malas],
        }

    @app.get("/api/panel/ia")
    def estado_ia(usuario: dict = Depends(usuario_actual)):
        """Qué servicios de IA están configurados. Nunca devuelve claves."""
        return asistente.ia.describir()

    # ----- Contenidos -----
    def _resumen_fila(fila) -> dict:
        datos = dict(fila)
        pendiente = json.loads(datos.pop("pendiente")) if datos.get("pendiente") else None
        datos["tiene_cambios"] = pendiente is not None
        datos["vista"] = pendiente or {c: datos[c] for c in C.CAMPOS}
        datos["fecha_legible"] = fecha_legible(datos["vista"].get("inicio"), datos["vista"].get("fin"))
        return datos

    @app.get("/api/panel/contenidos")
    def listar(
        tipo: str = "", estado: str = "", dependencia: str = "", publico: str = "", origen: str = "", q: str = "",
        pagina: int = Query(1, ge=1), usuario: dict = Depends(usuario_actual), conexion=Depends(db),
    ):
        condiciones, valores = ["c.reemplazado_por IS NULL"], []
        for campo, valor in (("tipo", tipo), ("dependencia", dependencia), ("publico", publico), ("origen", origen)):
            if valor:
                condiciones.append(f"c.{campo} = ?")
                valores.append(valor)
        if estado == "revision":
            condiciones.append("(c.estado = 'revision' OR c.pendiente_estado = 'revision')")
        elif estado == "borrador":
            condiciones.append("(c.estado = 'borrador' OR c.pendiente_estado = 'borrador')")
        elif estado:
            condiciones.append("c.estado = ?")
            valores.append(estado)
        else:
            condiciones.append("c.estado != 'archivado'")
        if q.strip():
            condiciones.append("(c.titulo LIKE ? OR c.texto LIKE ?)")
            valores += [f"%{q.strip()}%"] * 2
        donde = " AND ".join(condiciones)
        total = conexion.execute(f"SELECT COUNT(*) FROM contenidos c WHERE {donde}", valores).fetchone()[0]
        filas = conexion.execute(
            f"""SELECT c.*, COALESCE(f.nombre, fw.nombre) AS fuente FROM contenidos c
                LEFT JOIN fuentes f ON f.id = c.fuente_id
                LEFT JOIN fuentes_web fw ON c.origen = 'web' AND c.origen_ref LIKE 'web' || fw.id || ':%'
                WHERE {donde}
                ORDER BY (c.estado = 'revision' OR c.pendiente_estado = 'revision') DESC,
                         CASE c.tipo WHEN 'novedad' THEN 0 WHEN 'faq' THEN 1 WHEN 'fecha' THEN 2 WHEN 'contacto' THEN 3
                                     WHEN 'pagina' THEN 4 ELSE 5 END,
                         CASE WHEN c.tipo = 'novedad' THEN c.inicio END DESC, c.fuente_id, c.numero, c.id
                LIMIT ? OFFSET ?""",
            [*valores, POR_PAGINA, (pagina - 1) * POR_PAGINA],
        ).fetchall()
        return {"total": total, "por_pagina": POR_PAGINA, "items": [_resumen_fila(f) for f in filas]}

    @app.get("/api/panel/contenidos/{contenido_id}")
    def detalle(contenido_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        fila = conexion.execute(
            """SELECT c.*, COALESCE(f.nombre, fw.nombre) AS fuente, COALESCE(f.nota, '') AS fuente_nota FROM contenidos c
               LEFT JOIN fuentes f ON f.id = c.fuente_id
               LEFT JOIN fuentes_web fw ON c.origen = 'web' AND c.origen_ref LIKE 'web' || fw.id || ':%'
               WHERE c.id = ?""",
            (contenido_id,),
        ).fetchone()
        if not fila:
            raise HTTPException(404, "Ese contenido no existe.")
        versiones = conexion.execute(
            "SELECT id, accion, autor, fecha FROM versiones WHERE contenido_id = ? ORDER BY id DESC LIMIT 30", (contenido_id,)
        ).fetchall()
        datos = _resumen_fila(fila)
        datos["publicado"] = {c: fila[c] for c in C.CAMPOS} if fila["estado"] == "publicado" else None
        datos["versiones"] = [dict(v) for v in versiones]
        datos["puede_editar"] = C.puede_editar(usuario, fila["dependencia"])
        datos["puede_publicar"] = C.puede_publicar(usuario, fila["dependencia"])
        return datos

    @app.post("/api/panel/contenidos", dependencies=[Depends(peticion_del_panel)])
    def crear(datos: dict = Body(...), usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        return {"id": C.crear(conexion, datos, usuario)}

    @app.post("/api/panel/contenidos/{contenido_id}", dependencies=[Depends(peticion_del_panel)])
    def editar(contenido_id: int, datos: dict = Body(...), usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        C.editar(conexion, contenido_id, datos, usuario)
        return {"ok": True}

    @app.post("/api/panel/contenidos/{contenido_id}/enviar", dependencies=[Depends(peticion_del_panel)])
    def enviar(contenido_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        C.enviar_a_revision(conexion, contenido_id, usuario)
        return {"ok": True}

    @app.post("/api/panel/contenidos/{contenido_id}/publicar", dependencies=[Depends(peticion_del_panel)])
    def publicar(contenido_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        C.publicar(conexion, contenido_id, usuario)
        asistente.invalidar()
        return {"ok": True}

    @app.post("/api/panel/contenidos/{contenido_id}/devolver", dependencies=[Depends(peticion_del_panel)])
    def devolver(contenido_id: int, datos: Nota, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        C.devolver(conexion, contenido_id, datos.nota, usuario)
        return {"ok": True}

    @app.post("/api/panel/contenidos/{contenido_id}/descartar", dependencies=[Depends(peticion_del_panel)])
    def descartar(contenido_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        C.descartar_cambios(conexion, contenido_id, usuario)
        return {"ok": True}

    @app.post("/api/panel/contenidos/{contenido_id}/archivar", dependencies=[Depends(peticion_del_panel)])
    def archivar(contenido_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        C.archivar(conexion, contenido_id, usuario)
        asistente.invalidar()
        return {"ok": True}

    @app.post("/api/panel/contenidos/{contenido_id}/restaurar/{version_id}", dependencies=[Depends(peticion_del_panel)])
    def restaurar(contenido_id: int, version_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        C.restaurar(conexion, contenido_id, version_id, usuario)
        return {"ok": True}

    # ----- Importar documentos -----
    @app.post("/api/panel/importar", dependencies=[Depends(peticion_del_panel)])
    async def importar(archivo: UploadFile = File(...), usuario: dict = Depends(usuario_actual)):
        """Solo extrae y muestra el resultado: nada se guarda hasta que la persona lo revise y confirme."""
        contenido = await archivo.read(MAX_ARCHIVO + 1)
        if len(contenido) > MAX_ARCHIVO:
            raise C.ErrorContenido("El archivo supera los 15 MB.", 413)
        try:
            # Un PDF grande tarda varios segundos: en otro hilo, para que el chat siga respondiendo.
            extraido = await run_in_threadpool(T.extraer, archivo.filename or "", contenido)
        except ValueError as error:
            raise C.ErrorContenido(str(error)) from error
        except Exception as error:  # noqa: BLE001 - un archivo dañado no debe tumbar el panel
            logger.warning("No se pudo leer un archivo importado (%s)", type(error).__name__)
            raise C.ErrorContenido("No se pudo leer el archivo. Verifica que no esté dañado o protegido.") from error
        segmentos = [] if extraido.es_escaneo else T.segmentar(extraido.texto)
        return {
            "paginas": extraido.paginas,
            "es_escaneo": extraido.es_escaneo,
            "advertencias": extraido.advertencias,
            "segmentos": [
                {"titulo": s.titulo, "texto": s.texto, "capitulo": s.capitulo, "numero": s.numero} for s in segmentos
            ],
        }

    @app.post("/api/panel/importar/confirmar", dependencies=[Depends(peticion_del_panel)])
    def confirmar(datos: Importacion, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        if not C.puede_editar(usuario, datos.dependencia):
            raise C.ErrorContenido(f"Solo puedes cargar documentos de {usuario['dependencia']}.", 403)
        fila = conexion.execute("SELECT id FROM fuentes WHERE nombre = ?", (datos.nombre,)).fetchone()
        fuente_id = fila["id"] if fila else conexion.execute(
            "INSERT INTO fuentes (nombre, dependencia, url) VALUES (?, ?, ?)", (datos.nombre, datos.dependencia, datos.url)
        ).lastrowid
        creados = 0
        for segmento in datos.segmentos:
            C.crear(
                conexion,
                {
                    "tipo": "articulo", "dependencia": datos.dependencia, "fuente_id": fuente_id, "url": datos.url,
                    "titulo": f"{segmento.titulo} — {datos.nombre}", "texto": segmento.texto,
                    "capitulo": segmento.capitulo, "numero": segmento.numero, "publico": datos.publico,
                },
                usuario,
            )
            creados += 1
        return {"creados": creados}

    # ----- Fuentes web -----
    @app.get("/api/panel/fuentes-web")
    def fuentes_web(usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        return [dict(f) for f in conexion.execute("SELECT * FROM fuentes_web ORDER BY tipo DESC, nombre")]

    @app.post("/api/panel/fuentes-web", dependencies=[Depends(peticion_del_panel)])
    def agregar_fuente(datos: FuenteNueva, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        if not C.puede_publicar(usuario, datos.dependencia):
            raise C.ErrorContenido("Solo un aprobador de la dependencia o un administrador puede agregar fuentes.", 403)
        fuente_id = W.agregar(conexion, datos.model_dump(), config.dominios_web)
        resultado = W.sincronizar(conexion, fuente_id, http_web, config.dominios_web)
        asistente.invalidar()
        return {"id": fuente_id, **resultado}

    @app.post("/api/panel/fuentes-web/{fuente_id}/actualizar", dependencies=[Depends(peticion_del_panel)])
    def actualizar_fuente(fuente_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        resultado = W.sincronizar(conexion, fuente_id, http_web, config.dominios_web)
        asistente.invalidar()
        return resultado

    @app.post("/api/panel/fuentes-web/{fuente_id}/activa", dependencies=[Depends(peticion_del_panel)])
    def activar_fuente(fuente_id: int, datos: dict = Body(...), usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        fuente = conexion.execute("SELECT * FROM fuentes_web WHERE id = ?", (fuente_id,)).fetchone()
        if not fuente:
            raise HTTPException(404, "Esa fuente no existe.")
        if not C.puede_publicar(usuario, fuente["dependencia"]):
            raise C.ErrorContenido("Solo un aprobador de la dependencia o un administrador puede cambiar esta fuente.", 403)
        activa = bool(datos.get("activa"))
        conexion.execute("UPDATE fuentes_web SET activa = ? WHERE id = ?", (int(activa), fuente_id))
        if not activa:
            # Pausar una fuente la saca del asistente; al reactivarla vuelve con la siguiente actualización.
            conexion.execute(
                "UPDATE contenidos SET estado = 'archivado' WHERE origen = 'web' AND origen_ref LIKE ? AND estado = 'publicado'",
                (f"web{fuente_id}:%",),
            )
            conexion.execute("UPDATE fuentes_web SET huella = '' WHERE id = ?", (fuente_id,))
        conexion.commit()
        A.subir_version(conexion)
        asistente.invalidar()
        return {"ok": True}

    # ----- Usuarios (solo administración) -----
    @app.get("/api/panel/usuarios")
    def lista_usuarios(usuario: dict = Depends(solo_admin), conexion=Depends(db)):
        return U.listar(conexion)

    @app.post("/api/panel/usuarios", dependencies=[Depends(peticion_del_panel)])
    def nuevo_usuario(datos: dict = Body(...), usuario: dict = Depends(solo_admin), conexion=Depends(db)):
        usuario_id, temporal = U.crear(conexion, datos)
        return {"id": usuario_id, "clave_temporal": temporal}

    @app.post("/api/panel/usuarios/{usuario_id}", dependencies=[Depends(peticion_del_panel)])
    def cambiar_usuario(usuario_id: int, datos: dict = Body(...), usuario: dict = Depends(solo_admin), conexion=Depends(db)):
        U.actualizar(conexion, usuario_id, datos, usuario)
        return {"ok": True}

    @app.post("/api/panel/usuarios/{usuario_id}/clave", dependencies=[Depends(peticion_del_panel)])
    def restablecer(usuario_id: int, usuario: dict = Depends(solo_admin), conexion=Depends(db)):
        return {"clave_temporal": U.restablecer_clave(conexion, usuario_id)}

    # ----- Ajustes -----
    @app.get("/api/panel/ajustes")
    def ver_ajustes(usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        valores = A.todos(conexion)
        valores.pop("version_contenido", None)
        return {**valores, "tope_servidor": config.max_llamadas_ia_dia}

    @app.post("/api/panel/ajustes", dependencies=[Depends(peticion_del_panel)])
    def guardar_ajustes(datos: dict = Body(...), usuario: dict = Depends(solo_admin), conexion=Depends(db)):
        valores = A.actualizar(conexion, datos)
        asistente.invalidar()
        valores.pop("version_contenido", None)
        return valores

    # ----- Preguntas sin respuesta -----
    @app.get("/api/panel/sin-respuesta")
    def sin_respuesta(usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        filas = conexion.execute(
            "SELECT * FROM sin_respuesta WHERE resuelta = 0 ORDER BY veces DESC, ultima DESC LIMIT 100"
        ).fetchall()
        return [dict(f) for f in filas]

    @app.post("/api/panel/sin-respuesta/{pregunta_id}/resolver", dependencies=[Depends(peticion_del_panel)])
    def resolver(pregunta_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        conexion.execute("UPDATE sin_respuesta SET resuelta = 1 WHERE id = ?", (pregunta_id,))
        conexion.commit()
        return {"ok": True}

    # ----- Actividad y prueba -----
    @app.get("/api/panel/actividad")
    def actividad(usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        filas = conexion.execute(
            """SELECT v.id, v.contenido_id, v.accion, v.autor, v.fecha, c.titulo, c.tipo, c.dependencia
               FROM versiones v JOIN contenidos c ON c.id = v.contenido_id
               WHERE v.autor != 'Carga inicial' ORDER BY v.id DESC LIMIT 60"""
        ).fetchall()
        return [dict(f) for f in filas]

    @app.post("/api/panel/probar", dependencies=[Depends(peticion_del_panel)])
    def probar(datos: Pregunta, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        """Responde como si todo lo pendiente ya estuviera publicado, sin afectar al público ni a las métricas."""
        historial = [m.model_dump() for m in datos.historial]
        return asistente.responder(conexion, datos.pregunta, historial, prueba=True, perfil=datos.perfil).como_dict()

    return app


app = crear_app()
