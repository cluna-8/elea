"""Detector de secretos — llaves OpenAI actuales (sk-proj-, sk-svcacct-, sk-admin-) y criterio único en los dos caminos (057 R38).

Hallazgo: la capa del motor (`SECRET_PATTERNS`, `sk-[a-zA-Z0-9]{10,}`) no veía las llaves modernas: `sk-proj-…` lleva un guion tras
`proj`, así que no hay diez alfanuméricos seguidos. El camino del backend (`GuardianService`, `sk-(?:proj-)?[A-Za-z0-9_-]{20,}`) sí las
veía, pero sin límite izquierdo: `task-implementation-of-the-risk-assessment` (…`sk-` + 20 caracteres con guiones) era «clave».

Fija, en AMBOS caminos con el mismo criterio: (a) las llaves modernas se detectan (se generan acá, nunca son reales); (b) `task-…`,
`ask-…`, `desk-…` y similares, aun largas y con guiones, no; (c) las llaves viejas `sk-<alfanumérico>` y toda detección previa siguen.
"""
import random

import pytest

from s14_helpers import policy  # noqa: E402
from src.models.guardian import Guardian
from src.services import guardian_service

_ALFABETO = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
_ALFABETO_B64URL = _ALFABETO + "-_"


def _cuerpo(semilla, largo, alfabeto=_ALFABETO_B64URL):
    """Cuerpo pseudoaleatorio determinista (sin secretos reales); empieza y termina alfanumérico como las llaves emitidas."""
    r = random.Random(semilla)
    cuerpo = [r.choice(alfabeto) for _ in range(largo)]
    cuerpo[0] = r.choice(_ALFABETO)
    cuerpo[-1] = r.choice(_ALFABETO)
    return "".join(cuerpo)


LLAVES_MODERNAS = {
    "proj": "sk-proj-" + _cuerpo(1, 156),
    "proj-corta": "sk-proj-" + _cuerpo(2, 48),
    "svcacct": "sk-svcacct-" + _cuerpo(3, 150),
    "admin": "sk-admin-" + _cuerpo(4, 120),
    "proj-con-marca": "sk-proj-" + _cuerpo(5, 60) + "T3BlbkFJ" + _cuerpo(6, 60),
}
LLAVES_VIEJAS = ["sk-" + _cuerpo(7, 48, _ALFABETO), "sk-" + "A1b2C3d4E5" * 4, "sk-abcdefghij", "sk-abcdefghij1234567890"]
OTRAS_DETECCIONES = [  # lo que algún camino ya detectaba: no puede bajar
    "sk-ant-api03-" + _cuerpo(8, 90),          # el camino del backend la veía (guiones, 20+)
    "sk-" + "a1b2_c3d4-" * 3,                   # idem, con guion bajo
    "mi-clave-sk-" + _cuerpo(9, 40, _ALFABETO),  # tras un guion: no es letra ni dígito
    "_sk-" + _cuerpo(10, 40, _ALFABETO),
]
PALABRAS_CORRIENTES = [
    "task-implementation", "ask-clarification-questions", "desk-reservations", "risk-assessment", "disk-partitioning",
    "task-implementation-of-the-risk-assessment-framework", "ask-clarification-questions-before-you-continue-working",
    "desk-reservation-and-room-scheduling-for-the-whole-team", "high-risk-assessments-and-mitigations-for-every-release",
    "Use a sub-agent for each task-specific-analysis-of-the-codebase", "TASK-IMPLEMENTATION-OF-THE-RISK-ASSESSMENT",
    "mask-generation-and-disk-partitioning-pipeline-for-the-batch-jobs", "task_force-task-implementation-details-and-more",
]
PLANTILLAS = ["{k}", " {k}", "{k} al final", "OPENAI_API_KEY={k}", "api_key: {k}", 'key="{k}"', "(clave {k})", "línea 1\n{k}\nlínea 3",
              "Authorization: Bearer {k}", "usá {k}, por favor", "`{k}`", "https://host/?key={k}"]


# ---- camino del motor ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("plantilla", PLANTILLAS)
@pytest.mark.parametrize("llave", LLAVES_MODERNAS.values(), ids=LLAVES_MODERNAS.keys())
def test_motor_detecta_llave_moderna(plantilla, llave):
    assert "OpenAI API Key" in policy.detect_secrets(plantilla.format(k=llave))


@pytest.mark.parametrize("texto", PALABRAS_CORRIENTES)
def test_motor_no_detecta_palabra_corriente(texto):
    assert policy.detect_secrets(texto) == []
    assert policy.detect_secrets(f"antes {texto} después") == []


@pytest.mark.parametrize("llave", LLAVES_VIEJAS + OTRAS_DETECCIONES)
def test_motor_detecta_viejas_y_deteccion_previa(llave):
    assert "OpenAI API Key" in policy.detect_secrets(f"clave {llave} fin")


def test_motor_redacta_la_llave_moderna_completa():
    for llave in LLAVES_MODERNAS.values():
        redactado = policy.redact_secrets(f"clave {llave} fin")
        assert redactado == "clave [SECRET_REDACTED] fin"


# ---- camino del backend -------------------------------------------------------------------------------------------------------
class _Consulta:
    def __init__(self, filas):
        self._filas = filas

    def all(self):
        return self._filas

    def filter(self, *_a, **_k):
        return _Consulta([g for g in self._filas if g.guardian_type == "pii_masking"])

    def first(self):
        return self._filas[0] if self._filas else None


class _Sesion:
    def __init__(self, filas):
        self._filas = filas

    def query(self, *_a, **_k):
        return _Consulta(self._filas)

    def commit(self):
        pass


def _guardianes(accion):
    secreto = Guardian(name="Filtro de Secretos", guardian_type="secret_detection", is_active=True, config={"action": accion})
    pii = Guardian(name="PII", guardian_type="pii_masking", is_active=False,
                   config={"custom_names": [], "entities": ["PERSON", "ES_NIF"], "action": "MASK"})
    rellenos = [Guardian(name=f"f{i}", guardian_type=f"filler_{i}", is_active=False, config={}) for i in range(7)]
    return [secreto, pii, *rellenos]


async def _procesar(prompt, accion="BLOCK"):
    return await guardian_service.GuardianService.process_prompt(_Sesion(_guardianes(accion)), prompt, selected_model="gpt-4o")


@pytest.mark.asyncio
@pytest.mark.parametrize("plantilla", PLANTILLAS)
@pytest.mark.parametrize("llave", LLAVES_MODERNAS.values(), ids=LLAVES_MODERNAS.keys())
async def test_backend_detecta_llave_moderna(plantilla, llave):
    assert (await _procesar(plantilla.format(k=llave)))["blocked"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("texto", PALABRAS_CORRIENTES)
async def test_backend_no_detecta_palabra_corriente(texto):
    assert (await _procesar(f"antes {texto} después"))["blocked"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("llave", LLAVES_VIEJAS + OTRAS_DETECCIONES)
async def test_backend_detecta_viejas_y_deteccion_previa(llave):
    assert (await _procesar(f"clave {llave} fin"))["blocked"] is True


@pytest.mark.asyncio
async def test_backend_redacta_la_llave_moderna_completa():
    for llave in LLAVES_MODERNAS.values():
        resultado = await _procesar(f"clave {llave} fin", accion="REDACT")
        assert llave[:12] not in resultado["prompt"], resultado["prompt"]
        assert resultado["prompt"] == "clave [SECRETO_REDACTADO] fin"


# ---- criterio único -----------------------------------------------------------------------------------------------------------
def test_un_solo_criterio_en_los_dos_caminos():
    assert guardian_service.OPENAI_KEY_PATTERN == policy.SECRET_PATTERNS["OpenAI API Key"]
