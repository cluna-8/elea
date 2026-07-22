"""Contract test de ``GET /api/v1/governance/status`` (spec 027, US1/T010 — SC-001).

El invariante que da SC-001 —**cero capas reportadas como activas que no se ejecutan**— es
verificable de forma automatizada porque el estado se calcula de fuentes independientes: si
una capa del plano motor se reporta ``aplicandose``, su cableado tiene que estar en la
respuesta de la sonda ``GET /guardrails/list``. Ese cruce es este archivo.

Las capas de piso quedan **fuera del cruce** a propósito (mismo recorte que la tarea T010):
no se cablean por nombre en el motor sino que las ejecuta nuestro propio guardrail, así que
el nombre que la sonda confirma para ellas es el de esa pieza, no el de un proveedor. Lo que
SC-001 persigue son las capas de proveedor, que son las que hoy la UI muestra activas sin
ejecutarse.

El shape se testea contra el contrato (contracts/api-gobernanza.md): 7 claves por capa,
``planes`` como lista, piso siempre presente con ``origen=floor``, y decisión y estado como
ejes independientes.
"""
import sys
import uuid
from pathlib import Path

import pytest

# Los harness de DB viven en ``tests/`` y ``tests/integration/`` (pytest solo agrega al
# path el directorio del módulo que colecta, así que desde ``tests/contract/`` no se ven).
# Se reusan en vez de duplicarse: son los que montan la app real contra una base migrada a
# head, que es la única forma de que este contract test hable con el endpoint de verdad.
_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_governance_status_contract"

CLAVES_DE_CAPA = {"layer_key", "tier", "planes", "decision_resuelta", "origen",
                  "estado_efectivo", "motivo"}


class _Probe:
    """Doble de la sonda con los tres estados reales: confirmada con nombres, confirmada
    vacía, y **no confirmada** (que no es lo mismo que vacía — es la diferencia entre
    'el motor dice que no está cargada' y 'el motor no contesta')."""

    def __init__(self, confirmed, names=()):
        self.confirmed = confirmed
        self.names = frozenset(names)

    def has(self, name):
        return bool(self.confirmed and name and name in self.names)


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


@pytest.fixture(autouse=True)
def _limpiar_guardianes(harness):
    """Cada test siembra su propio cableado: el estado depende de las filas de
    ``guardians``, así que arrastrar filas entre tests haría el resultado dependiente del
    orden de ejecución."""
    _, factory, _ = harness
    yield
    from src.models.guardian import Guardian
    db = factory()
    try:
        db.query(Guardian).delete()
        db.commit()
    finally:
        db.close()


def seed_guardian(factory, guardian_type, *, engine_name=None, con_credencial=False):
    from src.models.guardian import Guardian
    db = factory()
    try:
        db.add(Guardian(name=f"instancia-{guardian_type}", guardian_type=guardian_type,
                        is_active=True, config={}, engine_guardrail_name=engine_name,
                        service_api_key_encrypted="cifrada" if con_credencial else None))
        db.commit()
    finally:
        db.close()


def set_probe(monkeypatch, probe):
    from src.api import governance

    async def _fake(**_kwargs):
        return probe

    monkeypatch.setattr(governance.ai_engine_client, "probe_loaded_guardrails", _fake)


def get_status(client, headers, **params):
    resp = client.get("/api/v1/governance/status", headers=headers, params=params)
    return resp


# ── Shape del contrato ────────────────────────────────────────────────────────────


def test_shape_exacto_por_capa(harness, monkeypatch):
    """7 claves, ni una más: una clave de más es un canal por donde vuelve a filtrarse
    información del motor a la UI."""
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(True, {"basa-guardian"}))

    resp = get_status(client, headers, mode="gateway-models")

    assert resp.status_code == 200, resp.text
    capas = resp.json()["layers"]
    assert capas, "la respuesta jamás puede venir sin capas"
    for capa in capas:
        assert set(capa) == CLAVES_DE_CAPA
        assert isinstance(capa["planes"], list)      # lista, no escalar
        assert capa["estado_efectivo"] in {"aplicandose", "requiere_credencial", "delegada",
                                           "no_disponible", "degradada"}
        assert capa["motivo"], "todo estado viene con motivo del catálogo cerrado"


def test_piso_siempre_presente_on_y_con_origen_floor(harness, monkeypatch):
    """Garantía (b): no existe representación de piso apagado — el piso no sale de la
    configuración sino del registry en código."""
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(True, {"basa-guardian"}))

    for mode in ("subscription", "gateway-models"):
        capas = get_status(client, headers, mode=mode).json()["layers"]
        piso = [c for c in capas if c["tier"] == "floor"]
        assert len(piso) == 4, "las 4 capas de piso aparecen siempre"
        for capa in piso:
            assert capa["decision_resuelta"] == "on"
            assert capa["origen"] == "floor"


def test_decision_y_estado_son_ejes_independientes(harness, monkeypatch):
    """Garantía (c): con el motor sin confirmar, el enmascarado sigue ``on`` por decisión y
    aun así se reporta ``no_disponible``. El deseo no fabrica ejecución."""
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(False))

    capas = {c["layer_key"]: c for c in get_status(client, headers,
                                                   mode="gateway-models").json()["layers"]}
    masking = capas["pii_masking"]
    assert masking["decision_resuelta"] == "on"
    assert masking["estado_efectivo"] == "no_disponible"


def test_resumen_por_modo_sin_parametros(harness, monkeypatch):
    """SC-002: una sola respuesta contesta qué protege cada tipo de tráfico."""
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(True, {"basa-guardian"}))

    cuerpo = get_status(client, headers).json()

    assert [b["mode"] for b in cuerpo["modes"]] == ["subscription", "gateway-models"]
    for bloque in cuerpo["modes"]:
        claves = [c["layer_key"] for c in bloque["layers"]]
        assert len(claves) == len(set(claves)) == 10, "cada modo lista el catálogo completo"
    assert len(cuerpo["layers"]) == 20, "layers = unión de los bloques por modo"


def test_valores_fuera_de_enum_devuelven_422_nombrando_el_valor(harness, monkeypatch):
    """Garantía (e)."""
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(True, {"basa-guardian"}))

    resp = get_status(client, headers, mode="produccion")
    assert resp.status_code == 422
    assert "produccion" in resp.json()["detail"]

    resp = get_status(client, headers, surface="telepatia")
    assert resp.status_code == 422
    assert "telepatia" in resp.json()["detail"]


# ── SC-001: el cruce que hace falsificable "cero capas fantasma" ──────────────────


def _nombres_de_motor(factory, layer_key):
    """El cableado real de la capa, leído como lo lee el backend."""
    from src.models.guardian import Guardian
    from src.services.governance_status import _credentials_and_wiring

    db = factory()
    try:
        _, nombres = _credentials_and_wiring(tuple(db.query(Guardian).all()))
    finally:
        db.close()
    return nombres.get(layer_key, frozenset())


def _cruce_sc001(cuerpo, factory, probe_names):
    """∀ capa ``aplicandose`` de plano motor y tier != floor ⇒ su nombre ∈ la sonda."""
    for capa in cuerpo["layers"]:
        if capa["estado_efectivo"] != "aplicandose":
            continue
        if "engine" not in capa["planes"] or capa["tier"] == "floor":
            continue
        nombres = _nombres_de_motor(factory, capa["layer_key"])
        assert nombres & probe_names, (
            f"{capa['layer_key']} se reporta aplicándose sin estar cargada en el motor")


def test_sc001_con_el_cableado_real_del_producto(harness, monkeypatch):
    """El escenario de hoy: el motor tiene UNA sola pieza cargada (la nuestra) y los
    nombres de proveedor sembrados no existen. Ninguna capa de proveedor puede reportarse
    aplicándose."""
    client, factory, headers = harness
    for tipo, nombre in (("openai_moderation", "litellm_content_filter"),
                         ("lakera_prompt_injection", "promptguard"),
                         ("azure_content_safety", "azure/text_moderations"),
                         ("bedrock_guardrails", "bedrock_guardrails")):
        seed_guardian(factory, tipo, engine_name=nombre, con_credencial=True)
    probe_names = {"basa-guardian"}
    set_probe(monkeypatch, _Probe(True, probe_names))

    cuerpo = get_status(client, headers).json()

    _cruce_sc001(cuerpo, factory, probe_names)
    proveedor = {c["layer_key"] for c in cuerpo["layers"]
                 if c["estado_efectivo"] == "aplicandose" and c["tier"] != "floor"
                 and "engine" in c["planes"] and c["layer_key"] != "pii_masking"}
    assert not proveedor, f"capas de proveedor reportadas activas: {proveedor}"


def test_sc001_se_sostiene_aunque_el_motor_cargue_capas_de_proveedor(harness, monkeypatch):
    """El cruce no es una tautología del escenario actual: con las piezas de proveedor
    cargadas y con credencial, el invariante se sigue cumpliendo — y ninguna capa cuyo
    nombre NO esté en la sonda se cuela como activa."""
    client, factory, headers = harness
    seed_guardian(factory, "openai_moderation", engine_name="litellm_content_filter",
                  con_credencial=True)
    seed_guardian(factory, "bedrock_guardrails", engine_name="bedrock_guardrails",
                  con_credencial=True)
    probe_names = {"basa-guardian", "litellm_content_filter"}
    set_probe(monkeypatch, _Probe(True, probe_names))

    cuerpo = get_status(client, headers).json()

    _cruce_sc001(cuerpo, factory, probe_names)
    estados = {(c["layer_key"], c["estado_efectivo"]) for c in cuerpo["layers"]}
    assert ("provider_guardrails", "aplicandose") not in estados


def test_sc001_contra_la_sonda_viva_del_motor(harness):
    """Mismo invariante, con la sonda REAL contra la imagen pineada del motor. Se auto-skipea
    cuando el motor no está levantado (no toda corrida de la suite tiene el stack completo),
    pero cuando corre es el gate que hace fallar un upgrade del motor acá y no en producción.
    """
    import asyncio

    from src.services import ai_engine_client

    client, factory, headers = harness
    ai_engine_client.reset_guardrail_probe_cache()
    probe = asyncio.run(ai_engine_client.probe_loaded_guardrails())
    if not probe.confirmed:
        pytest.skip("motor no disponible: el cruce vivo de SC-001 necesita el stack arriba")

    cuerpo = get_status(client, headers).json()

    _cruce_sc001(cuerpo, factory, set(probe.names))


# ── Gate del tenant (garantía (g)) ────────────────────────────────────────────────


def test_tenant_id_inexistente_da_404_en_single_tenant(harness, monkeypatch):
    client, _, headers = harness
    set_probe(monkeypatch, _Probe(True, {"basa-guardian"}))

    resp = get_status(client, headers, tenant_id=str(uuid.uuid4()))

    assert resp.status_code == 404


def test_sin_sesion_da_401(harness, monkeypatch):
    """Invariante #1: la protección real vive en el router, no en el nav de la UI."""
    client, _, _ = harness
    set_probe(monkeypatch, _Probe(True, {"basa-guardian"}))

    assert client.get("/api/v1/governance/status").status_code == 401
