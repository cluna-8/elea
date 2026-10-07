"""T096 (057 FR-027, SC-006; research R29; contracts/costuras-base.md §S14): el forzado de punta a punta, multiturno.

De la pasarela al motor, con las piezas reales y el analizador regex de la base: el plugin resuelve y firma la
autorización (`fm`), el guardrail del motor —sin ninguna señal inyectada por el test— se entera por el resolutor que
registra el guard al importarse, enmascara con alcance completo, informa `scope`/`unanalyzable`/`signed_thinking`, y
el guard verifica el informe y escribe `masking_scope` en la decisión.

Lo que fija: la herramienta reenvía el historial **ya restaurado** (el cliente guarda lo que recibió) y sale enmascarado
otra vez; `system` con DNI/CUIT/CBU; un PDF con texto; una imagen no analizable ⇒ `masking_required`; `thinking`
firmado con detecciones hacia un destino nativo ⇒ bloqueo y hacia un traducido no; sin el resolutor registrado (una
base sin S14 o un guard que no se cargó) ⇒ `masking_required` (falla cerrado); y la respuesta vuelve restaurada."""
import copy
import json
import os
import sys

import pytest

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "backend", "tests", "unit"))

import s14_helpers as h  # noqa: E402  (PDFs generados a mano; doble de litellm)
from extensions import sentinel_guardrail  # noqa: E402
from extensions import sentinel_guardian_policy as policy  # noqa: E402
from sentinel.engine import redirect_guard as guard  # noqa: E402
from sentinel.redirect import authz  # noqa: E402
from sentinel.redirect.plugin import RedirectPlugin  # noqa: E402
from sentinel.tests import redirect_fixtures as fx  # noqa: E402
from sentinel.tests import residency_fixtures as rf  # noqa: E402

DNI, DNI_PUNTOS, CUIT, CBU = h.DNI, h.DNI_PUNTOS, h.CUIT, h.CBU
PII = (DNI, DNI_PUNTOS, CUIT, CBU, h.CUIT_SIN_GUIONES)


class _Identidad:
    def __init__(self, **sentinel):
        self.metadata = {"sentinel": {"region": "latam_ar", **sentinel}}


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, fx.INTERNAL_KEY)
    monkeypatch.setenv("SENTINEL_ENTITY_REGION", "latam_ar")

    async def _nada(*_a, **_k):
        return None

    monkeypatch.setattr(sentinel_guardrail, "_auditar_bloqueo", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_marcar_nlp_degradado", _nada)
    monkeypatch.setattr(sentinel_guardrail, "_PRESIDIO_URL", None)
    # Como en el motor: el guardrail base (módulo plano) y el guard (que carga `extensions.…`) se instancian al arrancar
    guard.RedirectGuard(guardrail_name="redirect-guard")
    yield
    guard.register_forced_masking_resolver()


def _snapshot():
    dest = {**fx.DEST_ANTHROPIC, "id": "d-us", "level": "tenant", "tenant_id": fx.TENANT,
            "inference_jurisdiction": "US", "entity_jurisdiction": "US", "control_jurisdiction": "US"}
    snap = fx.snapshot("on", regions=[rf.region_row("masked_all")], targets=("d-us",), claude_targets=("d-us",),
                       offers=())
    return snap.__class__(**{**snap.__dict__, "destinations": {**snap.destinations, "d-us": dest},
                             "credentials": {**snap.credentials, "d-us": json.dumps({"api_key": "sk-destino-us"})}})


async def _pedido(messages, *, system=None, tools=None):
    """Lo que ve el motor: el cuerpo que sale de `pre_engine` + la cabecera firmada, como `data` del hook."""
    p = RedirectPlugin(store=fx.store(_snapshot()), ping_after=0.05)
    c = fx.ctx(route="/v1/messages", model="claude-sonnet-4-5", nlp={"region": "latam_ar"})
    assert await p.pre_request(c) is None
    body = {"model": "claude-sonnet-4-5", "max_tokens": 64, "messages": copy.deepcopy(messages)}
    if system is not None:
        body["system"] = system
    if tools is not None:
        body["tools"] = tools
    body, headers = p.pre_engine(c, body, {})
    data = {**body, "proxy_server_request": {"headers": {authz.HEADER: headers[authz.HEADER]}},
            "metadata": {}, "litellm_metadata": {}}
    return data, c


async def _motor(data, *, informe_a_mano=None):
    """Guardrail de la base y, después, guard de la extensión (el orden del fragmento de perfil)."""
    salida = await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(
        _Identidad(), None, data, "anthropic_messages")
    if informe_a_mano is not None:
        data["litellm_metadata"]["masking_report"] = informe_a_mano
    informe = data["litellm_metadata"]["masking_report"]
    guard.apply_redirect(data, key=fx.INTERNAL_KEY, call_type="anthropic_messages",
                         environ={"REDIRECT_CRED_ANT": "k"})
    return salida, informe


def _saliente(data):
    return json.dumps({k: v for k, v in data.items()
                       if k not in ("litellm_metadata", "metadata", "proxy_server_request")}, ensure_ascii=False)


def _historial_restaurado():
    """Varios turnos; el asistente ya vuelve restaurado (con el dato en claro) porque el cliente guarda lo que vio."""
    return [
        {"role": "user", "content": f"Hola, mi DNI es {DNI_PUNTOS} y mi CUIT {CUIT}."},
        {"role": "assistant", "content": [
            {"type": "text", "text": f"Gracias, confirmo el DNI {DNI_PUNTOS}."},
            {"type": "tool_use", "id": "toolu_0001", "name": "buscar", "input": {"cbu": CBU}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_0001",
                                      "content": f"Titular del CBU {CBU}: CUIT {h.CUIT_SIN_GUIONES}"}]},
        {"role": "assistant", "content": f"El CUIT {CUIT} figura activo."},
        {"role": "user", "content": "Perfecto, gracias."},
    ]


@pytest.mark.asyncio
async def test_multiturno_con_system_y_herramientas_sale_enmascarado_y_el_guard_lo_deja_pasar():
    data, _ = await _pedido(_historial_restaurado(),
                            system=f"Atendés al cliente con DNI {DNI} y CUIT {CUIT}. CBU de pruebas {CBU}.",
                            tools=[{"name": "buscar", "description": f"Busca por CBU, ej. {CBU}",
                                    "input_schema": {"type": "object", "properties": {}}}])
    salida, informe = await _motor(data)
    saliente = _saliente(salida)
    for valor in PII:
        assert valor not in saliente, f"{valor!r} salió en claro"
    assert informe["scope"] == "full" and informe["unanalyzable"] == 0 and informe["completed"] is True
    assert informe["detected"] == informe["masked"] > 0
    rd = data["litellm_metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert rd["masking_verified"] is True and rd["masking_scope"] == "full"
    assert "toolu_0001" in saliente and "buscar" in saliente           # lo estructural intacto


@pytest.mark.asyncio
async def test_el_forzado_de_la_pasarela_llega_a_la_decision_de_auditoria():
    _, c = await _pedido([{"role": "user", "content": "hola"}])
    assert c.routing_decision["extensions"]["redirect"]["masking_scope"] == "full"
    assert c.governance_overrides["masking_scope"] == "full"


@pytest.mark.asyncio
async def test_la_respuesta_vuelve_restaurada_aunque_el_modelo_repita_los_marcadores():
    data, _ = await _pedido(_historial_restaurado())
    await _motor(data)
    ph_to_orig = sentinel_guardrail._pii_tokens_from(data)
    ph = next(ph for ph, orig in ph_to_orig.items() if DNI_PUNTOS in orig)
    respuesta = {"content": [{"type": "text", "text": f"Listo, el {ph} quedó registrado."}]}
    out = await sentinel_guardrail.SentinelGuardrail().async_post_call_success_hook(data, None, respuesta)
    assert out["content"][0]["text"] == f"Listo, el {DNI_PUNTOS} quedó registrado."


@pytest.mark.asyncio
async def test_un_pdf_con_texto_viaja_como_texto_enmascarado():
    pdf = h.pdf_con_texto(f"Titular DNI {DNI_PUNTOS}")
    data, _ = await _pedido([{"role": "user", "content": [
        {"type": "text", "text": "Mirá el adjunto."}, h.bloque_pdf(pdf)]}])
    if not h.HAY_PYPDF:                                    # imagen base sin `pypdf`: no analizable ⇒ bloqueo
        with pytest.raises(guard.GuardRejection) as e:
            await _motor(data)
        assert e.value.code == "masking_required"
        return
    salida, informe = await _motor(data)
    assert DNI_PUNTOS not in _saliente(salida) and informe["unanalyzable"] == 0


@pytest.mark.asyncio
async def test_una_imagen_es_no_analizable_y_el_guard_bloquea_con_masking_required():
    img = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}
    data, _ = await _pedido([{"role": "user", "content": [{"type": "text", "text": "mirá"}, img]}])
    with pytest.raises(guard.GuardRejection) as e:
        await _motor(data)
    assert e.value.code == "masking_required"
    assert data["litellm_metadata"]["masking_report"]["unanalyzable_kinds"] == ["image"]
    assert "iVBOR" not in str(e.value.message)


def _captura():
    return {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBORw0KGgo="}}


@pytest.mark.asyncio
async def test_la_captura_de_cowork_en_un_tool_result_no_corta_la_tarea_y_queda_en_la_auditoria():
    """R39: Cowork verifica su PDF con una captura que vuelve como imagen dentro de un `tool_result`. Bajo el forzado
    el binario nunca sale: se reemplaza por una nota, el guard deja pasar y la auditoría lo registra."""
    data, _ = await _pedido([
        {"role": "user", "content": "creame un pdf con mis datos"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_0002", "name": "screenshot", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_0002",
                                      "content": [{"type": "text", "text": f"Listo, DNI {DNI_PUNTOS}"}, _captura()]}]}])
    salida, informe = await _motor(data)
    saliente = _saliente(salida)
    assert "iVBOR" not in saliente and DNI_PUNTOS not in saliente
    assert policy.UNANALYZABLE_REPLACED_NOTE in saliente
    assert informe["unanalyzable"] == 0 and informe["unanalyzable_replaced"] == 1
    rd = data["litellm_metadata"]["_internal_routing_decision"]["extensions"]["redirect"]
    assert rd["unanalyzable_replaced"] == 1 and rd["unanalyzable_replaced_kinds"] == "image"
    assert rd["masking_verified"] is True


@pytest.mark.asyncio
async def test_la_imagen_que_adjunta_la_persona_junto_al_tool_result_sigue_bloqueando():
    data, _ = await _pedido([
        {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_0003", "name": "screenshot", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_0003", "content": [_captura()]},
                                     _captura()]}])
    with pytest.raises(guard.GuardRejection) as e:
        await _motor(data)
    assert e.value.code == "masking_required"
    assert data["litellm_metadata"]["masking_report"]["unanalyzable_kinds"] == ["image"]


@pytest.mark.asyncio
async def test_sin_el_resolutor_registrado_el_pedido_forzado_se_bloquea_falla_cerrado():
    for mod in (policy, sys.modules.get("sentinel_guardian_policy")):
        if mod is not None:
            mod.clear_forced_masking_resolvers()
    data, _ = await _pedido([{"role": "user", "content": f"DNI {DNI_PUNTOS}"}])
    with pytest.raises(guard.GuardRejection) as e:
        await _motor(data)
    assert e.value.code == "masking_required"
    assert data["litellm_metadata"]["masking_report"]["scope"] == "user"


def _thinking_firmado():
    return [{"role": "user", "content": "hola"},
            {"role": "assistant", "content": [
                {"type": "thinking", "thinking": f"El usuario tiene DNI {DNI_PUNTOS}.", "signature": "EqQBCkYI..."},
                {"type": "text", "text": "Hola."}]},
            {"role": "user", "content": "seguimos"}]


@pytest.mark.asyncio
async def test_thinking_firmado_con_detecciones_hacia_un_destino_nativo_se_bloquea():
    data, _ = await _pedido(_thinking_firmado())
    with pytest.raises(guard.GuardRejection) as e:
        await _motor(data)
    assert e.value.code == "masking_required"
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["signed_thinking"] == 1 and informe["unanalyzable"] == 0


@pytest.mark.asyncio
async def test_thinking_firmado_hacia_un_traducido_no_bloquea():
    """La firma se reconstruye (R10): el informe lo cuenta pero el guard no bloquea fuera del destino nativo."""
    data, _ = await _pedido(_thinking_firmado())
    await sentinel_guardrail.SentinelGuardrail().async_pre_call_hook(_Identidad(), None, data, "anthropic_messages")
    informe = data["litellm_metadata"]["masking_report"]
    assert informe["signed_thinking"] == 1
    assert guard.signed_thinking_blocks(informe, "rdx-chatcompat") is False
    assert guard.masking_ok(informe, forced=True) is True
