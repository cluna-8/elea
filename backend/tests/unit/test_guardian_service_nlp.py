"""El plano panel/playground tampoco degrada en silencio (issue #63, `process_prompt`).

Este plano es el que MENOS riesgo tenía —es interno, no es tráfico de producción hacia
herramientas (spec 016 Assumptions)— y aun así arrastraba dos silencios:

1. Cuando el motor NLP estaba configurado y se caía, el trigger `DEGRADED` aparecía en la
   respuesta de ESE prompt y desaparecía con el siguiente. Un operador que mirara el estado
   media hora después no tenía forma de saber que el detector real estuvo caído.
2. Cuando NO había motor configurado, el playground corría con el regex de dev y NO lo decía
   en ningún lado: la pantalla mostraba un enmascarado exitoso sin distinguir con qué. Es la
   pantalla donde un humano decide si el producto "detecta bien" — y estaba juzgando al
   detector equivocado.

El playground SIGUE degradando (no se le aplica el fail-closed del tráfico real: es una
herramienta interna y bloquearla no protege a nadie). Lo que cambia es que ya no es mudo.
"""
import pytest

from src.services import guardian_service
from src.services.guardian_service import GuardianService
from src.services.presidio_service import NlpUnavailableError

ANALYZER = "http://nlp-analyzer:3000"
PROMPT = "escribile a maria.lopez@camara.es sobre el expediente"


class _GuardianFalso:
    def __init__(self, guardian_type, config=None, is_active=True):
        self.guardian_type = guardian_type
        self.config = config or {}
        self.is_active = is_active
        self.name = f"guardián {guardian_type}"
        self.engine_guardrail_name = None


@pytest.fixture(autouse=True)
def catalogo(monkeypatch):
    """Sólo el guardián PII activo: el resto del catálogo no participa de este camino."""
    guardianes = [_GuardianFalso("pii_masking", {"entities": ["EMAIL_ADDRESS", "PERSON"],
                                                 "action": "MASK", "custom_names": []})]
    monkeypatch.setattr(GuardianService, "get_or_create_default_guardians",
                        staticmethod(lambda db: guardianes))
    return guardianes


@pytest.fixture
def marcas(monkeypatch):
    """Espía del registro durable de la degradación."""
    registro = []
    monkeypatch.setattr(guardian_service, "record_nlp_degradation",
                        lambda reason="": registro.append(reason))
    return registro


def _degradados(resultado):
    return [t for t in resultado["triggers"] if t["action"] == "DEGRADED"]


@pytest.mark.asyncio
async def test_sin_url_configurada_el_trigger_es_visible(monkeypatch, marcas):
    """Antes: enmascaraba con regex y no lo decía. Ahora la pantalla declara con qué detector
    trabajó — la diferencia de cobertura es real y la lee el mismo humano que evalúa si el
    producto sirve."""
    monkeypatch.delenv("NLP_ANALYZER_URL", raising=False)

    resultado = await GuardianService.process_prompt(None, PROMPT, "modelo-x")

    degradados = _degradados(resultado)
    assert len(degradados) == 1, "el modo regex de desarrollo tiene que verse en la pantalla"
    assert "no configurada" in degradados[0]["detail"]
    assert marcas == [], (
        "no hay degradación de un servicio configurado: hay una instalación sin motor NLP. "
        "Marcarlo como avería encendería el aviso del panel para siempre")
    # Y el trabajo se hizo igual: el playground no se rompe por no tener sidecar.
    assert "maria.lopez@camara.es" not in resultado["prompt"]


@pytest.mark.asyncio
async def test_analyzer_caido_deja_trigger_visible_y_registro_durable(monkeypatch, marcas):
    """La degradación de un servicio que SÍ está configurado es un hecho operativo: se ve en
    la pantalla (efímero) y queda registrada (durable). Las dos cosas, no una."""
    monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)

    async def _caido(*_a, **_k):
        raise NlpUnavailableError("connection refused")

    monkeypatch.setattr(guardian_service.PresidioService, "analyze_text_http", _caido)

    resultado = await GuardianService.process_prompt(None, PROMPT, "modelo-x")

    degradados = _degradados(resultado)
    assert len(degradados) == 1
    assert "no disponible" in degradados[0]["detail"]
    assert marcas == ["playground/process_prompt"], (
        "sin marca durable, el trigger se lo lleva el próximo prompt y no queda nada")
    assert "maria.lopez@camara.es" not in resultado["prompt"], (
        "degradar no es dejar de proteger: el regex sigue enmascarando lo que puede")


# ── El cambio de postura queda registrado (issue #63; el gap general es del #72) ──


class _GuardianFila:
    def __init__(self, config, guardian_type="pii_masking"):
        self.config = config
        self.guardian_type = guardian_type
        self.tenant_id = None


@pytest.fixture
def filas_de_auditoria(monkeypatch):
    """Captura lo que se escribiría en `audit_logs` sin tocar la base."""
    from src.api import guardians as guardians_api
    registro = []
    monkeypatch.setattr(guardians_api.AuditService, "log_transaction",
                        staticmethod(lambda **kw: registro.append(kw)))
    return registro


@pytest.mark.parametrize("previo, config_nueva, esperado_en_modelo", [
    ("block", {"nlp_fail_mode": "degrade"}, "block->degrade"),
    ("degrade", {"nlp_fail_mode": "block"}, "degrade->block"),
    # Borrar la clave TAMBIÉN es un cambio de postura (vuelve al default fail-closed) y
    # tiene que auditarse: si sólo se mirara el valor escrito, vaciar el campo sería la
    # forma de cambiar la política sin dejar rastro.
    ("degrade", {}, "degrade->block"),
])
def test_el_cambio_de_nlp_fail_mode_deja_fila_durable(filas_de_auditoria, previo,
                                                      config_nueva, esperado_en_modelo):
    from src.api import guardians as guardians_api

    # Edición clásica por PUT: la fila ya era `pii_masking` y sigue siéndolo (tipo_previo =
    # tipo_actual = pii_masking). El #104 sólo agrega el `tipo_previo` explícito a la firma.
    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila(config_nueva), tipo_previo="pii_masking", previo=previo)

    assert len(filas_de_auditoria) == 1, (
        "una decisión de seguridad que nadie puede reconstruir después no es auditable")
    fila = filas_de_auditoria[0]
    assert fila["compliance_status"] == "config_change_nlp_fail_mode"
    assert esperado_en_modelo in fila["model"]
    # No hubo tráfico: ni tokens ni coste, o la fila contaminaría analytics y presupuestos.
    assert (fila["prompt_tokens"], fila["completion_tokens"], fila["cost_usd"]) == (0, 0, 0.0)


def test_guardar_sin_cambiar_la_postura_no_ensucia_la_auditoria(filas_de_auditoria):
    """La pantalla de Seguridad persiste los 9 guardianes en un bucle cada vez que se
    guarda: registrar "cambió" en cada guardado llenaría la auditoría de ruido y el officer
    dejaría de mirarla."""
    from src.api import guardians as guardians_api

    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila({"nlp_fail_mode": "block"}), tipo_previo="pii_masking",
        previo="block")

    assert filas_de_auditoria == []


def test_otro_guardian_no_genera_fila(filas_de_auditoria):
    from src.api import guardians as guardians_api

    # Ni el tipo previo ni el nuevo son `pii_masking`: no hay postura NLP en juego.
    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila({}, guardian_type="secret_detection"),
        tipo_previo="secret_detection", previo="degrade")

    assert filas_de_auditoria == []


# ── issue #104: la firma type-aware cierra el alta muda y la evasión por doble PUT ──


def test_alta_de_pii_masking_en_degrade_deja_fila(filas_de_auditoria):
    """POST /guardians: la fila NO existía antes (tipo_previo=None ⇒ línea base `block`). Un
    alta en `degrade` es un cambio de postura contra el default y tiene que quedar registrada."""
    from src.api import guardians as guardians_api

    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila({"nlp_fail_mode": "degrade"}), tipo_previo=None, previo="block")

    assert len(filas_de_auditoria) == 1
    assert "block->degrade" in filas_de_auditoria[0]["model"]


def test_alta_de_pii_masking_en_block_no_deja_fila(filas_de_auditoria):
    """El alta en el default (`block`) no cambia la postura: sin fila (nada de ruido)."""
    from src.api import guardians as guardians_api

    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila({}), tipo_previo=None, previo="block")

    assert filas_de_auditoria == []


def test_parkear_degrade_sacando_el_tipo_no_deja_fila(filas_de_auditoria):
    """PUT #1 de la evasión: `pii_masking`(block) → `regex` guardando `degrade`. Mientras la
    fila NO es `pii_masking`, ese `degrade` está INERTE y la postura efectiva sigue en `block`,
    así que todavía no hay cambio que auditar."""
    from src.api import guardians as guardians_api

    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila({"nlp_fail_mode": "degrade"}, guardian_type="regex"),
        tipo_previo="pii_masking", previo="block")

    assert filas_de_auditoria == []


def test_devolver_el_tipo_con_degrade_parkeado_si_deja_fila(filas_de_auditoria):
    """PUT #2 de la evasión: `regex`(degrade inerte) → `pii_masking`. Ahora el `degrade` pasa a
    gobernar de verdad. La línea base del lado previo (no era `pii_masking`) es `block`, así que
    el cambio `block->degrade` SÍ queda registrado: la evasión del #104 no puede completarse."""
    from src.api import guardians as guardians_api

    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila({"nlp_fail_mode": "degrade"}, guardian_type="pii_masking"),
        tipo_previo="regex", previo="block")

    assert len(filas_de_auditoria) == 1
    assert "block->degrade" in filas_de_auditoria[0]["model"]


def test_un_fallo_del_registro_no_voltea_el_guardado(monkeypatch):
    """El guardado ya se commiteó cuando esto corre: si el registro explota, el cambio del
    admin no puede "deshacerse" con un 500. Queda el `logger.error` como piso."""
    from src.api import guardians as guardians_api

    def _revienta(**_kw):
        raise RuntimeError("la base de auditoría no responde")

    monkeypatch.setattr(guardians_api.AuditService, "log_transaction", staticmethod(_revienta))

    guardians_api._auditar_cambio_nlp_fail_mode(
        None, _GuardianFila({"nlp_fail_mode": "degrade"}), tipo_previo="pii_masking",
        previo="block")  # no levanta


@pytest.mark.asyncio
async def test_analyzer_sano_no_marca_ni_avisa(monkeypatch, marcas):
    """Contracara: el camino sano no ensucia el estado ni la pantalla. Un aviso que aparece
    siempre no informa nada."""
    monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)

    async def _sano(text, *_a, **_k):
        i = text.find("maria.lopez@camara.es")
        return [] if i < 0 else [{"start": i, "end": i + len("maria.lopez@camara.es"),
                                  "entity_type": "EMAIL_ADDRESS", "score": 0.9}]

    monkeypatch.setattr(guardian_service.PresidioService, "analyze_text_http", _sano)

    resultado = await GuardianService.process_prompt(None, PROMPT, "modelo-x")

    assert _degradados(resultado) == []
    assert marcas == []
    assert "maria.lopez@camara.es" not in resultado["prompt"]
