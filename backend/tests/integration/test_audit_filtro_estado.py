"""Filtro «Bloqueados» del listado de auditoría (spec 031, T007-API — FR-006).

Antes de la 031, aislar los intentos IMPEDIDOS exigía que el officer supiera de memoria los
valores de `compliance_status` (`blocked_prohibited`, `blocked_secret`, …) y los filtrara de
a uno, o que los dedujera de «0/0 tokens». Con la convención D1 (prefijo `blocked_`) el
filtro canónico es uno solo: `LIKE 'blocked%'`.

Los invariantes que se fijan acá:

1. **`estado=bloqueados` devuelve TODOS los bloqueos y sólo bloqueos**, sin importar el
   motivo — el officer no tiene que conocer el vocabulario interno para encontrar lo que
   busca (SC-001/SC-005).
2. **Los eslabones de la hash-chain de licencias quedan fuera** (FR-010). No es un detalle:
   varias transiciones de licencia se persisten con `compliance_status='blocked_by_policy'`
   (`licensing/audit_events.py:195`) y caen de lleno en `LIKE 'blocked%'`. Sin la exclusión
   por `model='license'`, la pantalla mezclaría «se venció la licencia del deployment» con
   «alguien intentó pegar el padrón de socios» — justo la confusión que el filtro existe
   para eliminar. La cadena no se toca: sólo se la deja fuera de un filtro de TRÁFICO.
3. **Los rechazos por capacidad quedan fuera de los DOS baldes** (gate #135 H4, decisión JF
   12-ago). `rejected_saturated` (`services/engine_gate.py`) no empieza con `blocked` a
   propósito —capacidad no es política—, así que sin exclusión explícita caería en el `else`
   y se contaría como PERMITIDO: un pedido que nunca se sirvió, por causa nuestra, informado
   al cliente como servido. Su balde propio («Rechazados») llega en el ciclo 2; hasta
   entonces, fuera de ambos pero VISIBLE sin filtro `estado` (es auditoría durable).
"""
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import admin_headers, build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_audit_filtro_estado"
LOGS = "/api/v1/audit-logs"
EXPORT = "/api/v1/audit-logs/export"

# `compliance_status` del rechazo por capacidad. Literal y no import de `engine_gate`: lo que
# este archivo prueba es el CONTRATO de la pantalla contra el valor que se persiste, y un
# import haría pasar el test aunque la constante cambiara de las dos puntas a la vez.
SATURADO = "rejected_saturated"

# Un `rejected_*` que hoy NO existe en el código: clava que el contrato de exclusión es de
# PREFIJO, no de valor exacto. Si `RECHAZADO_LIKE` se degradara al literal, el próximo
# rechazo con nombre propio caería callado en «permitidos» — exactamente la mentira que H4
# vino a cerrar, reabierta para el status siguiente (mutante sobreviviente del re-check).
RECHAZO_FUTURO = "rejected_timeout"

# (modelo, compliance_status, capa que bloqueó). Cubre los dos motivos de bloqueo que ya
# escribía el passthrough, uno nuevo del plano chat, tráfico permitido, un rechazo por
# capacidad (que no es ni una cosa ni la otra), un segundo rechazo hipotético que clava el
# prefijo y —el caso feo— un eslabón de licencia que TAMBIÉN empieza con `blocked`.
SEMILLA = [
    ("claude-3-5-sonnet-20241022", "blocked_secret", "secret_detection"),
    ("claude-3-5-sonnet-20241022", "blocked_prohibited", "ai_act_evaluation"),
    ("ollama-qwen3-4b", "blocked_guardian", "pii_masking"),
    ("claude-3-5-sonnet-20241022", "passed", None),
    ("ollama-qwen3-4b", "flagged_high_risk", None),
    ("ollama-qwen3-4b", SATURADO, None),
    ("claude-3-5-sonnet-20241022", RECHAZO_FUTURO, None),
    ("license", "blocked_by_policy", None),
]


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    client.headers.update(admin_headers(client))
    sembrar(factory)
    yield client, factory
    cleanup()


def sembrar(factory):
    """Filas por base directa: lo que se prueba es la QUERY del listado, y hacerla depender
    de que cada plano emita su bloqueo convertiría este test en uno de integración de otros
    tres módulos."""
    from src.models.audit import AuditLog
    from src.models.tenant import DEFAULT_TENANT_ID
    db = factory()
    try:
        db.query(AuditLog).delete()
        base = datetime.utcnow() - timedelta(minutes=len(SEMILLA))
        for i, (modelo, estado, capa) in enumerate(SEMILLA):
            db.add(AuditLog(
                id=uuid.uuid4(), tenant_id=DEFAULT_TENANT_ID,
                timestamp=base + timedelta(minutes=i), model=modelo,
                prompt_tokens=0, completion_tokens=0, cost_usd=0,
                pii_detected=False, compliance_status=estado, latency_ms=7,
                blocked_by_layer=capa, guardian_events=[],
            ))
        db.commit()
    finally:
        db.close()


def estados(payload):
    return sorted(fila["compliance_status"] for fila in payload["logs"])


def test_sin_filtro_el_listado_no_cambia(harness):
    """Retrocompatibilidad: quien no manda `estado` sigue viendo todo (incluidos los
    eslabones de licencia, que siempre estuvieron en esta pantalla)."""
    client, _ = harness
    payload = client.get(LOGS).json()
    assert payload["total"] == len(SEMILLA)


def test_bloqueados_devuelve_todos_los_bloqueos_sin_conocer_el_vocabulario(harness):
    client, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    assert estados(payload) == ["blocked_guardian", "blocked_prohibited", "blocked_secret"]
    assert payload["total"] == 3


def test_bloqueados_no_arrastra_los_eslabones_de_licencia(harness):
    """FR-010: la hash-chain de la 021 no es tráfico bloqueado. Si esta afirmación se cae,
    el officer ve un «bloqueo» que ningún usuario provocó."""
    client, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    assert all(fila["model"] != "license" for fila in payload["logs"])
    assert "blocked_by_policy" not in estados(payload)


def test_la_fila_bloqueada_dice_que_capa_la_bloqueo(harness):
    """SC-005: quién/qué/cuándo/**qué capa**, sin abrir otra vista."""
    client, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    capas = {fila["compliance_status"]: fila["blocked_by_layer"] for fila in payload["logs"]}
    assert capas["blocked_secret"] == "secret_detection"
    assert capas["blocked_prohibited"] == "ai_act_evaluation"


def test_permitidos_es_el_complemento_y_tampoco_trae_licencias(harness):
    client, _ = harness
    payload = client.get(LOGS, params={"estado": "permitidos"}).json()
    assert estados(payload) == ["flagged_high_risk", "passed"]
    assert all(fila["model"] != "license" for fila in payload["logs"])


def test_el_rechazo_por_capacidad_no_se_cuenta_como_permitido(harness):
    """H4 del gate de #135. `rejected_saturated` no matchea `LIKE 'blocked%'` (capacidad ≠
    política), así que sin exclusión explícita caería en el `else` y se informaría como
    PERMITIDO. Ese pedido nunca se sirvió, y el motivo fue nuestro: contarlo entre los
    permitidos le miente al cliente justo en el número que más mira."""
    client, _ = harness
    payload = client.get(LOGS, params={"estado": "permitidos"}).json()
    assert SATURADO not in estados(payload)
    assert RECHAZO_FUTURO not in estados(payload)
    assert payload["total"] == 2


def test_el_rechazo_por_capacidad_tampoco_es_un_bloqueo(harness):
    """La otra mitad del mismo invariante: tampoco se lo infla como bloqueo. No lo impidió
    ninguna capa, no hubo dato personal ni secreto ni práctica prohibida. Su balde propio
    («Rechazados») llega en el ciclo 2; hasta entonces, fuera de los dos."""
    client, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados"}).json()
    assert SATURADO not in estados(payload)
    assert RECHAZO_FUTURO not in estados(payload)
    assert payload["total"] == 3


def test_sin_filtro_el_rechazo_por_capacidad_sigue_visible(harness):
    """Dejarlo fuera del filtro binario no es esconderlo: la fila es auditoría durable y el
    officer tiene que poder verla para explicar por qué ese pedido no salió."""
    client, _ = harness
    payload = client.get(LOGS).json()
    assert SATURADO in estados(payload)
    assert RECHAZO_FUTURO in estados(payload)


def test_el_export_tampoco_vende_el_rechazo_como_permitido(harness):
    """El CSV sale del MISMO constructor de query: si la exclusión viviera sólo en el listado,
    el reporte que se manda por mail seguiría mintiendo."""
    client, _ = harness
    cuerpo = client.get(EXPORT, params={"estado": "permitidos"}).text
    assert SATURADO not in cuerpo
    assert RECHAZO_FUTURO not in cuerpo
    assert "passed" in cuerpo and "flagged_high_risk" in cuerpo


def test_un_estado_desconocido_falla_fuerte_en_vez_de_ignorarse(harness):
    """Un filtro que se ignora en silencio es peor que un error: el officer creería estar
    viendo SÓLO los bloqueos mientras mira la tabla entera."""
    client, _ = harness
    assert client.get(LOGS, params={"estado": "bloqueadas"}).status_code == 422


def test_el_filtro_convive_con_los_filtros_previos(harness):
    """`estado` se compone con el resto (AND), no los reemplaza."""
    client, _ = harness
    payload = client.get(LOGS, params={"estado": "bloqueados",
                                       "compliance_status": "blocked_secret"}).json()
    assert estados(payload) == ["blocked_secret"]


def test_el_export_honra_el_mismo_filtro(harness):
    """Un CSV que ignora el filtro visible es una trampa silenciosa: el officer exporta lo
    que ve."""
    client, _ = harness
    respuesta = client.get(EXPORT, params={"estado": "bloqueados"})
    assert respuesta.status_code == 200
    cuerpo = respuesta.text
    assert "blocked_secret" in cuerpo and "blocked_prohibited" in cuerpo
    assert "blocked_by_policy" not in cuerpo   # el eslabón de licencia no es tráfico
    assert "passed" not in cuerpo
