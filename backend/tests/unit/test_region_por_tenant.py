"""`region`: el resolutor compartido y el plano MOTOR (H1/H5 del gate adversarial de #137).

Mismo molde que `test_nlp_fail_mode.py` (issue #63), aplicado a `region`. El propio gate lo
verificó con mutación: revertir el guardrail a env-only + quitar la propagación de
custom_auth + romper las DOS copias del SQL + quitar el seed ⇒ **281 passed, nada moría** —
los tests que trajo el PR original sólo cubrían la función pura `resolve_region`. Estas son
las 3 familias que faltaban, calcadas del molde de `nlp_fail_mode`:

1. Las DOS copias del SQL de identidad (`custom_auth`/`internal.py`) traen `region`.
2. `custom_auth` propaga el valor CRUDO a la identidad que recibe el motor.
3. El motor (BasaGuardrail) OBEDECE la región del tenant, no sólo el default de la
   instalación — con mutación explícita: revertir `basa_guardrail.py` a
   `region = os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION)` (env-only, sin
   `policy.resolve_region(identity, ...)`) tiene que dejar estos tests en rojo.

El plano `/gw` (+ navegador, que reusa el mismo `_build_analyze`) se cubre en
`tests/integration/test_gateway_nlp_paridad.py` (Postgres); el Playground en
`tests/unit/test_guardian_service_nlp.py` / `tests/unit/test_guardian_seed_region.py`.
"""
import sys
import types

import httpx
import pytest


# ── Doble de litellm.integrations.custom_guardrail (mismo patrón que test_nlp_fail_mode.py) ──
def _instalar_doble_litellm():
    if "litellm.integrations.custom_guardrail" in sys.modules:
        return

    class CustomGuardrail:
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


def _instalar_doble_proxy_types():
    if "litellm.proxy._types" in sys.modules:
        return

    class UserAPIKeyAuth:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class LitellmUserRoles:
        PROXY_ADMIN = "proxy_admin"

    litellm_mod = sys.modules.setdefault("litellm", types.ModuleType("litellm"))
    proxy_mod = sys.modules.setdefault("litellm.proxy", types.ModuleType("litellm.proxy"))
    mod = types.ModuleType("litellm.proxy._types")
    mod.UserAPIKeyAuth = UserAPIKeyAuth
    mod.LitellmUserRoles = LitellmUserRoles
    sys.modules["litellm.proxy._types"] = mod
    litellm_mod.proxy = proxy_mod
    proxy_mod._types = mod


_instalar_doble_litellm()

from extensions import basa_guardrail  # noqa: E402

# Misma librería compartida QUE USA EL GUARDRAIL (no un `from extensions import
# basa_guardian_policy` propio) — dos caminos de import producen objetos-módulo DISTINTOS y
# la `NlpUnavailableError` de un doble no sería la misma clase que el guardrail captura.
policy = basa_guardrail.policy

SECRETO = "master-key-de-prueba"
ANALYZER = "http://nlp-analyzer:3000"
PROMPT = "escribile a maria.lopez@camara.es antes del viernes"


# ── 1) Las DOS copias del SQL de identidad traen `region` ─────────────────────────


def test_las_dos_copias_del_sql_de_identidad_traen_region():
    """`custom_auth._IDENTITY_SQL` (base compartida) y `internal._IDENTITY_SQL` (plano
    interno) son ESPEJOS declarados. Si una trae `region` y la otra no, qué identificadores
    de qué país se detectan depende de qué env está cableada en el despliegue — el mismo
    bug de clase que el #76 (presupuesto) y el #63 (nlp_fail_mode) ya dejaron."""
    from src.api.internal import _IDENTITY_SQL as sql_interno

    _instalar_doble_proxy_types()
    from extensions import custom_auth

    for nombre, sql in (("custom_auth", custom_auth._IDENTITY_SQL),
                        ("internal", str(sql_interno))):
        assert "region" in sql, f"{nombre} no propaga la región del tenant"
        # `->>` y no `->`: el consumidor (`resolve_region`) compara contra un str del
        # vocabulario de STRUCTURED_ID_PATTERNS_BY_REGION; un valor JSON entrecomillado no
        # matchearía nunca (fallaría silencioso hacia el default).
        assert "config->>'region'" in sql, f"{nombre} lo lee como JSON, no como texto"


# ── 2) `custom_auth` propaga el valor CRUDO a la identidad del motor ──────────────


def test_custom_auth_propaga_la_region_cruda_a_la_identidad(monkeypatch):
    """El motor recibe el valor SIN normalizar: quien decide es `resolve_region`, con el
    default de instalación armado por el guardrail — normalizar acá sería una segunda
    copia de esa decisión (mismo criterio que `nlp_fail_mode`)."""
    _instalar_doble_proxy_types()
    from extensions import custom_auth

    fila = {
        "key_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": None, "username": "cliente", "group_id": None,
        "tool_type": "claude-code", "upstream_mode": "byok", "is_active": True,
        "region": "latam_ar",
    }

    async def _fake_lookup(_key_hash):
        return fila

    monkeypatch.setattr(custom_auth, "_lookup_identity", _fake_lookup)
    custom_auth._cache.clear()

    class _Request:
        headers = {}

    import asyncio
    auth = asyncio.get_event_loop().run_until_complete(
        custom_auth.user_api_key_auth(_Request(), "sk-basa-de-prueba"))

    assert auth.metadata["basa"]["region"] == "latam_ar"


def test_custom_auth_sin_region_propaga_none(monkeypatch):
    """Retrocompatibilidad: una Connection de antes de este PR no tiene `region` en la fila
    (columna ausente en el `SELECT`, no NULL explícito) — `custom_auth` no puede inventar un
    valor: el guardrail decide el default con `resolve_region(identity, default=env)`."""
    _instalar_doble_proxy_types()
    from extensions import custom_auth

    fila = {
        "key_id": "22222222-2222-2222-2222-222222222222",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": None, "username": "cliente", "group_id": None,
        "tool_type": "claude-code", "upstream_mode": "byok", "is_active": True,
    }

    async def _fake_lookup(_key_hash):
        return fila

    monkeypatch.setattr(custom_auth, "_lookup_identity", _fake_lookup)
    custom_auth._cache.clear()

    class _Request:
        headers = {}

    import asyncio
    auth = asyncio.get_event_loop().run_until_complete(
        custom_auth.user_api_key_auth(_Request(), "sk-basa-de-prueba"))

    assert auth.metadata["basa"].get("region") is None


# ── 3) El motor OBEDECE la región del tenant (mutación: env-only tiene que romper esto) ──


class _Respuesta:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class _PlanoInterno:
    """Doble del plano interno del backend: guarda las filas que el motor POSTea."""

    def __init__(self):
        self.posts: list = []

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
                plano.posts.append(json)
                return _Respuesta(200)

            async def get(self, url, headers=None):
                return _Respuesta(200)

        monkeypatch.setattr(httpx, "AsyncClient", _Cliente)
        return self


class _Identidad:
    def __init__(self, **basa):
        self.metadata = {"basa": basa}


def _connection(**extra):
    basa = {
        "identity": "connection",
        "key_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "33333333-3333-3333-3333-333333333333",
        "redact_enabled": True,
    }
    basa.update(extra)
    return _Identidad(**basa)


def _body(prompt: str = PROMPT) -> dict:
    return {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}]}


async def _hook(identidad, data, call_type="acompletion"):
    return await basa_guardrail.BasaGuardrail().async_pre_call_hook(
        identidad, None, data, call_type)


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", SECRETO)
    monkeypatch.setattr(basa_guardrail, "_probe_cache", None, raising=False)
    monkeypatch.setattr(basa_guardrail, "_PRESIDIO_URL", ANALYZER)


@pytest.mark.asyncio
async def test_motor_usa_la_region_del_tenant_no_solo_el_default_de_instalacion(monkeypatch):
    """Con `BASA_ENTITY_REGION` AUSENTE (default del código, `eu`) pero el tenant con
    `region: latam_ar` en su identidad, el analyzer real tiene que recibir `latam_ar` — no
    el default de la instalación. MUTACIÓN que este test mata: revertir la línea de
    `basa_guardrail.py` a `region = os.environ.get("BASA_ENTITY_REGION", policy.DEFAULT_REGION)`
    (env-only, sin `policy.resolve_region(identity, ...)`) deja este test en rojo."""
    monkeypatch.delenv("BASA_ENTITY_REGION", raising=False)
    _PlanoInterno().instalar(monkeypatch)
    capturada = {}

    async def _analyze_espia(text, analyzer_url, custom_names, region, **kwargs):
        capturada["region"] = region
        return []

    monkeypatch.setattr(basa_guardrail.policy, "presidio_analyze", _analyze_espia)

    salida = await _hook(_connection(region="latam_ar"), _body())

    assert isinstance(salida, dict), "el pedido tiene que procesarse (no hay bloqueo en juego)"
    assert capturada.get("region") == "latam_ar", (
        "el guardrail no propagó la región del tenant al analyzer — se quedó en el default "
        "de la instalación (mutación: volver a env-only)")


@pytest.mark.asyncio
async def test_motor_sin_region_propia_cae_al_default_de_instalacion(monkeypatch):
    """Contracara de retrocompatibilidad: sin `region` en la identidad (Connection de antes
    de este PR), el motor sigue resolviendo `BASA_ENTITY_REGION` — el comportamiento no
    cambia para nadie que no fijó región propia."""
    monkeypatch.setenv("BASA_ENTITY_REGION", "latam_ar")
    _PlanoInterno().instalar(monkeypatch)
    capturada = {}

    async def _analyze_espia(text, analyzer_url, custom_names, region, **kwargs):
        capturada["region"] = region
        return []

    monkeypatch.setattr(basa_guardrail.policy, "presidio_analyze", _analyze_espia)

    salida = await _hook(_connection(), _body())

    assert isinstance(salida, dict)
    assert capturada.get("region") == "latam_ar"


@pytest.mark.asyncio
async def test_degrade_resuelve_la_region_del_tenant_no_el_default_de_instalacion(monkeypatch):
    """H1 del gate: «un degrade que pierde la región es la falla silenciosa clásica, justo
    cuando el sistema ya está en problemas». Con el analyzer real CAÍDO y la instalación en
    `degrade`, el regex de dev (`policy.default_analyze`) tiene que recibir la región del
    TENANT, no el default de la instalación.

    Se espía `default_analyze` en vez de afirmar sobre qué patrones detecta (`FALLBACK_
    STRUCTURED_BY_REGION` hoy sólo tiene datos para `eu` — es un hueco de datos/patrones
    conocido y FUERA de alcance de este PR, no del wiring que este test defiende): lo que
    importa acá es que la región LLEGA, no si ya hay reconocedores cargados para ella.

    MUTACIÓN que este test mata: los `_analyze = policy.default_analyze` SIN bindear
    `region` (el estado de `basa_guardrail.py` antes de este PR) dejan este test en rojo."""
    monkeypatch.delenv("BASA_ENTITY_REGION", raising=False)
    _PlanoInterno().instalar(monkeypatch)

    async def _caido(*_a, **_k):
        raise policy.NlpUnavailableError("connection refused")

    monkeypatch.setattr(basa_guardrail.policy, "presidio_analyze", _caido)

    capturada = {}
    original_default_analyze = policy.default_analyze

    async def _default_analyze_espia(text, region=policy.DEFAULT_REGION):
        capturada["region"] = region
        return await original_default_analyze(text, region=region)

    monkeypatch.setattr(basa_guardrail.policy, "default_analyze", _default_analyze_espia)

    salida = await _hook(_connection(region="latam_ar", nlp_fail_mode="degrade"), _body())

    assert isinstance(salida, dict), "con `degrade` el pedido no se rechaza"
    assert capturada.get("region") == "latam_ar", (
        "el camino degrade se quedó en el default de la instalación — perdió la región del "
        "tenant justo cuando el sistema ya estaba en problemas")
