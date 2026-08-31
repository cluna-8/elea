"""Generador determinista de corpus PII español (spec 035, T006, #107).

Emite documentos conformes a ``contracts/corpus-format.md``: spans en CODEPOINTS
Unicode sobre texto NFC, ``end`` exclusivo, ``value == text[start:end]``, y
``entity_type`` del enum cerrado del baseline eu. Los valores estructurados
(NIF/NIE/IBAN/tarjeta) llevan checksum válido y los teléfonos matchean el patrón
nacional español — de modo que los reconocedores REALES del producto los detectan
(oráculo en ``oracle.py``).

DETERMINISMO (US3 comparabilidad): misma semilla → mismo corpus byte a byte. Se usa
un ``random.Random(seed)`` LOCAL; nunca el random global, ni ``time``/``uuid``. No se
añaden dependencias externas (Faker/python-stdnum): los pools son fijos y versionados
y los checksums viven en ``oracle.py`` — así el ``sha256`` del dataset es reproducible
en cualquier máquina, sin datos de terceros que cambien entre versiones (ver reporte).
"""
from __future__ import annotations

import random
import unicodedata
from typing import Optional

from . import oracle

# Versión del generador — viaja en el manifest (corpus-format.md regla 7). Bump si
# cambian los pools o el algoritmo de ensamblado (el sha256 del dataset cambiaría).
# 1.1.0: dominio de ejemplo (FIX-C1), +prosa limpia (FIX-C2), PASSPORT excluye NIF/NIE
# en el mismo doc (FIX-C4).
GENERATOR_VERSION = "1.1.0"

# ── Pools sintéticos es-ES (100% inventados; cero datos reales — regla 9) ──────────

_NOMBRES = [
    "Laura", "María", "Carlos", "Javier", "Ana", "Miguel", "Lucía", "Pablo",
    "Elena", "Sergio", "Marta", "David", "Cristina", "Alberto", "Raquel",
    "Fernando", "Isabel", "Andrés", "Nuria", "Gonzalo",
]
_APELLIDOS = [
    "Martínez", "Gómez", "Cifuentes", "Navarro", "Fernández", "López", "Ruiz",
    "Sánchez", "Romero", "Torres", "Vidal", "Molina", "Serrano", "Ortega",
    "Castro", "Delgado", "Ibáñez", "Herrera", "Peña", "Vázquez",
]
# FIX-C1 (GDPR, #107): NUNCA un dominio real de cliente. Un dominio con buzones vivos
# haría que un local-part sintético pudiera chocar con una persona real (dato personal).
# Todos los dominios de abajo son claramente de ejemplo/inválidos (regla 9 del contrato).
_DOMINIOS = [
    "camara-ejemplo.es", "gestoria-ejemplo.es", "correo-ficticio.com",
    "mail-demo.es", "empresa-test.es", "notaria-ejemplo.com",
]
_CALLES = [
    ("Calle", "Mayor"), ("Avenida", "del Puerto"), ("Calle", "Colón"),
    ("Plaza", "del Ayuntamiento"), ("Calle", "de la Paz"), ("Avenida", "Blasco Ibáñez"),
    ("Calle", "San Vicente"), ("Ronda", "Norte"), ("Calle", "de las Flores"),
]
_CIUDADES = [
    ("Valencia", "460"), ("Madrid", "280"), ("Barcelona", "080"),
    ("Sevilla", "410"), ("Zaragoza", "500"), ("Bilbao", "480"),
    ("Alicante", "030"), ("Castellón", "120"),
]
_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
]
_BANCOS = ["2100", "0049", "0075", "0182", "1465", "2038", "0081", "0128"]

# Frases de contexto por tipo — dan al detector NER/regex el entorno realista y
# separan las entidades entre sí (evita solapes accidentales entre reconocedores).
_INTROS = [
    "Datos del expediente. ",
    "Le confirmo los datos de la ficha del cliente. ",
    "Adjunto la información para la gestión solicitada. ",
    "Resumen de la solicitud registrada en la Cámara. ",
    "Por favor, verifique los siguientes datos de contacto. ",
]

# Documentos limpios (densidad 0): prosa administrativa SIN PII alguna. FIX-C2: la
# tasa de falsos positivos global se mide sobre estos textos, así que deben ser
# GENUINAMENTE distintos (no 6 plantillas reusadas ×10). Ninguno contiene nombres,
# fechas, direcciones, importes con pinta de PII ni identificadores.
_CLEAN_TEXTS = [
    "Confirmamos la recepción de su solicitud. El expediente sigue el curso habitual "
    "y le avisaremos cuando haya novedades.",
    "El horario de atención al público es de lunes a viernes por la mañana. Gracias "
    "por su paciencia durante el periodo de tramitación.",
    "La documentación aportada cumple los requisitos formales. No se requiere "
    "información adicional por el momento.",
    "Le recordamos que la próxima reunión de la comisión tratará el plan anual. El "
    "orden del día se publicará con antelación.",
    "El importe de la tasa se ha calculado según la ordenanza vigente. Puede consultar "
    "el desglose en la sede electrónica.",
    "Agradecemos su colaboración en el proceso de mejora del servicio. Sus comentarios "
    "se han trasladado al departamento correspondiente.",
    "El servicio de asesoramiento permanecerá cerrado durante el periodo estival. "
    "Reanudaremos la atención habitual al término de las vacaciones.",
    "Su consulta ha sido derivada al área competente. Recibirá una respuesta motivada "
    "una vez completado el estudio del asunto planteado.",
    "Recuerde que puede descargar los formularios desde el portal. La presentación "
    "telemática agiliza notablemente los plazos de resolución.",
    "El pleno aprobó por unanimidad las líneas generales del presupuesto. El detalle "
    "quedará a disposición de los interesados en los próximos boletines.",
    "Para cualquier incidencia técnica con la plataforma, existe un formulario de "
    "soporte que canaliza las peticiones al equipo de sistemas.",
    "La comisión de seguimiento valorará el grado de cumplimiento de los objetivos "
    "y elevará sus conclusiones al órgano de gobierno.",
    "Le informamos de que el trámite no conlleva coste alguno. La verificación de los "
    "requisitos se realiza de oficio por la unidad correspondiente.",
    "Los cursos de formación cubrirán aspectos prácticos de la gestión administrativa. "
    "Las plazas se asignarán por riguroso orden de inscripción.",
    "El archivo de documentación se conserva conforme a la política de retención "
    "aprobada. Transcurrido el plazo, se procede a su depuración ordenada.",
    "Agradecemos las sugerencias recibidas durante la fase de consulta pública. Han "
    "sido incorporadas al informe que acompaña a la propuesta final.",
    "La sede permanecerá operativa con normalidad durante las obras de mejora. Se ruega "
    "disculpar las molestias que puedan derivarse de los trabajos.",
    "El boletín mensual resume las principales actuaciones del periodo. Puede suscribirse "
    "para recibir las novedades directamente en su bandeja de entrada.",
]


class _DocBuilder:
    """Ensambla un documento registrando spans en codepoints por construcción.

    Cada segmento se normaliza a NFC ANTES de apendarse; como los separadores son
    ASCII (nunca combinan), la concatenación de segmentos NFC permanece NFC. El
    invariante ``value == text[start:end]`` se garantiza al insertar (y se re-verifica
    en ``build``).
    """

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._pos = 0  # offset en codepoints
        self.entities: list[dict] = []
        self.forbidden: list[dict] = []

    def add_text(self, s: str) -> None:
        s = unicodedata.normalize("NFC", s)
        if s:
            self._parts.append(s)
            self._pos += len(s)

    def add_entity(self, value: str, entity_type: str, *, span: Optional[tuple] = None) -> None:
        """Inserta ``value``; ``span`` acota qué sub-tramo se etiqueta (el resto queda
        como contexto sin etiquetar — p.ej. el prefijo "+34 " de un teléfono, que el
        reconocedor nacional no captura)."""
        value = unicodedata.normalize("NFC", value)
        lo, hi = (0, len(value)) if span is None else span
        self.add_text(value[:lo])
        start = self._pos
        core = value[lo:hi]
        self._parts.append(core)
        self._pos += len(core)
        self.entities.append({
            "entity_type": entity_type, "start": start, "end": self._pos, "value": core,
        })
        self.add_text(value[hi:])

    def add_forbidden(self, value: str, entity_type: str, *, with_value: bool = True) -> None:
        """Inserta un hard-negative: un tramo que NO debe detectarse como
        ``entity_type`` (p.ej. un código interno FAC-2026-* que el dev-regex confundía
        con teléfono — la regresión literal del #63)."""
        value = unicodedata.normalize("NFC", value)
        start = self._pos
        self._parts.append(value)
        self._pos += len(value)
        entry = {"entity_type": entity_type, "start": start, "end": self._pos}
        if with_value:
            entry["value"] = value
        self.forbidden.append(entry)

    def build(self, doc_id: str, source: str, difficulty: str,
              region: str = "eu") -> dict:
        text = "".join(self._parts)
        # Invariantes duros del contrato (regla 2/3): NFC y checksum de value.
        assert unicodedata.normalize("NFC", text) == text, f"{doc_id}: texto no-NFC"
        for e in self.entities:
            assert text[e["start"]:e["end"]] == e["value"], f"{doc_id}: span roto"
        doc = {
            "id": doc_id,
            "text": text,
            "entities": self.entities,
            "source": source,
            "difficulty": difficulty,
            "lang": "es",
            "region": region,
        }
        if self.forbidden:
            doc["forbidden"] = self.forbidden
        return doc


# ── Generadores de valores (deterministas: reciben el rng local) ──────────────────

def _gen_person(rng: random.Random) -> tuple[str, str]:
    nombre = rng.choice(_NOMBRES)
    n_ap = rng.choice([1, 2, 2])  # sesgo a 2 apellidos (típico español)
    apellidos = " ".join(rng.sample(_APELLIDOS, n_ap))
    return f"{nombre} {apellidos}", "PERSON"


def _ascii_fold(s: str) -> str:
    """Sin tildes ni ñ → ASCII (los local-parts de email no llevan acentos)."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def _gen_email(rng: random.Random) -> tuple[str, str]:
    nombre = _ascii_fold(rng.choice(_NOMBRES).lower())
    ap = _ascii_fold(rng.choice(_APELLIDOS).lower())
    sep = rng.choice([".", "_", ""])
    dominio = rng.choice(_DOMINIOS)
    return f"{nombre}{sep}{ap}@{dominio}", "EMAIL_ADDRESS"


def _gen_phone(rng: random.Random) -> tuple[str, str, tuple]:
    prefijo = rng.choice(["+34 ", "0034 ", "", ""])
    primero = rng.choice("6789")  # móvil 6/7, fijo 8/9
    resto = "".join(rng.choice("0123456789") for _ in range(8))
    digitos = primero + resto
    estilo = rng.choice(["3-3-3", "3-2-2-2"])
    if estilo == "3-3-3":
        nacional = f"{digitos[0:3]} {digitos[3:6]} {digitos[6:9]}"
    else:
        nacional = f"{digitos[0:3]} {digitos[3:5]} {digitos[5:7]} {digitos[7:9]}"
    display = prefijo + nacional
    # El reconocedor nacional NO captura el prefijo "+34 " (el \b falla en '+'):
    # etiquetamos exactamente lo que matchea el oráculo.
    m = oracle.PHONE_RE.search(display)
    return display, "PHONE_NUMBER", m.span()


def _gen_nif(rng: random.Random) -> tuple[str, str]:
    numero = f"{rng.randint(0, 99999999):08d}"
    return numero + oracle.nif_control_letter(numero), "ES_NIF"


def _gen_nie(rng: random.Random) -> tuple[str, str]:
    prefijo = rng.choice("XYZ")
    siete = f"{rng.randint(0, 9999999):07d}"
    return prefijo + siete + oracle.nie_control_letter(prefijo, siete), "ES_NIE"


def _gen_iban(rng: random.Random) -> tuple[str, str]:
    bank = rng.choice(_BANCOS)
    branch = f"{rng.randint(0, 9999):04d}"
    account = f"{rng.randint(0, 9999999999):010d}"
    compact = oracle.build_iban_es(bank, branch, account)
    # Agrupado de 4 en 4 (formato humano habitual; Presidio lo detecta igual).
    grouped = " ".join(compact[i:i + 4] for i in range(0, len(compact), 4))
    return grouped, "IBAN_CODE"


def _gen_card(rng: random.Random) -> tuple[str, str]:
    prefijo = rng.choice(["4", "51", "52", "53", "54", "55"])  # Visa / Mastercard
    cuerpo = prefijo + "".join(rng.choice("0123456789") for _ in range(15 - len(prefijo)))
    numero = cuerpo + str(oracle.luhn_check_digit(cuerpo))
    grouped = " ".join(numero[i:i + 4] for i in range(0, 16, 4))
    return grouped, "CREDIT_CARD"


def _gen_passport(rng: random.Random) -> tuple[str, str]:
    letras = "".join(rng.choice("ABCDEFGHJKLMNPRSTVWXYZ") for _ in range(3))
    digitos = "".join(rng.choice("0123456789") for _ in range(6))
    return letras + digitos, "PASSPORT"  # 9 alfanum, dentro de [A-Z0-9]{6,9}


def _gen_location(rng: random.Random) -> tuple[str, str]:
    tipo, nombre = rng.choice(_CALLES)
    numero = rng.randint(1, 180)
    ciudad, cp_pref = rng.choice(_CIUDADES)
    cp = cp_pref + f"{rng.randint(0, 99):02d}"
    return f"{tipo} {nombre} {numero}, {cp} {ciudad}", "LOCATION"


def _gen_datetime(rng: random.Random) -> tuple[str, str]:
    dia = rng.randint(1, 28)
    mes = rng.randint(1, 12)
    anio = rng.randint(2019, 2026)
    if rng.random() < 0.5:
        return f"{dia:02d}/{mes:02d}/{anio}", "DATE_TIME"
    return f"{dia} de {_MESES[mes - 1]} de {anio}", "DATE_TIME"


# Registro de tipos "simples" (valor completo = entidad) y sus frases de contexto.
_SIMPLE_GENERATORS = {
    "PERSON": (_gen_person, "El titular es {v}. "),
    "EMAIL_ADDRESS": (_gen_email, "Correo de contacto: {v}. "),
    "ES_NIF": (_gen_nif, "NIF: {v}. "),
    "ES_NIE": (_gen_nie, "NIE del solicitante: {v}. "),
    "IBAN_CODE": (_gen_iban, "Domiciliación en el IBAN {v}. "),
    "CREDIT_CARD": (_gen_card, "Tarjeta de pago {v}. "),
    "PASSPORT": (_gen_passport, "Número de pasaporte {v}. "),
    "LOCATION": (_gen_location, "Domicilio: {v}. "),
    "DATE_TIME": (_gen_datetime, "Fecha de la operación: {v}. "),
}
# Orden estable de tipos elegibles por doc (el teléfono se maneja aparte por el span).
_ENTITY_MENU = list(_SIMPLE_GENERATORS.keys()) + ["PHONE_NUMBER"]

# FIX-C4: identificadores personales de 6-9 alfanuméricos que el scoring exact-span del
# core NO puede desambiguar si conviven en el mismo texto (PASSPORT `[A-Z0-9]{6,9}` se
# solapa con NIF/NIE de 9 chars). Se admite A LO SUMO UNO de este grupo por documento.
_EXCLUSIVE = ("ES_NIF", "ES_NIE", "PASSPORT")


def _sample_types(rng: random.Random, density: int) -> list[str]:
    """Elige ``density`` tipos con a lo sumo un miembro de ``_EXCLUSIVE`` (FIX-C4).

    Determinista sobre ``rng``. Sin repetición mientras alcancen los tipos no
    excluyentes (7); solo repite no-excluyentes si la densidad supera el catálogo.
    """
    otros = [t for t in _ENTITY_MENU if t not in _EXCLUSIVE]  # 7 tipos
    tipos: list[str] = []
    # ¿incluir un identificador del grupo excluyente? Obligatorio si no hay otros
    # suficientes para llenar la densidad.
    if density >= 1 and (rng.random() < 0.5 or density > len(otros)):
        tipos.append(rng.choice(_EXCLUSIVE))
    faltan = density - len(tipos)
    if faltan <= len(otros):
        tipos += rng.sample(otros, faltan)
    else:  # densidad mayor que el catálogo no-excluyente: repetimos no-excluyentes
        tipos += [rng.choice(otros) for _ in range(faltan)]
    rng.shuffle(tipos)
    return tipos


def _difficulty_for(density: int) -> str:
    if density <= 1:
        return "easy"
    if density <= 3:
        return "medium"
    return "hard"


def _make_doc(rng: random.Random, idx: int, density: int, seed: int, region: str) -> dict:
    b = _DocBuilder()
    doc_id = f"gen-{seed}-{idx:04d}"
    if density == 0:
        b.add_text(rng.choice(_CLEAN_TEXTS))
        return b.build(doc_id, "generated", "easy", region)

    b.add_text(rng.choice(_INTROS))
    tipos = _sample_types(rng, density)  # a lo sumo un ID excluyente por doc (FIX-C4)

    for tipo in tipos:
        if tipo == "PHONE_NUMBER":
            display, _t, span = _gen_phone(rng)
            b.add_text("Teléfono de contacto: ")
            b.add_entity(display, "PHONE_NUMBER", span=span)
            b.add_text(". ")
            continue
        gen, plantilla = _SIMPLE_GENERATORS[tipo]
        value, etype = gen(rng)
        pre, post = plantilla.split("{v}", 1)
        b.add_text(pre)
        b.add_entity(value, etype)
        b.add_text(post)

    return b.build(doc_id, "generated", _difficulty_for(density), region)


def _density_plan(n_docs: int, densities: dict[int, float]) -> list[int]:
    """Reparte ``n_docs`` documentos entre las densidades según sus pesos relativos."""
    if not densities:
        raise ValueError("densities no puede estar vacío")
    total_w = sum(densities.values())
    if total_w <= 0:
        raise ValueError("los pesos de densities deben sumar > 0")
    plan: list[int] = []
    for dens, w in sorted(densities.items()):
        plan += [dens] * round((w / total_w) * n_docs)
    # Ajuste exacto a n_docs (relleno/recorte con la densidad de mayor peso).
    dominante = max(sorted(densities.items()), key=lambda kv: kv[1])[0]
    while len(plan) < n_docs:
        plan.append(dominante)
    return plan[:n_docs]


def generate(seed: int, n_docs: int, densities: dict[int, float],
             region: str = "eu") -> list[dict]:
    """Genera ``n_docs`` documentos deterministas conformes al contrato.

    Args:
        seed: semilla del RNG local — misma semilla → mismo corpus byte a byte.
        n_docs: número de documentos a emitir.
        densities: mapa ``{entidades_por_doc: peso_relativo}``; densidad 0 = doc limpio
            (``entities: []``). Ej.: ``{0: 1}`` → todos limpios; ``{4: 1}`` → todos con
            4 entidades.
        region: región del baseline (por ahora solo ``"eu"``).
    """
    if region != "eu":
        raise ValueError(f"región no soportada por el baseline: {region!r}")
    rng = random.Random(seed)
    plan = _density_plan(n_docs, densities)
    rng.shuffle(plan)
    return [_make_doc(rng, i, dens, seed, region) for i, dens in enumerate(plan)]
