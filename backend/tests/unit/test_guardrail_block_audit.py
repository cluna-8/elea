"""Auditoría durable de los bloqueos del plano MOTOR (spec 031 T005, D3/D4/D5).

Qué se protege acá: hasta la 031, los cuatro puntos de bloqueo de `BasaGuardrail.
async_pre_call_hook` devolvían el rechazo y NO dejaban fila — el logger de auditoría solo
implementa el hook de ÉXITO, así que TODO el tráfico byok de herramientas (la superficie
principal del producto) podía ser bloqueado sin dejar rastro durable. Un producto de
auditoría cuyo evento «se intentó y se impidió» no queda en ninguna parte es indefendible
en una demo de compliance, así que estos tests son el contrato de esa garantía:

1. cada punto de bloqueo POSTea la fila **antes** de rechazar (registrar → bloquear);
2. si el POST se cae en `open`, el cliente recibe EXACTAMENTE el mismo rechazo y la
   pérdida queda contada y logueada (nunca "se bloqueó y no quedó nada" en silencio);
3. en `closed`, un probe caído corta el pedido ANTES de tocar la política y, sobre todo,
   antes de que salga al proveedor (FR-005: no gastar dinero en tráfico inauditable);
4. el probe se cachea 5 s (riesgo R2 del research: el pre-check no puede volverse el
   costo dominante del pedido durante una caída).

La extensión se importa como la importa el motor (`from extensions import basa_guardrail`,
vía el `sys.path` que arma conftest) con un doble de `litellm.integrations.
custom_guardrail` en `sys.modules`: litellm NO está instalado en el backend y no hace
falta que lo esté — lo que se prueba es NUESTRA lógica de registro, no el SDK del motor.
"""
import sys
import types

import httpx
import pytest


# ── Doble de litellm.integrations.custom_guardrail (el módulo real no está acá) ─────────
def _instalar_doble_litellm():
    if "litellm.integrations.custom_guardrail" in sys.modules:
        return

    class CustomGuardrail:
        """Base vacía: el hook no usa nada del SDK, solo hereda de él."""
        def __init__(self, *args, **kwargs):
            pass

    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    integrations = sys.modules.setdefault(
        "litellm.integrations", types.ModuleType("litellm.integrations"))
    modulo = types.ModuleType("litellm.integrations.custom_guardrail")
    modulo.CustomGuardrail = CustomGuardrail
    sys.modules["litellm.integrations.custom_guardrail"] = modulo
    litellm_mod.integrations = integrations
    integrations.custom_guardrail = modulo


_instalar_doble_litellm()

from extensions import basa_guardrail  # noqa: E402

AUDIT_URL = "http://backend:8000/api/v1/internal/audit"
SECRETO = "master-key-de-prueba"

PROMPT_PROHIBIDO = "necesito un social scoring de los socios morosos"
PROMPT_CON_SECRETO = "subí esto: sk-abcdefghij1234567890"
PROMPT_CON_EMAIL = "el contacto es maria.lopez@camara.es, mandale el padrón"
PROMPT_SANO = "resumime el acta de la última reunión"


# ── Dobles ─────────────────────────────────────────────────────────────────────────────

class _Respuesta:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _PlanoInterno:
    """Doble del plano interno del backend: registra lo que recibe y responde una cola.

    Cada cola es una lista de status codes o excepciones; se van consumiendo y el último
    elemento se repite (así un test declara `[503, 200]` para "falla una vez y anda").
    """

    def __init__(self, post=None, get=None):
        self.posts: list = []
        self.gets: list = []
        self._post = list(post or [200])
        self._get = list(get or [200])

    @staticmethod
    def _resolver(cola):
        item = cola.pop(0) if len(cola) > 1 else cola[0]
        if isinstance(item, Exception):
            raise item
        return _Respuesta(item)

    def instalar(self, monkeypatch):
        plano = self

        class _Cliente:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None):
                plano.posts.append({"url": url, "json": json, "headers": headers or {}})
                return plano._resolver(plano._post)

            async def get(self, url, headers=None):
                plano.gets.append({"url": url, "headers": headers or {}})
                return plano._resolver(plano._get)

        monkeypatch.setattr(httpx, "AsyncClient", _Cliente)
        return self


class _Identidad:
    """Lo único que el guardrail lee del `UserAPIKeyAuth` es `.metadata['basa']`."""

    def __init__(self, **basa):
        self.metadata = {"basa": basa} if basa else {}


def _connection(**extra):
    basa = {
        "identity": "connection",
        "key_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "33333333-3333-3333-3333-333333333333",
        "client_id": "22222222-2222-2222-2222-222222222222",
        "group_id": "44444444-4444-4444-4444-444444444444",
        "tool_type": "claude-code",
        "redact_enabled": True,
    }
    basa.update(extra)
    return _Identidad(**basa)


def _body(prompt: str, model: str = "gpt-4o-mini") -> dict:
    return {"model": model, "messages": [{"role": "user", "content": prompt}]}


async def _hook(identidad, data, call_type="acompletion"):
    return await basa_guardrail.BasaGuardrail().async_pre_call_hook(
        identidad, None, data, call_type)


# ── Fixtures ───────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    """Env del perfil prod + estado de módulo limpio.

    El cache del probe y el backoff son globales del módulo: sin resetear, un test se
    llevaría puesto al siguiente (y el backoff real le sumaría 0,2 s a cada reintento)."""
    monkeypatch.setenv("BASA_AUDIT_URL", AUDIT_URL)
    # Nombre de upstream a propósito (#302): es la env que la extensión lee DENTRO
    # del motor. El operador ve BASA_ENGINE_MASTER_KEY y el compose se la pasa bajo
    # ESTE nombre; renombrarla acá deja el test verde contra un secreto no leído.
    monkeypatch.setenv("LITELLM_MASTER_KEY", SECRETO)
    monkeypatch.delenv("BASA_AUDIT_FAIL", raising=False)
    monkeypatch.setattr(basa_guardrail, "_probe_cache", None, raising=False)
    monkeypatch.setattr(basa_guardrail, "_AUDIT_RETRY_BACKOFF_S", 0)
    # Sin NLP configurada el guardrail usa el analyzer regex de dev — determinista y sin
    # red, que es justo lo que un unit test necesita.
    monkeypatch.setattr(basa_guardrail, "_PRESIDIO_URL", None)


@pytest.fixture
def perdidas(monkeypatch):
    """Espía del contador de pérdidas (el Redis real se prueba aparte)."""
    registro: list = []

    async def _fake(motivo):
        registro.append(motivo)

    monkeypatch.setattr(basa_guardrail, "_contar_perdida", _fake)
    return registro


# ── US1: cada punto de bloqueo deja fila ANTES de rechazar ─────────────────────────────

@pytest.mark.asyncio
async def test_bloqueo_ai_act_registra_la_fila_antes_de_rechazar(monkeypatch, perdidas):
    plano = _PlanoInterno().instalar(monkeypatch)

    salida = await _hook(_connection(), _body(PROMPT_PROHIBIDO))

    # El rechazo al cliente no cambia: sigue siendo el str que el hook traduce a 4xx.
    assert isinstance(salida, str) and "Ley de IA" in salida
    assert len(plano.posts) == 1, "el bloqueo tiene que dejar exactamente UNA fila"
    envio = plano.posts[0]
    assert envio["url"] == AUDIT_URL
    assert envio["headers"]["X-Basa-Internal"] == SECRETO, "el plano interno exige el secreto"

    fila = envio["json"]
    assert fila["compliance_status"] == "blocked_prohibited"
    assert fila["compliance_status"].startswith("blocked"), "filtro canónico LIKE 'blocked%'"
    assert fila["blocked_by_layer"] == "ai_act_evaluation"
    # Identidad de la Connection (FR-003): sin esto el officer ve el intento pero no quién.
    assert fila["tenant_id"] == "33333333-3333-3333-3333-333333333333"
    assert fila["user_id"] == "22222222-2222-2222-2222-222222222222"
    assert fila["api_key_id"] == "11111111-1111-1111-1111-111111111111"
    assert fila["user_group_id"] == "44444444-4444-4444-4444-444444444444"
    # Un bloqueo no consume nada: 0 tokens, 0 coste (contrato §Fila de bloqueo).
    assert (fila["prompt_tokens"], fila["completion_tokens"], fila["cost_usd"]) == (0, 0, 0.0)
    assert fila["model"] == "gpt-4o-mini"
    assert perdidas == [], "la escritura anduvo: no hay pérdida que contar"


@pytest.mark.asyncio
async def test_bloqueo_por_secreto_registra_su_capa_sin_nombrar_al_proveedor(
        monkeypatch, perdidas):
    plano = _PlanoInterno().instalar(monkeypatch)

    salida = await _hook(_connection(), _body(PROMPT_CON_SECRETO))

    assert "material secreto" in salida
    fila = plano.posts[0]["json"]
    assert fila["compliance_status"] == "blocked_secret"
    assert fila["blocked_by_layer"] == "secret_detection"
    # C1 + Constitución VII: conteo por tipo GENÉRICO. El catálogo de secretos nombra
    # proveedores ("OpenAI API Key") y esta fila se muestra en una UI white-label.
    assert fila["masked_entities"] == [{"type": "SECRET", "count": 1}]
    serializado = str(fila)
    assert "OpenAI" not in serializado and "sk-abcdefghij" not in serializado


@pytest.mark.asyncio
async def test_bloqueo_por_tipo_de_entidad_registra_conteos_y_deteccion(
        monkeypatch, perdidas):
    plano = _PlanoInterno().instalar(monkeypatch)
    identidad = _connection(entity_configs={"EMAIL_ADDRESS": "BLOCK"})

    salida = await _hook(identidad, _body(PROMPT_CON_EMAIL))

    assert "exige bloquear" in salida
    fila = plano.posts[0]["json"]
    assert fila["compliance_status"] == "blocked_entity_type"
    assert fila["blocked_by_layer"] == "pii_detection"
    assert fila["masked_entities"] == [{"type": "EMAIL_ADDRESS", "count": 1}]
    # Detección confirmada aunque no se enmascarara nada (el pedido se cortó antes): la
    # fila no puede decir "no había datos personales" — D8/FR-002.
    assert fila["pii_detected"] is True
    # Jamás el valor detectado en el registro durable (C1).
    assert "maria.lopez@camara.es" not in str(fila)


@pytest.mark.asyncio
async def test_bloqueo_por_nlp_caido_registra_fila(monkeypatch, perdidas):
    """El fail-closed de la 016 también es un bloqueo: hoy era el más invisible de todos
    (se rechaza el pedido porque no hay garantía de detección… y no queda constancia)."""
    plano = _PlanoInterno().instalar(monkeypatch)
    monkeypatch.setattr(basa_guardrail, "_PRESIDIO_URL", "http://nlp-analyzer:3000")

    async def _caido(*args, **kwargs):
        raise basa_guardrail.policy.NlpUnavailableError("timeout")

    monkeypatch.setattr(basa_guardrail.policy, "presidio_analyze", _caido)

    salida = await _hook(_connection(), _body(PROMPT_CON_EMAIL))

    assert "no está disponible" in salida
    fila = plano.posts[0]["json"]
    assert fila["compliance_status"] == "blocked_nlp_unavailable"
    assert fila["blocked_by_layer"] == "pii_detection"


@pytest.mark.asyncio
async def test_bloqueo_sin_identidad_resoluble_igual_deja_fila(monkeypatch, perdidas):
    """Edge case de la spec: el intento existe aunque no sepamos de quién es. La fila cae
    al tenant por defecto y sin atribución, jamás se pierde."""
    plano = _PlanoInterno().instalar(monkeypatch)

    await _hook(_Identidad(identity="master"), _body(PROMPT_PROHIBIDO))

    fila = plano.posts[0]["json"]
    assert fila["tenant_id"] == "00000000-0000-0000-0000-000000000001"
    # Las claves sin valor NO viajan como null (convención del plano interno + evita 422).
    assert "user_id" not in fila and "api_key_id" not in fila
    assert fila["model"] == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_peticion_sana_no_escribe_fila_de_bloqueo(monkeypatch, perdidas):
    """El camino feliz sigue siendo del logger de éxito: si el guardrail escribiera acá,
    cada pedido byok tendría DOS filas."""
    plano = _PlanoInterno().instalar(monkeypatch)

    salida = await _hook(_connection(), _body(PROMPT_SANO))

    assert isinstance(salida, dict), "una petición sana devuelve el body, no un rechazo"
    assert plano.posts == []


@pytest.mark.asyncio
async def test_call_type_no_inspeccionado_ni_toca_la_auditoria(monkeypatch, perdidas):
    plano = _PlanoInterno().instalar(monkeypatch)

    assert await _hook(_connection(), _body(PROMPT_PROHIBIDO), call_type="embedding") is None
    assert plano.posts == []


# ── US2: la escritura no falla en silencio ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_post_caido_en_open_no_cambia_el_rechazo_y_cuenta_la_perdida(
        monkeypatch, perdidas):
    plano = _PlanoInterno(post=[httpx.ConnectError("backend caído")]).instalar(monkeypatch)

    salida = await _hook(_connection(), _body(PROMPT_PROHIBIDO))

    assert "Ley de IA" in salida, "en `open` el bloqueo se sirve igual: el cliente no ve el fallo"
    assert len(plano.posts) == 2, "1 reintento acotado (D3), ni cero ni una cola infinita"
    assert perdidas == ["guardrail/blocked_prohibited"], "la pérdida queda contada"


@pytest.mark.asyncio
async def test_fallo_transitorio_lo_absorbe_el_reintento(monkeypatch, perdidas):
    plano = _PlanoInterno(post=[503, 200]).instalar(monkeypatch)

    await _hook(_connection(), _body(PROMPT_PROHIBIDO))

    assert len(plano.posts) == 2
    assert perdidas == [], "un 5xx transitorio no es una pérdida: el reintento lo absorbió"


@pytest.mark.asyncio
async def test_un_4xx_no_se_reintenta(monkeypatch, perdidas):
    """Un payload que el plano interno rechaza no se arregla repitiéndolo: reintentarlo
    solo suma latencia al rechazo que el cliente ya está esperando."""
    plano = _PlanoInterno(post=[422]).instalar(monkeypatch)

    await _hook(_connection(), _body(PROMPT_PROHIBIDO))

    assert len(plano.posts) == 1
    assert perdidas == ["guardrail/blocked_prohibited"]


@pytest.mark.asyncio
async def test_sin_url_del_plano_interno_la_perdida_se_cuenta(monkeypatch, perdidas):
    """Motor sin `BASA_AUDIT_URL` = motor sin forma de registrar. Eso es una pérdida
    ruidosa, no un "no hacía falta auditar"."""
    plano = _PlanoInterno().instalar(monkeypatch)
    monkeypatch.delenv("BASA_AUDIT_URL", raising=False)

    salida = await _hook(_connection(), _body(PROMPT_PROHIBIDO))

    assert "Ley de IA" in salida
    assert plano.posts == []
    assert perdidas == ["guardrail/blocked_prohibited"]


@pytest.mark.asyncio
async def test_el_contador_usa_las_claves_canonicas_de_redis(monkeypatch):
    """Mismas claves que el backend (contrato §Contador): el health las lee de un solo
    lugar, venga la pérdida del plano que venga."""
    import redis.asyncio as redis_lib

    comandos: list = []

    class _Pipe:
        def incr(self, key):
            comandos.append(("incr", key))

        def set(self, key, value):
            comandos.append(("set", key, value))

        async def execute(self):
            return True

    class _RedisFalso:
        def __init__(self, *args, **kwargs):
            pass

        def pipeline(self):
            return _Pipe()

        async def aclose(self):
            comandos.append(("aclose",))

    monkeypatch.setattr(redis_lib, "Redis", _RedisFalso)
    _PlanoInterno(post=[500]).instalar(monkeypatch)

    await _hook(_connection(), _body(PROMPT_PROHIBIDO))

    assert ("incr", "basa:audit:lost") in comandos
    assert [c for c in comandos if c[0] == "set" and c[1] == "basa:audit:last_fail"]


@pytest.mark.asyncio
async def test_redis_caido_no_rompe_el_bloqueo(monkeypatch):
    """El contador es best-effort; el piso innegociable es el log. Si el contador
    explotara hacia arriba, un Redis caído convertiría un bloqueo en un 500."""
    import redis.asyncio as redis_lib

    class _RedisExplosivo:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("redis caído")

    monkeypatch.setattr(redis_lib, "Redis", _RedisExplosivo)
    _PlanoInterno(post=[500]).instalar(monkeypatch)

    salida = await _hook(_connection(), _body(PROMPT_PROHIBIDO))

    assert "Ley de IA" in salida


# ── US2: modo closed (FR-005) ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_closed_con_probe_503_rechaza_sin_evaluar_ni_llamar_al_proveedor(
        monkeypatch, perdidas):
    plano = _PlanoInterno(get=[503]).instalar(monkeypatch)
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")

    def _no_deberia_correr(*args, **kwargs):
        raise AssertionError("el corte va ANTES de la política y del proveedor")

    monkeypatch.setattr(basa_guardrail.policy, "evaluate_ai_act", _no_deberia_correr)

    salida = await _hook(_connection(), _body(PROMPT_SANO))

    assert isinstance(salida, str), "un str corta el pedido: el proveedor nunca se llama"
    assert "auditoría no disponible" in salida and "audit_fail=closed" in salida
    assert plano.gets[0]["url"] == AUDIT_URL + "/probe"
    assert plano.gets[0]["headers"]["X-Basa-Internal"] == SECRETO
    assert plano.posts == [], "no hay fila que escribir: la auditoría es justo lo que no anda"


@pytest.mark.asyncio
async def test_closed_con_probe_ok_deja_pasar_el_trafico(monkeypatch, perdidas):
    plano = _PlanoInterno(get=[200]).instalar(monkeypatch)
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")

    salida = await _hook(_connection(), _body(PROMPT_SANO))

    assert isinstance(salida, dict), "auditoría escribible ⇒ el pedido sigue su camino"
    assert len(plano.gets) == 1


@pytest.mark.asyncio
async def test_closed_sin_url_del_plano_interno_rechaza(monkeypatch, perdidas):
    """Fail-closed de verdad: sin forma de preguntar, la respuesta es no."""
    plano = _PlanoInterno().instalar(monkeypatch)
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")
    monkeypatch.delenv("BASA_AUDIT_URL", raising=False)

    salida = await _hook(_connection(), _body(PROMPT_SANO))

    assert "auditoría no disponible" in salida
    assert plano.gets == []


@pytest.mark.asyncio
async def test_open_es_el_default_y_no_consulta_el_probe(monkeypatch, perdidas):
    """En `open` (default del piloto) el pre-check no existe: cero latencia extra por
    pedido en la instalación normal."""
    plano = _PlanoInterno(get=[503]).instalar(monkeypatch)

    salida = await _hook(_connection(), _body(PROMPT_SANO))

    assert isinstance(salida, dict)
    assert plano.gets == []


@pytest.mark.asyncio
async def test_valor_ilegible_de_la_env_degrada_a_open(monkeypatch, perdidas):
    """Un typo en la configuración NUNCA puede convertirse en un corte de servicio: el
    fail-closed es una decisión explícita de la instalación."""
    plano = _PlanoInterno(get=[503]).instalar(monkeypatch)
    monkeypatch.setenv("BASA_AUDIT_FAIL", "Closedd")

    assert isinstance(await _hook(_connection(), _body(PROMPT_SANO)), dict)
    assert plano.gets == []


@pytest.mark.asyncio
async def test_closed_con_la_escritura_caida_devuelve_el_bloqueo_no_el_503(
        monkeypatch, perdidas):
    """Decisión declarada: si el probe pasó pero la escritura del BLOQUEO falla, el
    cliente recibe el motivo real del bloqueo, no el mensaje de auditoría. El pedido se
    estaba rechazando igual —no hay tráfico servido sin registro, que es lo que `closed`
    protege— y decirle "auditoría caída" a quien intentó filtrar un secreto sería peor
    información. La pérdida queda contada y logueada."""
    _PlanoInterno(get=[200], post=[500]).instalar(monkeypatch)
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")

    salida = await _hook(_connection(), _body(PROMPT_CON_SECRETO))

    assert "material secreto" in salida
    assert perdidas == ["guardrail/blocked_secret"]


@pytest.mark.asyncio
async def test_el_probe_se_cachea_5s_y_expira(monkeypatch, perdidas):
    """Riesgo R2 del research: el probe corre en el pre-call de CADA pedido del plano
    agentic; sin cache, una caída se paga con un round-trip extra por pedido."""
    plano = _PlanoInterno(get=[200]).instalar(monkeypatch)
    monkeypatch.setenv("BASA_AUDIT_FAIL", "closed")

    # Se reemplaza la REFERENCIA al módulo `time` dentro de la extensión, no
    # `time.monotonic` global: congelarle el reloj al proceso entero le mueve el piso al
    # scheduler de asyncio, que también lo usa.
    reloj = {"t": 1000.0}

    class _RelojFalso:
        @staticmethod
        def monotonic():
            return reloj["t"]

    monkeypatch.setattr(basa_guardrail, "time", _RelojFalso())

    await _hook(_connection(), _body(PROMPT_SANO))
    await _hook(_connection(), _body(PROMPT_SANO))
    assert len(plano.gets) == 1, "dentro de la ventana el probe se responde de cache"

    reloj["t"] += basa_guardrail._AUDIT_PROBE_CACHE_TTL_S + 0.1
    await _hook(_connection(), _body(PROMPT_SANO))
    assert len(plano.gets) == 2, "vencida la ventana se vuelve a preguntar"
