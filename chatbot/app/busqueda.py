"""
Búsqueda sobre el contenido publicado.

Funciona sin servicios externos (BM25 con raíces de palabras en español), así que el asistente sigue
respondiendo aunque la IA falle. Si hay vectores de Cohere, se combinan ambas búsquedas para entender
preguntas escritas con otras palabras.
"""
from __future__ import annotations

import math
import re
from array import array
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache

import snowballstemmer

from .texto import sin_acentos

_lematizador = snowballstemmer.stemmer("spanish")


@lru_cache(maxsize=50_000)
def _raiz_de(palabra: str) -> str:
    return _lematizador.stemWord(palabra)


VACIAS = set(
    """a al algo algun alguna algunas alguno algunos ante antes aqui asi aun cada casi como con cual cuales cualquier
    cuando cuanta cuantas cuanto cuantos de debe deben debo del dentro desde donde dos el ella ellas ello ellos en entre
    era eres es esa esas ese eso esos esta estan estar estas este esto estos estoy fue ha haber hace hacen hacer hacerlo
    hago han hasta hay he hola la las le les lo los mas me mi mis mucho muy nada ni no nos nosotros nuestra nuestro o
    otra otras otro otros para pasa pasar paso pero poder podria podrian poner por porque puede pueden puedo pues que
    quien quiero saber se sea sean segun ser si sido siempre sin sobre soy su sus tambien tan tanto te tener tengo
    tiene tienen toda todas todo todos tu tus un una uno unos usted ustedes va vez veces y ya yo favor gracias
    universidad univalle valle""".split()
)

# Cómo lo dicen los estudiantes -> cómo lo dice la norma.
_SINONIMOS = {
    "materia": ["asignatura"],
    "materias": ["asignatura"],
    "curso": ["asignatura"],
    "cursos": ["asignatura"],
    "clase": ["asignatura"],
    "clases": ["asignatura"],
    "nota": ["calificacion"],
    "notas": ["calificacion"],
    "semestre": ["periodo"],
    "semestres": ["periodo"],
    "retirar": ["cancelar", "cancelacion"],
    "retiro": ["cancelacion"],
    "retirarme": ["cancelacion"],
    "cancelo": ["cancelacion"],
    "repito": ["repeticion"],
    "repetir": ["repeticion"],
    "volver": ["reingreso"],
    "regresar": ["reingreso"],
    "cambiarme": ["traslado"],
    "cambiar": ["traslado"],
    "promedio": ["acumulado"],
    "sancion": ["disciplinaria"],
    "sanciones": ["disciplinaria"],
    "copia": ["fraude"],
    "copiar": ["fraude"],
    "plagio": ["fraude"],
    "tesis": ["trabajo", "grado"],
    "graduarme": ["grado"],
    "graduacion": ["grado"],
    "inscribirme": ["inscripcion"],
    "inscribo": ["inscripcion"],
    "matricularme": ["matricula"],
    "matriculo": ["matricula"],
    "homologar": ["equivalencia"],
    "homologacion": ["equivalencia"],
    "pido": ["solicitar"],
    "pedir": ["solicitar"],
    "tramito": ["solicitar"],
    "tramitar": ["solicitar"],
    "perdi": ["perdida", "reprobar", "repeticion"],
    "perder": ["perdida", "reprobar", "repeticion"],
    "pierdo": ["perdida", "reprobar", "repeticion"],
    "cuesta": ["valor"],
    "vale": ["valor"],
    "plata": ["dinero"],
    # El lematizador no une las formas irregulares del verbo.
    "aprobar": ["aprueba", "aprobacion"],
    "apruebo": ["aprobar", "aprobacion"],
    "costo": ["valor"],
    "precio": ["valor"],
}

# Frases típicas que no se resuelven palabra por palabra. Se aplican sobre el texto sin tildes.
_REESCRITURAS = tuple(
    (re.compile(patron), reemplazo)
    for patron, reemplazo in (
        (r"\bse pasa\b|\bpasar (?:una |la |el )?(?:materia|asignatura|curso|clase)\b", "aprobar asignatura"),
        # La norma dice «asignatura»; «Materias» solo aparece de pasada en un artículo de equivalencias.
        (r"\bmaterias?\b", "asignatura"),
        (r"\bganar (?:una |la |el )?(?:materia|asignatura|curso)\b", "aprobar asignatura"),
        (r"\bcambi\w* de (?:carrera|programa)\b", "traslado de programa"),
        (r"\bcarrera\b", "programa"),
        (r"\bme copie\b|\bcopiarme\b|\bhacer trampa\b|\bhice trampa\b", "fraude examen"),
        (r"\b(?:cancelar|retirarme de?l?) (?:el |del )?semestre\b", "cancelar semestre matricula"),
        (r"\bme fue (?:muy )?mal\b", "bajo rendimiento academico"),
        (r"\bme (?:saquen|sacan|echen|echan)\b|\bme (?:pueden?|van a) (?:sacar|echar)\b", "bajo rendimiento academico"),
        (r"\bexamen para no (?:tener que )?(?:ver|cursar|tomar)\b", "validar"),
    )
)

_PESO_SINONIMO = 0.7
_PESOS_CAMPO = (("titulo", 3), ("capitulo", 2), ("texto", 1))
# La primera frase de un artículo suele decir de qué trata: pesa más que el resto.
_LARGO_ENTRADA = 140
_PESO_ENTRADA = 2
_K1 = 1.2
_B = 0.55
_RRF = 60
_PESO_VECTORES = 2


@dataclass
class Documento:
    id: int
    tipo: str
    titulo: str
    texto: str
    dependencia: str = ""
    capitulo: str = ""
    numero: int | None = None
    fuente: str = ""
    url: str = ""
    inicio: str | None = None
    fin: str | None = None
    destacada: bool = False
    borrador: bool = False


@dataclass
class Resultado:
    documento: Documento
    puntaje: float
    cobertura: float
    similitud: float = 0.0  # Parecido de significado según los vectores; 0 si no hay IA.


def raices(texto: str) -> list[str]:
    palabras = re.findall(r"[a-z0-9]+", sin_acentos(texto.lower()))
    return [_raiz_de(p) for p in palabras if p not in VACIAS and len(p) > 1]


def _grupos(consulta: str) -> list[tuple[str, ...]]:
    """Cada palabra de la consulta con sus equivalentes en el lenguaje de la norma."""
    grupos: list[tuple[str, ...]] = []
    vistos: set[str] = set()
    texto = sin_acentos(consulta.lower())
    for patron, reemplazo in _REESCRITURAS:
        texto = patron.sub(reemplazo, texto)
    for palabra in re.findall(r"[a-z0-9]+", texto):
        if palabra in VACIAS or len(palabra) < 2:
            continue
        principal = _raiz_de(palabra)
        if principal in vistos:
            continue
        vistos.add(principal)
        grupos.append((principal, *(_raiz_de(s) for s in _SINONIMOS.get(palabra, []))))
    return grupos


def numero_de_articulo(consulta: str) -> int | None:
    coincide = re.search(r"\bart[ií]?c?u?l?o?\.?\s*(\d{1,3})\b", consulta.lower())
    return int(coincide.group(1)) if coincide else None


class Indice:
    def __init__(self, documentos: list[Documento], vectores: dict[int, array] | None = None):
        self.documentos = documentos
        self.vectores = vectores or {}
        self._frecuencias: list[Counter[str]] = []
        self._largos: list[float] = []
        presencia: Counter[str] = Counter()
        for doc in documentos:
            frecuencia: Counter[str] = Counter()
            for campo, peso in _PESOS_CAMPO:
                for raiz in raices(getattr(doc, campo) or ""):
                    frecuencia[raiz] += peso
            for raiz in raices(doc.texto[:_LARGO_ENTRADA]):
                frecuencia[raiz] += _PESO_ENTRADA
            self._frecuencias.append(frecuencia)
            self._largos.append(sum(frecuencia.values()))
            presencia.update(frecuencia.keys())
        self._total = max(1, len(documentos))
        self._largo_medio = (sum(self._largos) / self._total) or 1.0
        self._idf = {t: math.log(1 + (self._total - n + 0.5) / (n + 0.5)) for t, n in presencia.items()}
        self._idf_maximo = math.log(1 + (self._total + 0.5) / 0.5)

    def _idf_de(self, raiz: str) -> float:
        return self._idf.get(raiz, self._idf_maximo)

    def _bm25(self, grupos: list[tuple[str, ...]], indice: int) -> float:
        frecuencia = self._frecuencias[indice]
        normal = 1 - _B + _B * self._largos[indice] / self._largo_medio
        total = 0.0
        for grupo in grupos:
            mejor = 0.0
            for posicion, raiz in enumerate(grupo):
                tf = frecuencia.get(raiz, 0)
                if tf:
                    valor = self._idf_de(raiz) * tf * (_K1 + 1) / (tf + _K1 * normal)
                    mejor = max(mejor, valor * (_PESO_SINONIMO if posicion else 1.0))
            total += mejor
        return total

    def _cobertura(self, grupos: list[tuple[str, ...]], indice: int) -> float:
        """
        Qué parte de la pregunta aparece en el documento (0 a 1). Promedia dos medidas: la importancia de las
        palabras halladas y cuántas son, para que una sola palabra rara no baste para dar por buena una respuesta.
        """
        frecuencia = self._frecuencias[indice]
        pesos = [max(self._idf_de(r) for r in grupo) for grupo in grupos]
        if not sum(pesos):
            return 0.0
        aciertos = [any(r in frecuencia for r in grupo) for grupo in grupos]
        por_importancia = sum(p for p, acierto in zip(pesos, aciertos) if acierto) / sum(pesos)
        return (por_importancia + sum(aciertos) / len(grupos)) / 2

    def conoce_algo(self, consulta: str) -> bool:
        """Si alguna palabra de la pregunta existe en lo publicado: distingue una duda real de un tema ajeno."""
        return any(r in self._idf for grupo in _grupos(consulta) for r in grupo)

    def parecido_pregunta(self, consulta: str, pregunta_guardada: str) -> float:
        """Parecido entre dos preguntas (0 a 1), dando más valor a las palabras poco comunes."""
        grupos = _grupos(consulta)
        objetivo = set(raices(pregunta_guardada))
        if not grupos or not objetivo:
            return 0.0
        pesos = [max(self._idf_de(r) for r in grupo) for grupo in grupos]
        precision = sum(p for p, g in zip(pesos, grupos) if any(r in objetivo for r in g)) / sum(pesos)
        cubiertas = {r for g in grupos for r in g}
        exhaustividad = sum(self._idf_de(r) for r in objetivo & cubiertas) / sum(self._idf_de(r) for r in objetivo)
        return 0.7 * precision + 0.3 * exhaustividad

    def buscar(self, consulta: str, limite: int = 6, contexto: str = "", vector: array | None = None) -> list[Resultado]:
        """`contexto` es la pregunta anterior: ayuda con seguimientos como «¿y si es la tercera vez?»."""
        grupos = _grupos(consulta)
        grupos_contexto = [g for g in _grupos(contexto) if g[0] not in {x[0] for x in grupos}] if contexto else []
        numero = numero_de_articulo(consulta)
        if not self.documentos or not (grupos or numero):
            return []

        puntajes: dict[int, float] = {}
        for i in range(len(self.documentos)):
            valor = self._bm25(grupos, i) + 0.5 * self._bm25(grupos_contexto, i)
            if valor > 0:
                puntajes[i] = valor
        if numero is not None:
            for i, doc in enumerate(self.documentos):
                if doc.tipo == "articulo" and doc.numero == numero:
                    puntajes[i] = puntajes.get(i, 0) + 100

        orden = sorted(puntajes, key=puntajes.get, reverse=True)
        similitudes: dict[int, float] = {}
        if vector is not None and self.vectores:
            orden, similitudes = self._fusionar(orden, vector)

        resultados = []
        for i in orden[:limite]:
            cobertura = self._cobertura(grupos + grupos_contexto, i) if grupos else 1.0
            if numero is not None and self.documentos[i].numero == numero:
                cobertura = 1.0
            resultados.append(Resultado(self.documentos[i], puntajes.get(i, 0.0), cobertura, similitudes.get(i, 0.0)))
        return resultados

    def _fusionar(self, orden_palabras: list[int], vector: array) -> tuple[list[int], dict[int, float]]:
        """Combina los dos rankings con fusión recíproca: no hay que calibrar escalas distintas."""
        similitudes: dict[int, float] = {}
        for i, doc in enumerate(self.documentos):
            propio = self.vectores.get(doc.id)
            if propio is not None:
                similitudes[i] = sum(a * b for a, b in zip(vector, propio))
        orden_vectores = sorted(similitudes, key=similitudes.get, reverse=True)[:30]
        fusion: Counter[int] = Counter()
        # El significado pesa más: palabras comunes como «semestre» traían artículos de otros temas.
        for orden, peso in ((orden_palabras, 1), (orden_vectores, _PESO_VECTORES)):
            for posicion, i in enumerate(orden):
                fusion[i] += peso / (_RRF + posicion)
        return [i for i, _ in fusion.most_common()], similitudes
