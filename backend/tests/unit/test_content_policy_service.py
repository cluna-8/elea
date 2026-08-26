"""Tests de `ai_engine_client` — políticas de contenido (spec 036, sesión 11-ago-2026).

No pegan por red: monkeypatchean los helpers `_post`/`_get`/`_delete_by_id` del
propio módulo, igual que el resto del proyecto testea sobre `ai_engine_client` (ver
`test_auto_router_service.py`). Lo que se prueba es la lógica de Basa (armado del
payload, filtro del listado, contrato de retorno) — el motor de LiteLLM en sí ya
se probó en vivo (specs/036-plantillas-politicas-cliente/quickstart.md).
"""
import pytest

from src.services import ai_engine_client as svc


@pytest.mark.asyncio
async def test_create_content_policy_arma_el_payload_correcto(monkeypatch):
    capturado = {}

    async def _post_doble(path, payload):
        capturado["path"] = path
        capturado["payload"] = payload
        return {"guardrail_id": "abc-123"}

    monkeypatch.setattr(svc, "_post", _post_doble)

    resultado = await svc.create_content_policy(
        policy_id="banco-xyz-sin-credito",
        description="No dar asesoramiento de crédito",
        blocked_words=[{"keyword": "aprobar tu crédito", "action": "BLOCK"}],
        categories=[],
        active=True,
    )

    assert capturado["path"] == "/guardrails"
    g = capturado["payload"]["guardrail"]
    assert g["guardrail_name"] == "basa-policy-banco-xyz-sin-credito"
    assert g["litellm_params"]["guardrail"] == "litellm_content_filter"
    assert g["litellm_params"]["default_on"] is True
    assert g["litellm_params"]["blocked_words"] == [
        {"keyword": "aprobar tu crédito", "action": "BLOCK"}
    ]
    assert "categories" not in g["litellm_params"]  # lista vacía: no se manda la clave
    assert g["guardrail_info"]["description"] == "No dar asesoramiento de crédito"

    assert resultado["policy_id"] == "banco-xyz-sin-credito"
    assert resultado["guardrail_id"] == "abc-123"
    assert resultado["active"] is True


@pytest.mark.asyncio
async def test_create_content_policy_con_plantilla_ya_armada(monkeypatch):
    """El caso que faltaba (encontrado por Cristian, 11-ago-2026): activar una de las
    ~40 plantillas que ya trae litellm_content_filter (EU AI Act, Singapur, EAU...) por
    NOMBRE, sin escribir palabras propias — y las dos formas pueden convivir."""
    capturado = {}

    async def _post_doble(path, payload):
        capturado["payload"] = payload
        return {"guardrail_id": "xyz-789"}

    monkeypatch.setattr(svc, "_post", _post_doble)

    resultado = await svc.create_content_policy(
        policy_id="cliente-eu-ai-act",
        description="AI Act completo para este cliente",
        blocked_words=[],
        categories=[{"category": "eu_ai_act_article5", "action": "BLOCK"}],
        active=True,
    )

    g = capturado["payload"]["guardrail"]
    assert "blocked_words" not in g["litellm_params"]  # lista vacía: no se manda la clave
    assert g["litellm_params"]["categories"] == [
        {"category": "eu_ai_act_article5", "action": "BLOCK"}
    ]
    assert resultado["categories"] == [{"category": "eu_ai_act_article5", "action": "BLOCK"}]


@pytest.mark.asyncio
async def test_create_content_policy_con_category_file_propio(monkeypatch):
    """Hallazgo real (11-ago-2026): las plantillas de EU AI Act/Singapur/EAU NO se
    resuelven solo por nombre (viven en policy_templates/, no en categories/, que es
    lo único que `_load_categories` mira sin `category_file`) — necesitan
    `category_file` explícito. Mismo camino para una categoría propia nuestra
    (litellm/policy_categories/*.yaml, ej. la traducción al español)."""
    capturado = {}

    async def _post_doble(path, payload):
        capturado["payload"] = payload
        return {"guardrail_id": "es-123"}

    monkeypatch.setattr(svc, "_post", _post_doble)

    await svc.create_content_policy(
        policy_id="cliente-es",
        description="AI Act en español",
        blocked_words=[],
        categories=[{
            "category": "eu_ai_act_articulo5_es",
            "action": "BLOCK",
            "category_file": "/app/policy_categories/eu_ai_act_articulo5_es.yaml",
        }],
        active=True,
    )

    g = capturado["payload"]["guardrail"]
    assert g["litellm_params"]["categories"][0]["category_file"] == \
        "/app/policy_categories/eu_ai_act_articulo5_es.yaml"


@pytest.mark.asyncio
async def test_list_content_policies_filtra_lo_que_no_es_de_basa(monkeypatch):
    """El listado de LiteLLM trae de todo (basa-guardian, el ejemplo estático de
    config.yaml, guardrails de otros proveedores) — solo deben sobrevivir las
    creadas por este módulo (prefijo + proveedor)."""
    async def _get_doble(path, params):
        assert path == "/v2/guardrails/list"
        return {"guardrails": [
            {
                "guardrail_name": "basa-guardian",
                "litellm_params": {"guardrail": "extensions.basa_guardrail.BasaGuardrail"},
                "guardrail_info": {},
            },
            {
                "guardrail_name": "basa-content-filter",  # el estático de config.yaml, no una política
                "litellm_params": {"guardrail": "litellm_content_filter", "default_on": False},
                "guardrail_info": {},
            },
            {
                "guardrail_name": "basa-policy-banco-xyz-sin-credito",
                "guardrail_id": "abc-123",
                "litellm_params": {
                    "guardrail": "litellm_content_filter",
                    "default_on": True,
                    "blocked_words": [{"keyword": "aprobar tu crédito", "action": "BLOCK"}],
                },
                "guardrail_info": {"description": "No dar asesoramiento de crédito"},
            },
            {
                "guardrail_name": "otro-proveedor-cualquiera",
                "litellm_params": {"guardrail": "bedrock"},
                "guardrail_info": {},
            },
        ]}

    monkeypatch.setattr(svc, "_get", _get_doble)

    resultado = await svc.list_content_policies()

    assert len(resultado) == 1
    p = resultado[0]
    assert p["policy_id"] == "banco-xyz-sin-credito"
    assert p["guardrail_id"] == "abc-123"
    assert p["active"] is True
    assert p["description"] == "No dar asesoramiento de crédito"
    assert p["blocked_words"] == [{"keyword": "aprobar tu crédito", "action": "BLOCK"}]
    assert p["categories"] == []


@pytest.mark.asyncio
async def test_update_content_policy_borra_y_crea_de_nuevo(monkeypatch):
    """Ya NO usa PUT — hallazgo real en vivo (11-ago-2026, con Cristian): el PUT de
    LiteLLM guarda bien en su base pero falla al sincronizar en memoria cuando la
    política tiene `categories` con `category_file` (bug de LiteLLM, confirmado con
    curl directo). BORRAR + CREAR esquiva ese bug — hay que mandar el objeto completo
    igual, porque `create_content_policy` no acepta PATCH parcial tampoco."""
    capturado = {}

    async def _delete_doble(path):
        capturado["delete_path"] = path
        return {"message": "ok"}

    async def _post_doble(path, payload):
        capturado["post_path"] = path
        capturado["payload"] = payload
        return {"guardrail_id": "nuevo-id-456"}

    monkeypatch.setattr(svc, "_delete_by_id", _delete_doble)
    monkeypatch.setattr(svc, "_post", _post_doble)

    resultado = await svc.update_content_policy(
        guardrail_id="abc-123",
        policy_id="banco-xyz-sin-credito",
        description="Actualizada",
        blocked_words=[
            {"keyword": "aprobar tu crédito", "action": "BLOCK"},
            {"keyword": "tasa preferencial", "action": "MASK"},
        ],
        categories=[],
        active=False,
    )

    assert capturado["delete_path"] == "/guardrails/abc-123"
    assert capturado["post_path"] == "/guardrails"
    g = capturado["payload"]["guardrail"]
    assert g["litellm_params"]["default_on"] is False
    assert len(g["litellm_params"]["blocked_words"]) == 2
    assert resultado["guardrail_id"] == "nuevo-id-456"  # cambia — no se persiste en Basa


@pytest.mark.asyncio
async def test_delete_content_policy_llama_al_id_correcto(monkeypatch):
    capturado = {}

    async def _delete_doble(path):
        capturado["path"] = path
        return {"message": "ok"}

    monkeypatch.setattr(svc, "_delete_by_id", _delete_doble)

    await svc.delete_content_policy("abc-123")

    assert capturado["path"] == "/guardrails/abc-123"


@pytest.mark.asyncio
async def test_errores_de_red_se_traducen_a_content_policy_error(monkeypatch):
    """El caller (el router) solo necesita atrapar un tipo de excepción — confirmar
    que un fallo de red en cualquiera de las 4 operaciones no se escapa como algo
    distinto."""
    async def _post_falla(path, payload):
        raise svc.AIEngineClientError("motor caído")

    monkeypatch.setattr(svc, "_post", _post_falla)

    with pytest.raises(svc.AIEngineClientError):
        await svc.create_content_policy("x", "d", [{"keyword": "a", "action": "BLOCK"}], [], False)


@pytest.mark.asyncio
async def test_update_distingue_la_fase_que_falla(monkeypatch):
    """Las dos fases del borra+crea dejan el motor en estados OPUESTOS, así que NO pueden
    levantar el mismo error (P1 del gate cross-familia de #315, 26-ago-2026):

    - falla el `_delete_by_id` → la política sigue INTACTA. No hay nada que reponer.
    - falla el `_post` posterior → la política está BORRADA. Si el caller no la repone, el
      motor deja de filtrar y el 502 se lee como «no pasó nada».

    `ContentPolicyLostError` es subclase de `ContentPolicyError`: el caller que sólo quiera
    «falló algo» sigue funcionando, y el que compensa ordena los `except` de específico a
    general."""
    async def _delete_ok(path):
        return {}

    async def _delete_falla(path):
        raise svc.AIEngineClientError("motor caído en el DELETE")

    async def _post_falla(path, payload):
        raise svc.AIEngineClientError("motor caído en el POST")

    # Rama post-delete: el borrado se aplicó ⇒ tipo que pide compensación.
    monkeypatch.setattr(svc, "_delete_by_id", _delete_ok)
    monkeypatch.setattr(svc, "_post", _post_falla)
    with pytest.raises(svc.ContentPolicyLostError):
        await svc.update_content_policy("gid", "x", "d", [{"keyword": "a", "action": "BLOCK"}],
                                        [], False)

    # Rama delete: no se borró nada ⇒ NO puede ser el tipo que dispara la compensación.
    monkeypatch.setattr(svc, "_delete_by_id", _delete_falla)
    with pytest.raises(svc.ContentPolicyError) as exc:
        await svc.update_content_policy("gid", "x", "d", [{"keyword": "a", "action": "BLOCK"}],
                                        [], False)
    assert not isinstance(exc.value, svc.ContentPolicyLostError), (
        "fallar el DELETE no borró nada: marcarlo como 'perdida' hace que el caller reponga "
        "una política que sigue viva, y le borra al admin la diferencia entre 'no pasó nada' "
        "y 'perdiste la política'")
