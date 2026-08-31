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
import uuid
from datetime import datetime

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
        # Espeja el contrato del modelo real (Guardian): `process_prompt` desempata la fila
        # `pii_masking` por `(created_at, id)` desde el #119. Toda fila real los trae no-nulos
        # (migración 015 + PK); el fake también, o la selección no tiene por dónde ordenar.
        self.created_at = datetime.utcnow()
        self.id = uuid.uuid4()


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


# ── El cambio de postura EFECTIVA del tenant queda registrado (issue #63/#104) ──
#
# El round 2 del #104 movió el criterio: se audita la postura que GOBIERNA el tráfico (el
# `pii_masking` activo más antiguo del tenant, vía `_postura_efectiva_tenant`), no la de la fila
# aislada que se toca. El auditor (`_auditar_cambio_postura_tenant`) recibe la postura efectiva
# ANTES y DESPUÉS y escribe iff cambió; los escenarios multi-fila (promoción por desactivar o
# borrar la gobernante, alta gobernante, no-ruido de altas inactivas) se prueban de punta a punta
# en `tests/integration/test_nlp_posture_determinista.py`.

TENANT = "00000000-0000-0000-0000-0000000000aa"


@pytest.fixture
def filas_de_auditoria(monkeypatch):
    """Captura lo que se escribiría en `audit_logs` sin tocar la base."""
    from src.api import guardians as guardians_api
    registro = []
    monkeypatch.setattr(guardians_api.AuditService, "log_transaction",
                        staticmethod(lambda **kw: registro.append(kw)))
    return registro


@pytest.mark.parametrize("previo, actual, esperado_en_modelo", [
    ("block", "degrade", "block->degrade"),
    ("degrade", "block", "degrade->block"),
])
def test_cambio_de_postura_efectiva_deja_fila_durable(filas_de_auditoria, previo, actual,
                                                      esperado_en_modelo):
    """Cuando la postura efectiva del tenant cambia, hay fila durable con vocabulario cerrado y
    cero tráfico (o contaminaría analytics y presupuestos)."""
    from src.api import guardians as guardians_api

    guardians_api._auditar_cambio_postura_tenant(None, TENANT, previo, actual)

    assert len(filas_de_auditoria) == 1, (
        "una decisión de seguridad que nadie puede reconstruir después no es auditable")
    fila = filas_de_auditoria[0]
    assert fila["compliance_status"] == "config_change_nlp_fail_mode"
    assert esperado_en_modelo in fila["model"]
    assert fila["tenant_id"] == TENANT
    assert (fila["prompt_tokens"], fila["completion_tokens"], fila["cost_usd"]) == (0, 0, 0.0)


@pytest.mark.parametrize("postura", ["block", "degrade"])
def test_postura_efectiva_sin_cambio_no_ensucia_la_auditoria(filas_de_auditoria, postura):
    """La pantalla de Seguridad persiste los 9 guardianes en un bucle: registrar en cada
    guardado que NO mueve la postura efectiva llenaría la auditoría de ruido y el officer
    dejaría de mirarla."""
    from src.api import guardians as guardians_api

    guardians_api._auditar_cambio_postura_tenant(None, TENANT, postura, postura)

    assert filas_de_auditoria == []


def test_un_fallo_del_registro_no_voltea_la_mutacion(monkeypatch):
    """La mutación ya se commiteó cuando esto corre: si el registro explota, no puede
    "deshacerse" con un 500. Queda el `logger.error` como piso."""
    from src.api import guardians as guardians_api

    def _revienta(**_kw):
        raise RuntimeError("la base de auditoría no responde")

    monkeypatch.setattr(guardians_api.AuditService, "log_transaction", staticmethod(_revienta))

    guardians_api._auditar_cambio_postura_tenant(None, TENANT, "block", "degrade")  # no levanta


# ── `_postura_efectiva_tenant` = el MISMO criterio que los cuatro lectores del #104 ──


class _FakeQueryPostura:
    """Modela `db.query(Guardian.config).filter(...).order_by(...).first()`."""

    def __init__(self, fila):
        self._fila = fila

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def first(self):
        return self._fila


class _FakeSessionPostura:
    def __init__(self, fila):
        self._fila = fila

    def query(self, *_a, **_k):
        return _FakeQueryPostura(self._fila)


def test_postura_efectiva_tenant_sin_fila_activa_es_block():
    """Espejo del fail-closed de los lectores: sin `pii_masking` activo, `block`."""
    from src.api import guardians as guardians_api

    assert guardians_api._postura_efectiva_tenant(_FakeSessionPostura(None), TENANT) == "block"


def test_postura_efectiva_tenant_resuelve_la_config_de_la_fila_elegida():
    """Con la fila del `pii_masking` activo más antiguo se resuelve su `nlp_fail_mode`. El
    `first()` de `query(Guardian.config)` devuelve una tupla de un elemento."""
    from src.api import guardians as guardians_api

    sesion = _FakeSessionPostura(({"nlp_fail_mode": "degrade"},))
    assert guardians_api._postura_efectiva_tenant(sesion, TENANT) == "degrade"


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


# ── H6 del gate de #137: aviso ante región no reconocida en escritura ──────────────
#
# `resolve_region` cae al default en SILENCIO en LECTURA (correcto, patrón #131 de
# guardia ruidosa: un typo no puede activar/desactivar reconocedores de otro país por
# accidente). Pero eso deja al admin que tipeó mal el código de región sin ninguna señal
# de que su cambio no tuvo efecto. No se rechaza el write —mismo criterio que
# `nlp_fail_mode`, que tampoco valida en escritura ("config" es libre)— pero la
# degradación silenciosa se vuelve RUIDOSA con un WARNING.

def test_region_no_reconocida_en_escritura_avisa_por_log(caplog):
    from src.api import guardians as guardians_api

    with caplog.at_level("WARNING", logger="sentinel-secure-gateway.guardians"):
        guardians_api._advertir_region_no_reconocida(
            TENANT, "pii_masking", {"region": "latam-ar"})  # typo: guión, no guión bajo

    assert any("latam-ar" in r.message and TENANT in r.message for r in caplog.records), (
        "el admin que tipeó mal la región no tiene otra señal de que resolve_region() "
        "la va a ignorar")


def test_region_reconocida_no_avisa(caplog):
    from src.api import guardians as guardians_api

    with caplog.at_level("WARNING", logger="sentinel-secure-gateway.guardians"):
        guardians_api._advertir_region_no_reconocida(TENANT, "pii_masking", {"region": "latam_ar"})

    assert caplog.records == []


def test_region_ausente_o_vacia_no_avisa(caplog):
    """Ausente/vacía es retrocompatible (cae al default de instalación) — no es un typo,
    no merece el mismo aviso que un valor mal tipeado."""
    from src.api import guardians as guardians_api

    with caplog.at_level("WARNING", logger="sentinel-secure-gateway.guardians"):
        guardians_api._advertir_region_no_reconocida(TENANT, "pii_masking", {})
        guardians_api._advertir_region_no_reconocida(TENANT, "pii_masking", {"region": ""})
        guardians_api._advertir_region_no_reconocida(TENANT, "pii_masking", None)

    assert caplog.records == []


def test_otro_tipo_de_guardian_no_avisa(caplog):
    """`region` sólo tiene significado en `pii_masking` — otro tipo de guardián con esa
    clave en su config (coincidencia, o un campo propio del tipo) no es asunto de este
    aviso."""
    from src.api import guardians as guardians_api

    with caplog.at_level("WARNING", logger="sentinel-secure-gateway.guardians"):
        guardians_api._advertir_region_no_reconocida(TENANT, "secret_detection", {"region": "mars"})

    assert caplog.records == []


# ── H1 del gate de #137: el Playground resuelve la región del tenant (no "eu" hardcodeado) ──


@pytest.mark.asyncio
async def test_playground_usa_la_region_del_tenant_no_el_literal_eu(monkeypatch):
    """Antes: `analyze_text_http` hardcodeaba `region="eu"` — el Playground SIEMPRE
    detectaba con los patrones de España, sin importar la región del tenant ni la de la
    instalación. Mutación que este test mata: volver a `region: str = "eu"` en la firma de
    `PresidioService.analyze_text_http` (o no leer `pii_guardian.config.get('region')` en
    `process_prompt`) lo deja en rojo."""
    monkeypatch.delenv("SENTINEL_ENTITY_REGION", raising=False)
    guardianes = [_GuardianFalso("pii_masking", {"entities": ["EMAIL_ADDRESS", "PERSON"],
                                                 "action": "MASK", "custom_names": [],
                                                 "region": "latam_ar"})]
    monkeypatch.setattr(GuardianService, "get_or_create_default_guardians",
                        staticmethod(lambda db: guardianes))
    monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)

    capturada = {}

    async def _analyze_http(text, analyzer_url, language="es", entities=None,
                            custom_names=None, region=None):
        capturada["region"] = region
        return []

    monkeypatch.setattr(guardian_service.PresidioService, "analyze_text_http", _analyze_http)

    await GuardianService.process_prompt(None, PROMPT, "modelo-x")

    assert capturada.get("region") == "latam_ar", (
        "el Playground no propagó la región del tenant al analyzer HTTP")


@pytest.mark.asyncio
async def test_playground_degradado_tambien_resuelve_la_region_del_tenant(monkeypatch, marcas):
    """Mismo hallazgo que arriba pero en el camino degrade (analyzer configurado, caído):
    `PresidioService.analyze_text` (el fallback regex) tampoco tenía el parámetro `region` —
    se congelaba en `policy.DEFAULT_REGION` sin importar el tenant."""
    monkeypatch.delenv("SENTINEL_ENTITY_REGION", raising=False)
    guardianes = [_GuardianFalso("pii_masking", {"entities": ["EMAIL_ADDRESS", "PERSON"],
                                                 "action": "MASK", "custom_names": [],
                                                 "region": "latam_ar"})]
    monkeypatch.setattr(GuardianService, "get_or_create_default_guardians",
                        staticmethod(lambda db: guardianes))
    monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)

    async def _caido(*_a, **_k):
        raise NlpUnavailableError("connection refused")

    monkeypatch.setattr(guardian_service.PresidioService, "analyze_text_http", _caido)

    capturada = {}
    original = guardian_service.policy.default_analyze

    async def _default_analyze_espia(text, region=guardian_service.policy.DEFAULT_REGION):
        capturada["region"] = region
        return await original(text, region=region)

    monkeypatch.setattr(guardian_service.policy, "default_analyze", _default_analyze_espia)

    await GuardianService.process_prompt(None, PROMPT, "modelo-x")

    assert capturada.get("region") == "latam_ar"


@pytest.mark.asyncio
async def test_playground_sin_region_propia_cae_al_default_de_instalacion(monkeypatch):
    """Retrocompatibilidad: un `pii_masking` sin `region` en su config (instalación de
    antes de este PR) sigue resolviendo `SENTINEL_ENTITY_REGION`/`DEFAULT_REGION`."""
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")
    guardianes = [_GuardianFalso("pii_masking", {"entities": ["EMAIL_ADDRESS", "PERSON"],
                                                 "action": "MASK", "custom_names": []})]
    monkeypatch.setattr(GuardianService, "get_or_create_default_guardians",
                        staticmethod(lambda db: guardianes))
    monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)

    capturada = {}

    async def _analyze_http(text, analyzer_url, language="es", entities=None,
                            custom_names=None, region=None):
        capturada["region"] = region
        return []

    monkeypatch.setattr(guardian_service.PresidioService, "analyze_text_http", _analyze_http)

    await GuardianService.process_prompt(None, PROMPT, "modelo-x")

    assert capturada.get("region") == "latam_ar"
