"""
API del asistente.

- /api/chat y /api/config son públicas: las usa el chat flotante desde las páginas de la universidad.
- /api/panel/* exige sesión: es lo que usan los funcionarios para administrar el contenido.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from . import contenidos as C
from . import seguridad as S
from . import semilla
from . import texto as T
from .asistente import MAX_PREGUNTA, Asistente, fecha_legible
from .config import DEPENDENCIAS, ORIGEN_UNIVALLE, RAIZ, ROLES, TIPOS, Config, cargar_config
from .db import conectar, inicializar, leer_metrica

logger = logging.getLogger("asistente.api")

WEB = RAIZ / "web"
COOKIE = "sesion_panel"
MAX_ARCHIVO = 15 * 1024 * 1024
POR_PAGINA = 25
CSP_PANEL = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"


class MensajeHistorial(BaseModel):
    rol: str = Field(max_length=20)
    texto: str = Field(max_length=2000)


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=2, max_length=2000)
    historial: list[MensajeHistorial] = Field(default_factory=list, max_length=20)


class Credenciales(BaseModel):
    correo: str = Field(max_length=200)
    clave: str = Field(max_length=200)


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
    segmentos: list[SegmentoImportado] = Field(min_length=1, max_length=400)


def crear_app(config: Config | None = None, asistente: Asistente | None = None) -> FastAPI:
    config = config or cargar_config()
    asistente = asistente or Asistente(config)
    limite_chat = S.Limitador([(config.limite_minuto, 60), (config.limite_dia, 86_400)])
    limite_login = S.Limitador([(6, 600)])

    @asynccontextmanager
    async def ciclo(_: FastAPI):
        inicializar(config.ruta_db)
        conexion = conectar(config.ruta_db)
        if semilla.cargar_si_vacia(conexion, config.demo_clave):
            logger.info("Base de datos creada con el contenido inicial")
        # Se prepara el índice al arrancar para que la primera persona no espere.
        asistente.indice_publico(conexion)
        conexion.close()
        yield

    app = FastAPI(title="Asistente estudiantil", docs_url=None, redoc_url=None, openapi_url=None, lifespan=ciclo)
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

    def usuario_actual(sesion_panel: str | None = Cookie(default=None), conexion=Depends(db)) -> dict:
        usuario = S.usuario_de_sesion(conexion, sesion_panel)
        if not usuario:
            raise HTTPException(401, "Inicia sesión para continuar.")
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
        return {"estado": "ok", "ia": config.ia_activa}

    @app.get("/api/config")
    def configuracion(conexion=Depends(db)):
        filas = conexion.execute(
            """SELECT titulo FROM contenidos WHERE tipo = 'faq' AND estado = 'publicado' AND destacada = 1
               AND reemplazado_por IS NULL ORDER BY id LIMIT 4"""
        ).fetchall()
        return {
            "sugerencias": [f["titulo"] for f in filas],
            "maximo": MAX_PREGUNTA,
            "politica": config.url_politica_datos,
        }

    @app.post("/api/chat")
    def chat(datos: Pregunta, request: Request, conexion=Depends(db)):
        if not limite_chat.permitir(ip_de(request)):
            raise HTTPException(429, "Has hecho muchas preguntas seguidas. Espera un momento e inténtalo de nuevo.")
        historial = [m.model_dump() for m in datos.historial]
        return asistente.responder(conexion, datos.pregunta, historial).como_dict()

    # ----- Sesión del panel -----
    @app.post("/api/panel/entrar", dependencies=[Depends(peticion_del_panel)])
    def entrar(datos: Credenciales, request: Request, respuesta: Response, conexion=Depends(db)):
        clave_limite = f"{ip_de(request)}:{datos.correo.lower()}"
        if not limite_login.permitir(clave_limite):
            raise HTTPException(429, "Demasiados intentos. Espera unos minutos.")
        fila = conexion.execute("SELECT * FROM usuarios WHERE correo = ?", (datos.correo.strip().lower(),)).fetchone()
        if not fila or not S.verificar_clave(datos.clave, fila["clave_hash"]):
            raise HTTPException(401, "Correo o contraseña incorrectos.")
        limite_login.reiniciar(clave_limite)
        token = S.abrir_sesion(conexion, fila["id"])
        respuesta.set_cookie(
            COOKIE, token, httponly=True, samesite="strict", secure=config.cookie_segura,
            max_age=int(S.DURACION_SESION.total_seconds()), path="/",
        )
        return {"nombre": fila["nombre"], "rol": fila["rol"], "dependencia": fila["dependencia"]}

    @app.post("/api/panel/salir", dependencies=[Depends(peticion_del_panel)])
    def salir(respuesta: Response, sesion_panel: str | None = Cookie(default=None), conexion=Depends(db)):
        S.cerrar_sesion(conexion, sesion_panel)
        respuesta.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    @app.get("/api/panel/yo")
    def yo(usuario: dict = Depends(usuario_actual)):
        return {
            **usuario,
            "nombre_rol": ROLES[usuario["rol"]],
            "puede_publicar": usuario["rol"] in ("admin", "aprobador"),
            "dependencias": DEPENDENCIAS,
            "tipos": TIPOS,
            "ia": config.ia_activa,
        }

    # ----- Resumen -----
    @app.get("/api/panel/resumen")
    def resumen(usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        conteos = dict(
            conexion.execute(
                """SELECT tipo, COUNT(*) FROM contenidos
                   WHERE estado = 'publicado' AND reemplazado_por IS NULL GROUP BY tipo"""
            ).fetchall()
        )
        return {
            "publicados": conteos,
            "en_revision": conexion.execute(
                "SELECT COUNT(*) FROM contenidos WHERE estado = 'revision' OR pendiente_estado = 'revision'"
            ).fetchone()[0],
            "borradores": conexion.execute(
                "SELECT COUNT(*) FROM contenidos WHERE estado = 'borrador' OR pendiente_estado = 'borrador'"
            ).fetchone()[0],
            "sin_respuesta": conexion.execute("SELECT COUNT(*) FROM sin_respuesta WHERE resuelta = 0").fetchone()[0],
            "preguntas_hoy": leer_metrica(conexion, "preguntas"),
            "llamadas_ia_hoy": leer_metrica(conexion, "llamadas_ia"),
            "tope_ia": config.max_llamadas_ia_dia,
            "ia": config.ia_activa,
        }

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
        tipo: str = "", estado: str = "", dependencia: str = "", q: str = "", pagina: int = Query(1, ge=1),
        usuario: dict = Depends(usuario_actual), conexion=Depends(db),
    ):
        condiciones, valores = ["c.reemplazado_por IS NULL"], []
        if tipo:
            condiciones.append("c.tipo = ?")
            valores.append(tipo)
        if dependencia:
            condiciones.append("c.dependencia = ?")
            valores.append(dependencia)
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
            f"""SELECT c.*, f.nombre AS fuente FROM contenidos c LEFT JOIN fuentes f ON f.id = c.fuente_id
                WHERE {donde}
                ORDER BY (c.estado = 'revision' OR c.pendiente_estado = 'revision') DESC,
                         CASE c.tipo WHEN 'faq' THEN 0 WHEN 'fecha' THEN 1 WHEN 'contacto' THEN 2 ELSE 3 END,
                         c.fuente_id, c.numero, c.id
                LIMIT ? OFFSET ?""",
            [*valores, POR_PAGINA, (pagina - 1) * POR_PAGINA],
        ).fetchall()
        return {"total": total, "por_pagina": POR_PAGINA, "items": [_resumen_fila(f) for f in filas]}

    @app.get("/api/panel/contenidos/{contenido_id}")
    def detalle(contenido_id: int, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        fila = conexion.execute(
            """SELECT c.*, f.nombre AS fuente, f.nota AS fuente_nota FROM contenidos c
               LEFT JOIN fuentes f ON f.id = c.fuente_id WHERE c.id = ?""",
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
                    "capitulo": segmento.capitulo, "numero": segmento.numero,
                },
                usuario,
            )
            creados += 1
        return {"creados": creados}

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
               WHERE v.autor != 'Carga inicial' ORDER BY v.id DESC LIMIT 50"""
        ).fetchall()
        return [dict(f) for f in filas]

    @app.post("/api/panel/probar", dependencies=[Depends(peticion_del_panel)])
    def probar(datos: Pregunta, usuario: dict = Depends(usuario_actual), conexion=Depends(db)):
        """Responde como si todo lo pendiente ya estuviera publicado, sin afectar al público ni a las métricas."""
        historial = [m.model_dump() for m in datos.historial]
        return asistente.responder(conexion, datos.pregunta, historial, prueba=True).como_dict()

    return app


app = crear_app()
