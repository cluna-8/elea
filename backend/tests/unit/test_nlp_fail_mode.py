"""`nlp_fail_mode`: el resolutor compartido y el plano MOTOR (issue #63).

El issue denuncia una degradación silenciosa a regex cuando el analyzer NLP no está. La
respuesta del producto tiene dos piezas y las dos se fijan acá:

1. **El resolutor es UNO** (`policy.resolve_nlp_fail_mode`) y su default es `block`. Esto no
   es una preferencia de estilo: es el Principio I regla (d) de la constitución («nunca solo
   regex en producción con PHI»). Una clave ausente, vacía o mal tipeada NO puede terminar en
   "seguí sirviendo con media protección" — degradar tiene que ser una decisión escrita.
2. **El motor obedece esa política** en sus DOS puntos de caída (el preview de entidades y el
   enmascarado real), y cuando degrada lo hace RUIDOSO: fila durable con estado propio, marca
   de estado en Redis y `logger.error`. Antes del fix el motor sólo sabía bloquear; ahora sabe
   las dos cosas, pero ninguna en silencio.

El plano `/gw` (la otra mitad del issue) se cubre en
`tests/integration/test_gateway_nlp_paridad.py`, que necesita Postgres.
"""
import sys
import types
from pathlib import Path

import httpx
import pytest


# ── Doble de litellm.integrations.custom_guardrail (mismo patrón que test_guardrail_block_audit) ──
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


def _instalar_doble_custom_logger():
    """`basa_audit_logger` hereda de OTRA base del SDK (`custom_logger`). Se dobla aparte
    para no cargarla en los tests que sólo necesitan el guardrail."""
    if "litellm.integrations.custom_logger" in sys.modules:
        return

    class CustomLogger:
        def __init__(self, *args, **kwargs):
            pass

    modulo = types.ModuleType("litellm.integrations.custom_logger")
    modulo.CustomLogger = CustomLogger
    sys.modules["litellm.integrations.custom_logger"] = modulo
    sys.modules["litellm.integrations"].custom_logger = modulo


_instalar_doble_litellm()

from extensions import basa_guardrail  # noqa: E402

# La librería compartida se toma DEL GUARDRAIL, no con un `from extensions import
# basa_guardian_policy` propio. Los dos caminos de import producen objetos-módulo DISTINTOS
# (`basa_guardian_policy` vs `extensions.basa_guardian_policy`, según qué entrada de
# `sys.path` los resolvió), y con dos copias la `NlpUnavailableError` que levantaría el doble
# no es la misma clase que el guardrail captura: el test fallaría por plomería y no por el
# comportamiento. Es la misma referencia que ya usa `test_guardrail_block_audit.py`.
policy = basa_guardrail.policy

AUDIT_URL = "http://backend:8000/api/v1/internal/audit"
SECRETO = "master-key-de-prueba"
ANALYZER = "http://nlp-analyzer:3000"
PROMPT = "escribile a maria.lopez@camara.es antes del viernes"


# ── 1) El resolutor compartido ────────────────────────────────────────────────────


@pytest.mark.parametrize("config, esperado, motivo", [
    ({"nlp_fail_mode": "block"}, "block", "valor explícito"),
    ({"nlp_fail_mode": "degrade"}, "degrade", "valor explícito"),
    ({"nlp_fail_mode": "BLOCK"}, "block", "mayúsculas: el vocabulario no es case-sensitive"),
    ({"nlp_fail_mode": " degrade "}, "degrade", "espacios de un copy/paste del panel"),
    ({}, "block", "CLAVE AUSENTE — instalaciones anteriores al fix, sin migración"),
    ({"nlp_fail_mode": None}, "block", "clave presente en null (columna sin valor)"),
    ({"nlp_fail_mode": ""}, "block", "cadena vacía (campo borrado en la UI)"),
    ({"nlp_fail_mode": "degradar"}, "block", "typo del admin"),
    ({"nlp_fail_mode": "off"}, "block", "vocabulario de OTRO toggle copiado por error"),
    ({"nlp_fail_mode": True}, "block", "tipo no-string"),
    ({"nlp_fail_mode": ["degrade"]}, "block", "estructura en vez de escalar"),
    (None, "block", "sin config en absoluto (guardián ilegible)"),
])
def test_resolve_nlp_fail_mode(config, esperado, motivo):
    """Todo lo que no sea un `degrade` legible resuelve `block`. La lista de basura es larga
    a propósito: el default fail-closed sólo vale algo si aguanta la entrada real (una
    columna en null, un campo vaciado, un typo), no sólo la ausencia limpia de la clave."""
    assert policy.resolve_nlp_fail_mode(config) == esperado, motivo


def test_el_resolutor_acepta_el_dict_de_identidad_del_motor():
    """El motor no tiene el `Guardian.config` en la mano: recibe la identidad que arma
    `custom_auth`, que transporta la MISMA clave. Que las dos formas entren por la misma
    puerta es lo que garantiza que los dos planos no puedan divergir."""
    identidad = {"tenant_id": "x", "redact_enabled": True, "nlp_fail_mode": "degrade"}
    assert policy.resolve_nlp_fail_mode(identidad) == "degrade"


def test_el_vocabulario_de_estados_es_compartido():
    """Las dos palabras que terminan en `audit_logs.compliance_status` viven en la librería
    compartida, no duplicadas por plano: si un plano inventara la suya, la misma situación
    aparecería con dos nombres en la auditoría."""
    assert policy.STATUS_NLP_BLOCKED == "blocked_nlp_unavailable"
    assert policy.STATUS_NLP_DEGRADED == "degraded_nlp_regex"
    assert policy.STATUS_NLP_BLOCKED.startswith("blocked"), "filtro canónico LIKE 'blocked%'"
    assert not policy.STATUS_NLP_DEGRADED.startswith("blocked"), (
        "una request degradada SE SIRVIÓ: contarla entre los bloqueos falsearía el tablero")


# ── Dobles del plano motor ────────────────────────────────────────────────────────


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
    monkeypatch.setenv("BASA_AUDIT_URL", AUDIT_URL)
    # Nombre de upstream a propósito (#302): es la env que la extensión lee DENTRO
    # del motor. El operador ve BASA_ENGINE_MASTER_KEY y el compose se la pasa bajo
    # ESTE nombre; renombrarla acá deja el test verde contra un secreto no leído.
    monkeypatch.setenv("LITELLM_MASTER_KEY", SECRETO)
    monkeypatch.delenv("BASA_AUDIT_FAIL", raising=False)
    monkeypatch.setattr(basa_guardrail, "_probe_cache", None, raising=False)
    monkeypatch.setattr(basa_guardrail, "_AUDIT_RETRY_BACKOFF_S", 0)
    monkeypatch.setattr(basa_guardrail, "_PRESIDIO_URL", ANALYZER)


@pytest.fixture
def marcas(monkeypatch):
    """Espía de la marca de estado en Redis (el cliente real se prueba en el backend)."""
    registro: list = []

    async def _fake():
        registro.append("degradado")

    monkeypatch.setattr(basa_guardrail, "_marcar_nlp_degradado", _fake)
    return registro


@pytest.fixture
def analyzer_caido(monkeypatch):
    async def _caido(*args, **kwargs):
        raise policy.NlpUnavailableError("connection refused")

    monkeypatch.setattr(basa_guardrail.policy, "presidio_analyze", _caido)


# ── 2) El motor obedece la política ───────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("identidad_extra, caso", [
    ({"nlp_fail_mode": "block"}, "explícito"),
    ({}, "clave AUSENTE — la Connection de una instalación anterior al fix"),
    ({"nlp_fail_mode": "basura"}, "valor no reconocido"),
])
async def test_motor_con_block_rechaza_y_registra(monkeypatch, marcas, analyzer_caido,
                                                  identidad_extra, caso):
    """El comportamiento de la 016 no cambia para nadie que no lo haya pedido: sin NLP no se
    procesa, y la fila durable queda igual que antes."""
    plano = _PlanoInterno().instalar(monkeypatch)

    salida = await _hook(_connection(**identidad_extra), _body())

    assert isinstance(salida, str) and "no está disponible" in salida, caso
    assert plano.posts[0]["compliance_status"] == "blocked_nlp_unavailable", caso
    assert plano.posts[0]["blocked_by_layer"] == "pii_detection", caso
    assert marcas == [], f"{caso}: un bloqueo no es una degradación — no se marca como tal"


@pytest.mark.asyncio
async def test_motor_con_degrade_sirve_con_regex_y_lo_marca(monkeypatch, marcas,
                                                            analyzer_caido):
    """`degrade`: el pedido sigue (devuelve `data`, no un str de rechazo), enmascarado con el
    regex de dev, y el hecho queda en los tres canales del contrato del #63."""
    _PlanoInterno().instalar(monkeypatch)
    data = _body()

    salida = await _hook(_connection(nlp_fail_mode="degrade"), data)

    assert isinstance(salida, dict), "con `degrade` el pedido NO se rechaza"
    # El regex sí caza el email: degradar protege lo que puede, no baja los brazos.
    assert "maria.lopez@camara.es" not in str(salida["messages"])
    home = salida.get("metadata") or salida.get("litellm_metadata") or {}
    assert home["basa_compliance"]["status"] == "degraded_nlp_regex", (
        "sin este estado, el emisor de éxito escribiría la fila como una transacción normal "
        "y la degradación sería invisible en la auditoría — que es el issue #63")
    assert home["pii_tokens"], "el mapa reversible tiene que existir para poder des-enmascarar"
    assert marcas == ["degradado"], "la degradación tiene que quedar consultable en el estado"


@pytest.mark.asyncio
async def test_degrade_no_saltea_el_bloqueo_por_tipo_de_entidad(monkeypatch, marcas,
                                                                analyzer_caido):
    """Degradar el DETECTOR no puede degradar la POLÍTICA: si el admin configuró que un tipo
    se bloquea, se sigue bloqueando con lo que el regex encuentre. Sin esto, tirar abajo el
    sidecar sería la forma de saltearse las reglas de bloqueo por tipo."""
    plano = _PlanoInterno().instalar(monkeypatch)
    identidad = _connection(nlp_fail_mode="degrade",
                            entity_configs={"EMAIL_ADDRESS": "BLOCK"})

    salida = await _hook(identidad, _body())

    assert isinstance(salida, str) and "exige bloquear" in salida
    assert plano.posts[0]["compliance_status"] == "blocked_entity_type"
    assert marcas == ["degradado"], "la degradación ocurrió igual y se marca igual"


@pytest.mark.asyncio
async def test_degrade_que_cae_a_mitad_del_masking_conserva_un_solo_mapa(monkeypatch,
                                                                         marcas):
    """El caso peligroso: el analyzer contesta el preview y se cae DENTRO de `mask_body`, con
    parte del body ya enmascarada. Reanudar con un `PlaceholderMap` nuevo dejaría esos
    placeholders sin original y saldrían crudos al cliente."""
    _PlanoInterno().instalar(monkeypatch)
    estado = {"n": 0}

    async def _muere_despues_del_preview(text, *_a, **_k):
        estado["n"] += 1
        if estado["n"] >= 3:  # 1: preview, 2: primer turno, 3: se cae
            raise policy.NlpUnavailableError("se cayó a mitad de camino")
        i = text.find("Ana Torres")
        return [] if i < 0 else [{"start": i, "end": i + len("Ana Torres"),
                                  "entity_type": "PERSON", "score": 0.9}]

    monkeypatch.setattr(basa_guardrail.policy, "presidio_analyze", _muere_despues_del_preview)
    data = {"model": "gpt-4o-mini", "messages": [
        {"role": "user", "content": "primero: Ana Torres"},
        {"role": "user", "content": "segundo: a@b.es"},
    ]}

    salida = await _hook(_connection(nlp_fail_mode="degrade"), data)

    assert isinstance(salida, dict)
    home = salida.get("metadata") or salida.get("litellm_metadata") or {}
    tokens = home.get("pii_tokens") or {}
    assert "Ana Torres" not in str(salida["messages"]), (
        "lo que el NLP alcanzó a enmascarar no puede volver a salir en claro")
    assert "a@b.es" not in str(salida["messages"])
    nonces = {ph.rstrip("]").split("_")[-1] for ph in tokens}
    assert len(nonces) == 1, f"el body quedó con mapas distintos: {nonces}"
    # Y el mapa cubre TODO lo enmascarado: si faltara una entrada, ese placeholder llegaría
    # crudo al usuario final y el valor original sería irrecuperable.
    assert len(tokens) == 2, tokens


@pytest.mark.asyncio
async def test_con_analyzer_sano_no_hay_marca_de_degradacion(monkeypatch, marcas):
    """Contracara obligatoria: el camino sano no puede ensuciar el estado. Un indicador que
    se enciende siempre no informa nada y el operador aprende a ignorarlo."""
    _PlanoInterno().instalar(monkeypatch)

    async def _sano(text, *_a, **_k):
        return []

    monkeypatch.setattr(basa_guardrail.policy, "presidio_analyze", _sano)

    salida = await _hook(_connection(nlp_fail_mode="degrade"), _body())

    assert isinstance(salida, dict)
    assert marcas == []


# ── 3) Las DOS copias del SQL de identidad traen la clave ─────────────────────────


def test_las_dos_copias_del_sql_de_identidad_traen_nlp_fail_mode():
    """`custom_auth._IDENTITY_SQL` (base compartida) y `internal._IDENTITY_SQL` (plano
    interno) son ESPEJOS declarados. Si una trae `nlp_fail_mode` y la otra no, la postura del
    admin depende de qué env está cableada en el despliegue y el bug del #63 —degradar sin
    que nadie lo haya decidido— renace por el camino que no la lleva. Este test es barato y
    ataja exactamente esa clase de deriva, que ya pasó antes con el presupuesto (#76)."""
    from src.api.internal import _IDENTITY_SQL as sql_interno

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

    _instalar_doble_proxy_types()
    from extensions import custom_auth

    for nombre, sql in (("custom_auth", custom_auth._IDENTITY_SQL),
                        ("internal", str(sql_interno))):
        assert "nlp_fail_mode" in sql, f"{nombre} no propaga la postura ante el NLP caído"
        # `->>` y no `->`: el consumidor compara contra un str del vocabulario cerrado, y un
        # valor JSON entrecomillado no matchearía nunca (fallaría silencioso hacia `block`).
        assert "config->>'nlp_fail_mode'" in sql, f"{nombre} lo lee como JSON, no como texto"


# ── 4) El motor y el backend escriben/leen el MISMO Redis ────────────────────────


def test_el_default_de_redis_del_motor_coincide_con_el_del_backend():
    """Las marcas del #63 (`basa:nlp:*`) y el contador de la 031 (`basa:audit:*`) los ESCRIBE
    el motor y los LEE el backend. Compartir las claves no sirve de nada si cada plano las
    escribe en un host distinto: el health contaría cero con el sidecar caído, que es
    exactamente la promesa que el issue viene a cumplir. El default del motor decía `redis`
    (el nombre del servicio del compose de DEV) y el del backend `eu-redis`.

    La otra mitad de este fix —que el perfil de producción le PASE `REDIS_HOST`/`REDIS_PORT`
    al servicio del motor— no se puede afirmar desde acá: el contenedor de la suite sólo
    monta `backend/` y `litellm/`, no la raíz del repo. Vive en
    `deploy/release/checks/test_redis_wiring.sh` (gate de release), que sí ve los compose."""
    import inspect as _inspect

    # El logger de auditoría necesita SU propia base del SDK (otro módulo de litellm).
    _instalar_doble_custom_logger()
    from extensions import basa_audit_logger
    from src.services import redis_client

    fuente = _inspect.getsource(redis_client.get_redis)
    assert f'"{basa_guardrail._REDIS_HOST_DEFAULT}"' in fuente, (
        f"el motor default-ea a {basa_guardrail._REDIS_HOST_DEFAULT!r} y el backend a otra "
        "cosa: escribirían y leerían en instancias distintas")
    # Y los dos emisores del motor comparten el mismo valor entre sí.
    assert basa_audit_logger._REDIS_HOST_DEFAULT == basa_guardrail._REDIS_HOST_DEFAULT


def test_custom_auth_propaga_la_postura_cruda_a_la_identidad(monkeypatch):
    """El motor recibe el valor SIN normalizar: quien decide es `resolve_nlp_fail_mode`, y
    ese default tiene que vivir en UN solo lugar para los dos planos. Normalizar acá sería
    la segunda copia de la decisión."""
    from extensions import custom_auth

    fila = {
        "key_id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "user_id": None, "username": "cliente", "group_id": None,
        "tool_type": "claude-code", "upstream_mode": "byok", "is_active": True,
        "nlp_fail_mode": "degrade",
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

    assert auth.metadata["basa"]["nlp_fail_mode"] == "degrade"


# ── 5) presidio_analyze no queda mudo ante un fallo (issue #167, sub-fix 1) ──────


class _ClienteQueRevienta:
    """Doble de httpx.AsyncClient cuyo `post` levanta la excepción real de httpx —
    incluido el caso, real en prod, de un timeout SIN mensaje (`str(e) == ""`)."""

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, timeout=None):
        raise httpx.ReadTimeout("")  # str(e) vacío: así llega un timeout real de httpx


@pytest.mark.asyncio
async def test_presidio_analyze_no_queda_mudo_ante_timeout_sin_mensaje(monkeypatch):
    """Antes del fix: `str(httpx.ReadTimeout(""))` es `""`, y el except armaba el
    `NlpUnavailableError` (y el WARNING) directo con eso — el operador veía un fallo
    sin causa ni cuánto tardó. Ahora el tipo de excepción y el elapsed van SIEMPRE en
    el mensaje, la tenga o no la excepción original."""
    monkeypatch.setattr(httpx, "AsyncClient", _ClienteQueRevienta)

    with pytest.raises(policy.NlpUnavailableError) as excinfo:
        await policy.presidio_analyze("hola", ANALYZER, [])

    mensaje = str(excinfo.value)
    assert mensaje, "el mensaje no puede quedar vacío — eso es exactamente el bug mudo"
    assert "ReadTimeout" in mensaje, "el tipo de excepción tiene que quedar en el mensaje"
    assert ANALYZER in mensaje, "hay que saber CONTRA QUÉ analyzer falló"
