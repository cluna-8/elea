"""Camino de BORRADO de `PUT /api/v1/content-policies/{policy_id}` — P1 del gate
cross-familia de #315 (26-ago-2026).

`ai_engine_client.update_content_policy` es **borrar + crear**, no un PUT: es el
workaround correcto del bug del PUT de LiteLLM (hallazgo en vivo del 11-ago con Cristian,
documentado en el docstring del cliente). El precio es que la operación NO es atómica. Sin
compensación, si el `_post` falla DESPUÉS del `_delete_by_id` la política queda **borrada y
no recreada**: el motor deja de filtrar, el tráfico pasa sin el guard, y el admin ve un 502
genérico que se lee «falló, sin cambios» cuando el borrado ya se aplicó. En un firewall de
compliance ese es el modo de fallo **abierto**.

Las dos ramas del borra+crea se pinean POR SEPARADO a propósito, porque dejan el sistema en
estados OPUESTOS y una compensación ciega arregla una rompiendo la otra:

| Falla              | Estado del motor      | Qué corresponde            |
|--------------------|-----------------------|----------------------------|
| el `_post`         | política **BORRADA**  | reponer el estado anterior |
| el `_delete_by_id` | política **INTACTA**  | NO tocar                   |

Por eso el cliente levanta `ContentPolicyLostError` (subclase de `ContentPolicyError`) sólo
en la primera, y el endpoint compensa sólo sobre ese tipo.

Medido contra LiteLLM real (26-ago-2026) para saber qué cuesta NO distinguir: el motor tiene
UNIQUE sobre `guardrail_name`, así que una reposición ciega en la rama del delete no deja un
guardrail duplicado — devuelve HTTP 500 `Unique constraint failed` y el listado sigue con una
sola. El costo real es de INFORMACIÓN: sin distinguir, el admin recibe el mismo 502 en las dos
ramas y nunca sabe si su política sobrevivió al fallo.
"""
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client, headers_for_role  # noqa: E402

from src.auth.matrix import Rol  # noqa: E402
from src.services import ai_engine_client as svc  # noqa: E402

require_postgres()

DB = "basa_test_content_policies_api"
POLICY_ID = "banco-xyz-sin-credito"
URL = f"/api/v1/content-policies/{POLICY_ID}"

# Estado ANTERIOR en el motor: la política que el `update` va a borrar. Es el estado que la
# compensación tiene que reponer tal cual — con sus reglas, no con las del request fallido.
_ANTERIOR = {
    "guardrail_name": f"basa-policy-{POLICY_ID}",
    "guardrail_id": "abc-123",
    "litellm_params": {
        "guardrail": "litellm_content_filter",
        "default_on": True,
        "blocked_words": [{"keyword": "aprobar tu crédito", "action": "BLOCK"}],
    },
    "guardrail_info": {"description": "No dar asesoramiento de crédito"},
}

# Cuerpo del PUT: reglas DISTINTAS a las anteriores, para poder distinguir en el `_post` de
# la compensación si repuso el estado viejo o re-mandó el nuevo que ya falló.
_CUERPO_NUEVO = {
    "description": "texto nuevo",
    "blocked_words": [{"keyword": "palabra nueva", "action": "BLOCK"}],
    "active": False,
}


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture
def admin(harness):
    client, factory = harness
    return headers_for_role(client, factory, Rol.SUPER_ADMIN)


@pytest.fixture
def motor(monkeypatch):
    """Doble del motor a nivel TRANSPORTE (`_get`/`_post`/`_delete_by_id`), no de las
    funciones de alto nivel: así el borra+crea real del cliente corre de verdad y lo que se
    mide es el efecto en el motor, no el mock."""
    llamadas = {"delete": [], "post": []}

    async def _get_doble(path, params):
        return {"guardrails": [_ANTERIOR]}

    monkeypatch.setattr(svc, "_get", _get_doble)
    return llamadas


def _instalar(monkeypatch, llamadas, *, delete_falla=False, post_falla_veces=0):
    async def _delete_doble(path):
        llamadas["delete"].append(path)
        if delete_falla:
            raise svc.AIEngineClientError("motor caído en el DELETE")
        return {}

    async def _post_doble(path, payload):
        llamadas["post"].append(payload)
        if len(llamadas["post"]) <= post_falla_veces:
            raise svc.AIEngineClientError("motor caído en el POST")
        return {"guardrail_id": "nuevo-id"}

    monkeypatch.setattr(svc, "_delete_by_id", _delete_doble)
    monkeypatch.setattr(svc, "_post", _post_doble)


def test_si_falla_el_create_repone_la_politica_anterior(harness, admin, motor, monkeypatch):
    """Rama post-delete: el borrado YA se aplicó ⇒ hay que reponer el estado anterior.

    TESTIGO: contra el CONTROL (árbol sin la compensación) esto rojea — el endpoint devuelve
    502 y `llamadas["post"]` queda en 1 sola entrada, la del update que falló. La política se
    queda borrada en el motor y nadie se entera."""
    client, _ = harness
    _instalar(monkeypatch, motor, post_falla_veces=1)

    resp = client.put(URL, json=_CUERPO_NUEVO, headers=admin)

    assert resp.status_code == 502, resp.text
    assert len(motor["delete"]) == 1, "el update tiene que haber intentado el borrado"
    assert len(motor["post"]) == 2, (
        f"esperaba 2 POST (el update que falla + la compensación que repone), hubo "
        f"{len(motor['post'])}: sin el segundo, la política quedó BORRADA en el motor")

    # El body de LiteLLM va anidado bajo "guardrail" (ver `_content_policy_payload`).
    repuesto = motor["post"][1]["guardrail"]
    assert repuesto["guardrail_name"] == f"basa-policy-{POLICY_ID}"
    assert repuesto["litellm_params"]["blocked_words"] == \
        _ANTERIOR["litellm_params"]["blocked_words"], (
        "la compensación tiene que reponer las reglas ANTERIORES, no las del request que falló")
    assert repuesto["litellm_params"]["default_on"] is True, \
        "la política anterior estaba activa: reponerla apagada la deja sin filtrar"
    assert repuesto["guardrail_info"]["description"] == \
        _ANTERIOR["guardrail_info"]["description"]
    assert "repuso" in resp.json()["detail"], \
        "el admin tiene que leer que no hubo cambios y que se repuso el estado anterior"


def test_si_falla_el_delete_no_intenta_reponer_nada(harness, admin, motor, monkeypatch):
    """Rama delete: la política sigue INTACTA ⇒ no hay nada que reponer.

    Este test NO rojea contra el árbol actual (hoy no hay compensación de ninguna clase): es
    un pin contra la compensación INGENUA — la que cuelga del `except AIEngineClientError`
    genérico y no distingue qué fase falló. Su testigo es esa implementación, no el árbol sin
    fix, y se midió: con ella `llamadas["post"]` pasa de 0 a 1 y este test rojea.

    Contra el motor real ese POST de más no deja un duplicado (LiteLLM tiene UNIQUE sobre
    `guardrail_name`, medido): falla con 500 y el `except` se lo traga. Lo que se pierde es la
    señal — el admin ve el mismo 502 que en la rama donde SÍ perdió la política."""
    client, _ = harness
    _instalar(monkeypatch, motor, delete_falla=True)

    resp = client.put(URL, json=_CUERPO_NUEVO, headers=admin)

    assert resp.status_code == 502, resp.text
    assert len(motor["delete"]) == 1
    assert motor["post"] == [], (
        f"el borrado falló ⇒ la política sigue viva y no hay nada que reponer; un POST acá es "
        f"un round-trip condenado (UNIQUE sobre guardrail_name) que además borra la diferencia "
        f"entre 'no pasó nada' y 'perdiste la política'. Hubo {len(motor['post'])}")


def test_si_el_rollback_tambien_falla_el_error_dice_que_quedo_borrada(
        harness, admin, motor, monkeypatch):
    """Peor caso: borrado aplicado, create fallido y compensación fallida. Acá el 502
    genérico es activamente peligroso — manda al admin a reintentar creyendo que su política
    sigue viva. El detalle tiene que nombrar el estado real.

    TESTIGO: contra el CONTROL da 502 y un detalle que no menciona el borrado."""
    client, _ = harness
    _instalar(monkeypatch, motor, post_falla_veces=2)

    resp = client.put(URL, json=_CUERPO_NUEVO, headers=admin)

    assert resp.status_code == 500, resp.text
    assert len(motor["post"]) == 2, "tiene que haber INTENTADO reponer antes de rendirse"
    detalle = resp.json()["detail"]
    assert "BORRADA" in detalle, f"el detalle no dice que la política quedó borrada: {detalle}"
    assert POLICY_ID in detalle, "el detalle tiene que nombrar la política afectada"
