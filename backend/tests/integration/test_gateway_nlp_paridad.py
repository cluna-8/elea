"""Paridad NLP y política ante el analyzer caído en el plano `/gw` (issue #63).

El bug que estos tests fijan es doble, y las dos mitades eran invisibles:

1. **Paridad rota**: `/gw` corría SIEMPRE `policy.default_analyze` (el regex de dev), aunque
   `NLP_ANALYZER_URL` estuviera configurada y el sidecar sano — mientras el motor, por la
   ruta byok, sí usaba el NLP real. El mismo prompt salía enmascarado por un camino y
   sub-enmascarado por el otro, y el docstring del módulo prometía «paridad EXACTA».
2. **Degradación silenciosa**: sin nada que gobernara qué pasa cuando el detector real se
   cae, ningún test de la suite fallaba si el NLP desaparecía (criterio 3 del issue).

Lo que se afirma acá es comportamiento observable —qué se enmascara, qué se rechaza, qué
queda escrito en `audit_logs` y qué queda marcado en Redis—, nunca la forma interna. El
sidecar NLP se dobla al nivel de `policy.presidio_analyze` (la frontera de red de la
librería compartida), que es donde el motor también lo dobla en sus propios tests.
"""
import json
import re
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_gateway_nlp"
GW = "/api/v1/gw/v1/messages"
ANALYZER = "http://nlp-analyzer:3000"

# Nombre que el NLP real detecta (NER) y el regex de dev NO: el patrón `PERSON` del fallback
# exige un tratamiento previo ("sr.", "dra."). Es exactamente la clase de PII que se escapaba
# por `/gw` mientras el motor la enmascaraba — el test discrimina los dos detectores por su
# resultado, no por qué función se llamó.
NOMBRE = "Marta Iglesias"
PROMPT = f"revisá el expediente de {NOMBRE}, urgente"


def _cuerpo(texto: str = PROMPT) -> dict:
    return {"model": "claude-3-5-sonnet-20241022",
            "messages": [{"role": "user", "content": texto}]}


# ── Dobles ────────────────────────────────────────────────────────────────────────


class _RespuestaFalsa:
    status_code = 200
    headers = {"content-type": "application/json"}
    content = json.dumps({"content": [{"type": "text", "text": "ok"}],
                          "usage": {"input_tokens": 3, "output_tokens": 2}}).encode()

    def json(self):
        return json.loads(self.content)


class _ClienteFalso:
    def __init__(self, registro):
        self._registro = registro

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, url, **kwargs):
        # Se guarda el BODY que salió al proveedor: es la única forma honesta de afirmar
        # "esto se enmascaró antes de salir" — mirar el enmascarado por dentro sería
        # testear la implementación, no la garantía.
        self._registro.append({"url": url, "content": kwargs.get("content")})
        return _RespuestaFalsa()


class _HttpxEspia:
    def __init__(self):
        self.llamadas = []

    def AsyncClient(self, *_args, **_kwargs):  # noqa: N802 — espeja el nombre real
        return _ClienteFalso(self.llamadas)


class _RedisFalso:
    """Sólo lo que usan `record_nlp_degradation` / `read_nlp_degradation`."""

    def __init__(self):
        self.datos = {}

    def set(self, key, value, nx=False):
        if nx and key in self.datos:
            return False
        self.datos[key] = value
        return True

    def incr(self, key):
        self.datos[key] = int(self.datos.get(key, 0)) + 1
        return self.datos[key]

    def get(self, key):
        valor = self.datos.get(key)
        return None if valor is None else str(valor)

    def delete(self, *keys):
        for k in keys:
            self.datos.pop(k, None)

    # El emisor de la vitrina usa pipeline(); acá no interesa, pero tiene que no explotar.
    def pipeline(self):
        return self

    def lpush(self, *_a, **_k):
        return self

    def ltrim(self, *_a, **_k):
        return self

    def expire(self, *_a, **_k):
        return self

    def execute(self):
        return []


# ── Fixtures ──────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def sesion_del_gateway(harness, monkeypatch):
    """`gateway` abre sus PROPIAS sesiones (`SessionLocal`): sin este patch los tests
    escribirían en la base del compose."""
    _, factory = harness
    from src.api import gateway
    monkeypatch.setattr(gateway, "SessionLocal", factory)
    return factory


@pytest.fixture(autouse=True)
def proveedor(monkeypatch):
    from src.api import gateway
    espia = _HttpxEspia()
    monkeypatch.setattr(gateway, "httpx", espia)
    return espia


@pytest.fixture(autouse=True)
def redis_falso(monkeypatch):
    """Redis en memoria para la marca de degradación. Se parchea en el módulo que la
    ESCRIBE (`audit_service`), que es el único que la toca en este plano."""
    from src.services import audit_service
    falso = _RedisFalso()
    monkeypatch.setattr(audit_service, "get_redis", lambda: falso)
    return falso


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    from src.services import audit_service
    monkeypatch.setattr(audit_service, "_wait", lambda _s: None)


@pytest.fixture(autouse=True)
def limpiar_filas(harness):
    _, factory = harness
    from src.models.audit import AuditLog
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def guardian_pii(harness):
    """Escribe el guardián `pii_masking` del tenant por defecto con la config pedida.

    Se usa la fila REAL y no un mock de `_nlp_context`: el canal por el que la postura del
    admin llega al plano de tráfico es parte de lo que el #63 arregla (antes ese canal no
    existía), así que romperlo tiene que romper un test."""
    _, factory = harness
    from src.models.guardian import Guardian
    from src.models.tenant import DEFAULT_TENANT_ID

    def _sembrar(**config):
        db = factory()
        try:
            db.query(Guardian).filter(Guardian.guardian_type == "pii_masking").delete()
            db.add(Guardian(name="PII", guardian_type="pii_masking", is_active=True,
                            tenant_id=DEFAULT_TENANT_ID, config=config))
            db.commit()
        finally:
            db.close()

    return _sembrar


@pytest.fixture
def key_atribuible(harness):
    """Emite una Connection real y devuelve la cabecera `X-Basa-Key` que la resuelve.

    Necesaria desde el hallazgo ALTO del review: la postura `degrade` sólo se honra con
    tenant ATRIBUIBLE. Un test que la ejercite sin key estaría midiendo el bypass, no la
    función."""
    _, factory = harness
    from src.models.budget import APIKey
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.services.key_material import hash_key

    clave = "sk-basa-test-atribuible-63"
    db = factory()
    try:
        db.query(APIKey).filter(APIKey.key_hash == hash_key(clave)).delete()
        # `upstream_mode="byok"`: la Connection sólo se usa para ATRIBUIR. El ruteo de este
        # plano lo decide `_detect_mode_and_key` mirando headers/URL —y `X-Basa-Key` está
        # excluido del scan a propósito—, así que el pedido sigue yendo por passthrough. Se
        # usa byok porque una fila `subscription-passthrough` exige `oauth_credential_ref`
        # (CHECK `ck_api_keys_subscription_oauth`) y acá no hay credencial que custodiar.
        db.add(APIKey(tenant_id=DEFAULT_TENANT_ID, key_hash=hash_key(clave),
                      key_preview="sk-basa-…63", name="conexión de prueba #63",
                      is_active=True, tool_type="claude-code", upstream_mode="byok"))
        db.commit()
    finally:
        db.close()
    return {"X-Basa-Key": clave}


@pytest.fixture
def nlp_configurado(monkeypatch):
    """`NLP_ANALYZER_URL` seteada + doble del sidecar. `caido=True` lo tumba."""
    from src.api import gateway

    def _instalar(caido: bool = False):
        monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)

        async def _analyze(text, analyzer_url, *args, **kwargs):
            assert analyzer_url == ANALYZER, "el plano tiene que llamar a la URL configurada"
            if caido:
                raise gateway.policy.NlpUnavailableError("connection refused")
            # NER simulado: detecta el nombre completo, que es lo que el regex NO caza.
            inicio = text.find(NOMBRE)
            if inicio < 0:
                return []
            return [{"start": inicio, "end": inicio + len(NOMBRE),
                     "entity_type": "PERSON", "score": 0.95}]

        monkeypatch.setattr(gateway.policy, "presidio_analyze", _analyze)

    return _instalar


# ── Helpers ───────────────────────────────────────────────────────────────────────


def filas(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return [{"compliance_status": f.compliance_status,
                 "blocked_by_layer": f.blocked_by_layer,
                 "pii_detected": f.pii_detected,
                 "masked_entities": f.masked_entities}
                for f in db.query(AuditLog).all()]
    finally:
        db.close()


def body_enviado(proveedor) -> str:
    assert proveedor.llamadas, "el pedido no llegó al proveedor"
    return (proveedor.llamadas[-1]["content"] or b"").decode()


# ── 1) Analyzer sano ⇒ el masking usa el NLP, no el regex ─────────────────────────


def test_con_analyzer_sano_el_masking_usa_el_nlp(harness, proveedor, nlp_configurado,
                                                 guardian_pii):
    """La paridad restituida, medida por su efecto: un nombre que SOLO el NLP detecta sale
    enmascarado. Antes del #63 este mismo pedido salía con el nombre en claro por `/gw` y
    enmascarado por el motor — la misma política, dos resultados."""
    guardian_pii(nlp_fail_mode="block")
    nlp_configurado()
    client, factory = harness

    respuesta = client.post(GW, json=_cuerpo())

    assert respuesta.status_code == 200, respuesta.text
    enviado = body_enviado(proveedor)
    assert NOMBRE not in enviado, "el nombre salió EN CLARO al proveedor (paridad rota)"
    assert "[PERSON_0_" in enviado, "no se aplicó el placeholder reversible"
    assert filas(factory)[0]["pii_detected"] is True


def test_sin_nlp_el_regex_de_dev_no_detecta_ese_nombre(harness, proveedor, guardian_pii,
                                                       monkeypatch):
    """Contracara que le da sentido al test anterior: con el mismo prompt y SIN sidecar, el
    regex deja pasar el nombre. Sin este test, el de arriba podría estar pasando por
    casualidad y la paridad no quedaría demostrada."""
    monkeypatch.delenv("NLP_ANALYZER_URL", raising=False)
    guardian_pii(nlp_fail_mode="block")
    client, _factory = harness

    assert client.post(GW, json=_cuerpo()).status_code == 200
    assert NOMBRE in body_enviado(proveedor)


# ── 2) Analyzer caído + `block` (y clave AUSENTE) ⇒ rechazo con fila durable ───────


@pytest.mark.parametrize("config, caso", [
    ({"nlp_fail_mode": "block"}, "explícito"),
    ({}, "clave AUSENTE (default fail-closed)"),
    ({"nlp_fail_mode": "cualquier-cosa"}, "valor no reconocido"),
])
def test_analyzer_caido_con_block_rechaza_y_registra(harness, proveedor, nlp_configurado,
                                                     guardian_pii, config, caso):
    """El default es `block` y no depende de que el admin haya escrito nada: una
    instalación anterior al #63 (sin la clave) tiene que comportarse igual que una que la
    escribió. El pedido NO sale al proveedor y queda fila durable."""
    guardian_pii(**config)
    nlp_configurado(caido=True)
    client, factory = harness

    respuesta = client.post(GW, json=_cuerpo())

    assert respuesta.status_code == 400, f"{caso}: {respuesta.text}"
    assert "no está disponible" in respuesta.json()["error"]["message"]
    assert proveedor.llamadas == [], f"{caso}: sin garantía de detección no se envía nada"
    fila = filas(factory)[0]
    assert fila["compliance_status"] == "blocked_nlp_unavailable", caso
    # Mismo vocabulario que el motor (`_LAYER_PII`): las dos filas tienen que ser
    # indistinguibles para quien consulta la auditoría.
    assert fila["blocked_by_layer"] == "pii_detection", caso


def test_el_texto_del_prompt_no_llega_a_la_fila_del_bloqueo(harness, nlp_configurado,
                                                            guardian_pii):
    """C1: el bloqueo ocurre con el body todavía crudo, así que este es justo el camino
    donde una fila descuidada filtraría PII."""
    guardian_pii(nlp_fail_mode="block")
    nlp_configurado(caido=True)
    client, factory = harness

    client.post(GW, json=_cuerpo())

    assert NOMBRE not in json.dumps(filas(factory), default=str)


# ── 3) Analyzer caído + `degrade` ⇒ regex + marca durable + estado en Redis ────────


def test_analyzer_caido_con_degrade_sirve_con_regex_y_lo_deja_marcado(
        harness, proveedor, nlp_configurado, guardian_pii, redis_falso, key_atribuible):
    """`degrade` es una postura legítima; degradar EN SILENCIO no lo es. El pedido se sirve,
    pero deja los tres rastros: enmascarado por regex, `compliance_status` propio en la fila
    durable y estado consultable en Redis.

    Va con `X-Basa-Key`: la relajación sólo se honra con tenant atribuible (ver la sección
    de la barrera de la 027 más abajo)."""
    from src.services import audit_service
    guardian_pii(nlp_fail_mode="degrade")
    nlp_configurado(caido=True)
    client, factory = harness

    respuesta = client.post(GW, json=_cuerpo("escribile a marta.iglesias@camara.es hoy"),
                            headers=key_atribuible)

    assert respuesta.status_code == 200, respuesta.text
    enviado = body_enviado(proveedor)
    # El regex SÍ caza el email: la degradación sigue protegiendo lo que puede.
    assert "marta.iglesias@camara.es" not in enviado
    assert "[EMAIL_ADDRESS_0_" in enviado

    fila = filas(factory)[0]
    assert fila["compliance_status"] == "degraded_nlp_regex", (
        "la transacción degradada tiene que ser distinguible de una normal en la auditoría")

    assert redis_falso.datos.get(audit_service.REDIS_KEY_NLP_DEGRADED_SINCE), (
        "sin marca de estado, el operador no puede enterarse después del hecho")
    assert int(redis_falso.datos[audit_service.REDIS_KEY_NLP_DEGRADED_COUNT]) == 1


def test_degrade_no_pierde_el_mapa_reversible(harness, proveedor, guardian_pii, monkeypatch,
                                              key_atribuible):
    """Regresión del camino más peligroso del fix: si el analyzer se cae A MITAD de
    `mask_body`, parte del body ya quedó enmascarada. Reanudar con un `PlaceholderMap` nuevo
    dejaría esos placeholders sin original al que volver y saldrían CRUDOS al cliente."""
    from src.api import gateway
    monkeypatch.setenv("NLP_ANALYZER_URL", ANALYZER)
    guardian_pii(nlp_fail_mode="degrade")
    estado = {"llamadas": 0}

    async def _muere_en_la_segunda(text, *_args, **_kwargs):
        estado["llamadas"] += 1
        if estado["llamadas"] >= 2:
            raise gateway.policy.NlpUnavailableError("el sidecar se cayó a mitad de camino")
        inicio = text.find(NOMBRE)
        return ([] if inicio < 0 else
                [{"start": inicio, "end": inicio + len(NOMBRE),
                  "entity_type": "PERSON", "score": 0.95}])

    monkeypatch.setattr(gateway.policy, "presidio_analyze", _muere_en_la_segunda)
    client, _factory = harness

    cuerpo = {"model": "claude-3-5-sonnet-20241022", "messages": [
        {"role": "user", "content": f"primero: {NOMBRE}"},
        {"role": "user", "content": "segundo: escribile a a@b.es"},
    ]}
    respuesta = client.post(GW, json=cuerpo, headers=key_atribuible)

    assert respuesta.status_code == 200, respuesta.text
    enviado = body_enviado(proveedor)
    assert NOMBRE not in enviado, "lo que el NLP alcanzó a enmascarar no puede volver a salir"
    assert "a@b.es" not in enviado, "el turno servido ya en degradado tampoco puede salir crudo"
    # Un solo nonce en todo el body ⇒ un solo mapa reversible ⇒ el unmask de la respuesta
    # puede deshacer TODOS los placeholders. Con dos mapas, los del primer tramo saldrían
    # crudos al cliente ("[PERSON_0_ab12]" en pantalla) y la PII quedaría irrecuperable.
    nonces = set(re.findall(r"\[[A-Z][A-Z0-9_]*_\d+_([0-9a-f]+)\]", enviado))
    assert len(nonces) == 1, f"el body salió con mapas distintos: {nonces} — {enviado}"


# ── 4) Sin NLP configurada ⇒ regex como siempre, y el health lo dice ──────────────


def test_sin_url_configurada_el_trafico_sigue_como_hoy(harness, proveedor, guardian_pii,
                                                       monkeypatch, redis_falso):
    """Dev/demo: no hay avería que reportar ni degradación que marcar — hay una instalación
    sin motor NLP. El tráfico no se bloquea y Redis queda intacto."""
    from src.services import audit_service
    monkeypatch.delenv("NLP_ANALYZER_URL", raising=False)
    guardian_pii(nlp_fail_mode="block")  # ni siquiera `block` bloquea: no hay nada caído
    client, factory = harness

    respuesta = client.post(GW, json=_cuerpo("escribile a a@b.es"))

    assert respuesta.status_code == 200, respuesta.text
    assert "[EMAIL_ADDRESS_0_" in body_enviado(proveedor)
    assert filas(factory)[0]["compliance_status"] == "passed"
    assert audit_service.REDIS_KEY_NLP_DEGRADED_SINCE not in redis_falso.datos


def test_sin_url_el_health_reporta_not_configured(harness, monkeypatch):
    """El otro extremo del mismo hecho: el modo regex de desarrollo es legítimo pero tiene
    que ser VISIBLE. `not_configured` no degrada el health — no es una avería."""
    monkeypatch.delenv("NLP_ANALYZER_URL", raising=False)
    client, _factory = harness
    from seat_gate_harness import admin_headers

    body = client.get("/api/v1/health", headers=admin_headers(client)).json()

    assert body["nlp"]["configured"] is False
    assert body["nlp"]["status"] == "not_configured"
    assert body["status"] == "healthy"


# ── El preview del monitor jamás cae al regex (Constraint C1) ─────────────────────


def test_con_analyzer_sano_el_preview_del_monitor_va_enmascarado(harness, nlp_configurado,
                                                                 guardian_pii, monkeypatch):
    """Contracara del test de abajo, y red de seguridad del atajo que evita el segundo viaje
    al sidecar: la vitrina tiene que seguir mostrando el texto CON placeholders. Si el atajo
    se aplicara en el camino equivocado (body todavía crudo), acá aparecería el nombre."""
    from src.api import gateway
    guardian_pii(nlp_fail_mode="block")
    nlp_configurado()
    eventos = []
    monkeypatch.setattr(gateway, "_publish_monitor",
                        lambda *a, **k: eventos.append(a[5] if len(a) > 5 else None))
    client, _factory = harness

    assert client.post(GW, json=_cuerpo()).status_code == 200
    assert NOMBRE not in eventos[-1], "la vitrina jamás muestra PII cruda (C1)"
    assert "[PERSON_0_" in eventos[-1]


def test_bloque_no_enmascarable_no_llega_a_la_vitrina(harness, nlp_configurado,
                                                      guardian_pii, monkeypatch,
                                                      key_atribuible):
    """Hallazgo ALTO del review adversarial: `_last_user_text` recogía `text` de CUALQUIER
    bloque del content, pero el masker sólo toca `type` en ("text", "tool_result"). Un bloque
    `{"type": "image", "text": "<PII>"}` —forma válida de la API— viajaba sin enmascarar y el
    atajo `ya_enmascarado` lo copiaba LITERAL a la vitrina y a Redis. C1 lo prohíbe."""
    from src.api import gateway
    guardian_pii(nlp_fail_mode="block")
    nlp_configurado()
    eventos = []
    monkeypatch.setattr(gateway, "_publish_monitor",
                        lambda *a, **k: eventos.append(a[5] if len(a) > 5 else None))
    client, _factory = harness

    cuerpo = {"model": "claude-3-5-sonnet-20241022", "messages": [{"role": "user", "content": [
        {"type": "text", "text": f"mirá esto de {NOMBRE}"},
        # El bloque que el masker NO transforma: su `text` no puede salir a la vitrina.
        {"type": "image", "text": "Sr. Juan Perez, juan@clinica.es"},
    ]}]}
    respuesta = client.post(GW, json=cuerpo, headers=key_atribuible)

    assert respuesta.status_code == 200, respuesta.text
    preview = eventos[-1]
    assert "juan@clinica.es" not in preview, f"PII cruda en la vitrina (C1): {preview!r}"
    assert "Juan Perez" not in preview
    # Y lo que SÍ se enmascara sigue mostrándose, enmascarado: el fix no vacía la vitrina.
    assert "[PERSON_0_" in preview


def test_el_texto_de_un_tool_result_si_se_muestra_y_va_enmascarado(harness, nlp_configurado,
                                                                   guardian_pii, monkeypatch,
                                                                   key_atribuible):
    """Contracara del filtro: `tool_result` SÍ lo enmascara el masker (sobre `content`), así
    que la vitrina lo puede mostrar. El filtro alinea con `_mask_content`, no recorta por
    recortar — si sólo se aceptara `type == "text"`, la vitrina perdería información real."""
    from src.api import gateway
    guardian_pii(nlp_fail_mode="block")
    nlp_configurado()
    eventos = []
    monkeypatch.setattr(gateway, "_publish_monitor",
                        lambda *a, **k: eventos.append(a[5] if len(a) > 5 else None))
    client, _factory = harness

    cuerpo = {"model": "claude-3-5-sonnet-20241022", "messages": [{"role": "user", "content": [
        {"type": "tool_result", "content": f"el paciente es {NOMBRE}"},
    ]}]}
    assert client.post(GW, json=cuerpo, headers=key_atribuible).status_code == 200

    assert NOMBRE not in eventos[-1]
    assert "[PERSON_0_" in eventos[-1]


# ── Barrera de atribución de la 027 sobre la postura NLP (hallazgo ALTO) ──────────


def test_sin_tenant_atribuible_la_postura_degrade_no_se_hereda(harness, proveedor,
                                                               nlp_configurado, guardian_pii):
    """`X-Basa-Key` es OPCIONAL en esta ruta (la credencial es el OAuth). Sin la barrera,
    OMITIRLA bastaba para caer al tenant por defecto y heredar SU `degrade`: en multi-tenant,
    un cliente cuyo admin exige `block` conseguía que su tráfico se sirviera con regex sólo
    con tirar abajo el sidecar. Misma regla que la 027 ya aplica al perfil: sin tenant
    atribuible sólo se acepta lo que AGREGA protección."""
    guardian_pii(nlp_fail_mode="degrade")  # el tenant de fallback relaja…
    nlp_configurado(caido=True)
    client, factory = harness

    respuesta = client.post(GW, json=_cuerpo())  # …y el pedido llega SIN key

    assert respuesta.status_code == 400, respuesta.text
    assert "no está disponible" in respuesta.json()["error"]["message"]
    assert proveedor.llamadas == [], "la relajación de otro tenant no puede dejar salir el pedido"
    assert filas(factory)[0]["compliance_status"] == "blocked_nlp_unavailable"


def test_con_tenant_atribuible_la_misma_postura_si_se_honra(harness, proveedor,
                                                            nlp_configurado, guardian_pii,
                                                            key_atribuible):
    """Contracara imprescindible: la barrera no puede convertir `degrade` en papel mojado.
    Con la Connection del admin viajando en el pedido, la relajación SÍ aplica."""
    guardian_pii(nlp_fail_mode="degrade")
    nlp_configurado(caido=True)
    client, _factory = harness

    respuesta = client.post(GW, json=_cuerpo("escribile a a@b.es"), headers=key_atribuible)

    assert respuesta.status_code == 200, respuesta.text
    assert len(proveedor.llamadas) == 1


def test_con_analyzer_caido_el_preview_del_monitor_va_vacio(harness, nlp_configurado,
                                                            guardian_pii, monkeypatch,
                                                            key_atribuible):
    """Con el NLP caído, la vitrina NO degrada a regex ni con `degrade`: una preview
    sub-enmascarada muestra en pantalla (y guarda en Redis) justo la PII que el regex no
    caza. Vacía no filtra nada, y de la vitrina no depende el trabajo de nadie."""
    from src.api import gateway
    guardian_pii(nlp_fail_mode="degrade")
    nlp_configurado(caido=True)
    eventos = []
    monkeypatch.setattr(gateway, "_publish_monitor",
                        lambda *a, **k: eventos.append(a[5] if len(a) > 5 else None))
    client, _factory = harness

    assert client.post(GW, json=_cuerpo(), headers=key_atribuible).status_code == 200
    assert eventos and eventos[-1] == "", (
        "la vitrina no puede ser la superficie menos protegida del producto")
