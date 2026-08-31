"""Consumo real por Connection en el listado de llaves (issue #76, UI honesta).

Hasta este fix la columna «Consumo Real» de la pantalla de usuarios mostraba `—` para
TODAS las llaves. No era un bug de la vista: el dato se pedía a `GET /keys/{id}/spend`, que
pregunta por el gasto al provisionador de keys del MOTOR — y en selfhosted ese
provisionador no existe, `engine_key_token` es NULL y la respuesta era siempre `null`. El
número honesto lo tenemos nosotros: es el contador de `budgets`, el mismo que dispara el
402 del motor. Que la UI muestre ESE y no otro es lo que hace que un admin pueda explicar
por qué a su usuario le cortaron el servicio.

Lo que se ancla:
* el listado expone `spend_usd` con el gasto del presupuesto del DUEÑO de la llave;
* la precedencia es personal → grupo, la MISMA de `BudgetService` y del plano interno (si
  divergieran, el consumo que ve el admin no explicaría el corte que ve el usuario);
* sin presupuesto configurado el listado dice 0.0 (no rompe la UI) y el endpoint de detalle
  dice `null` (no hay nada que informar: 0 se leería como "no gastó");
* la precisión fina de la migración 014 llega ENTERA hasta el JSON — redondear acá volvería
  a mostrar $0.0000 para el tráfico barato, que es el bug original visto desde la pantalla.
"""
import uuid
from decimal import Decimal

import pytest

from migration_harness import DEFAULT_TENANT, require_postgres
from seat_gate_harness import admin_headers, build_app_client

require_postgres()

DB = "sentinel_test_keys_spend"

# Gasto con 8 decimales: el orden de magnitud real del tráfico byok barato.
GASTO_FINO = Decimal("0.00001234")
GASTO_GRUPO = Decimal("0.55000000")


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    headers = admin_headers(client)
    yield client, factory, headers
    cleanup()


def _sembrar(factory, *, con_presupuesto_personal=False, con_grupo=False):
    """Client + Connection (+ presupuestos) por DB directa. Devuelve los ids."""
    from src.models.budget import APIKey, Budget
    from src.models.user import Group, User

    marca = uuid.uuid4().hex[:8]
    db = factory()
    try:
        grupo = None
        if con_grupo:
            grupo = Group(tenant_id=DEFAULT_TENANT, name=f"grupo-{marca}")
            db.add(grupo)
            db.flush()
            db.add(Budget(tenant_id=DEFAULT_TENANT, group_id=grupo.id,
                          max_spend_usd=Decimal("10"), current_spend_usd=GASTO_GRUPO,
                          max_tokens=1_000_000, reset_period="monthly"))

        # role='client': el vocabulario que fija ck_users_role desde la 010
        usuario = User(tenant_id=DEFAULT_TENANT, username=f"cliente-{marca}",
                       email=f"cliente-{marca}@sentinel.test", password_hash="x", role="client",
                       group_id=grupo.id if grupo else None)
        db.add(usuario)
        db.flush()

        if con_presupuesto_personal:
            db.add(Budget(tenant_id=DEFAULT_TENANT, user_id=usuario.id,
                          max_spend_usd=Decimal("5"), current_spend_usd=GASTO_FINO,
                          max_tokens=1_000_000, reset_period="monthly"))

        llave = APIKey(tenant_id=DEFAULT_TENANT, name=f"conn-{marca}",
                       key_hash=f"hash-{marca}", key_preview=f"sk-...{marca}",
                       tool_type="claude-code", user_id=usuario.id)
        db.add(llave)
        db.commit()
        return str(llave.id), str(usuario.id)
    finally:
        db.close()


def _llave(client, headers, key_id):
    resp = client.get("/api/v1/keys", headers=headers)
    assert resp.status_code == 200, resp.text
    fila = [k for k in resp.json() if k["id"] == key_id]
    assert fila, f"la llave {key_id} no está en el listado"
    return fila[0]


def test_el_listado_expone_el_gasto_del_presupuesto_personal(harness):
    client, factory, headers = harness
    key_id, _ = _sembrar(factory, con_presupuesto_personal=True)

    assert _llave(client, headers, key_id)["spend_usd"] == pytest.approx(float(GASTO_FINO))


def test_el_gasto_fino_no_se_redondea_al_serializar(harness):
    """La migración 014 no sirve de nada si el JSON lo trunca: $0.00001234 tiene que llegar
    distinto de cero a la pantalla."""
    client, factory, headers = harness
    key_id, _ = _sembrar(factory, con_presupuesto_personal=True)

    gasto = _llave(client, headers, key_id)["spend_usd"]
    assert gasto > 0, "el consumo volvió a mostrarse como cero"
    assert round(gasto, 4) == 0.0, "el test perdería sentido si el importe fuera grueso"


def test_sin_presupuesto_el_listado_dice_null(harness):
    """La mayoría de las llaves del piloto no tienen tope: la UI las renderiza igual,
    y el contrato es NULL, no 0.0 — «sin presupuesto aplicable» y «con presupuesto y
    gasto cero» son estados distintos y la celda los pinta distinto (US3 de la 031:
    un cero que parece control activo es la clase de mentira suave que esta spec mata)."""
    client, factory, headers = harness
    key_id, _ = _sembrar(factory)

    assert _llave(client, headers, key_id)["spend_usd"] is None


def test_el_presupuesto_del_grupo_es_el_respaldo(harness):
    """Sin presupuesto personal manda el del grupo — misma precedencia que
    `get_applicable_budgets` y que el LATERAL del plano interno."""
    client, factory, headers = harness
    key_id, _ = _sembrar(factory, con_grupo=True)

    assert _llave(client, headers, key_id)["spend_usd"] == pytest.approx(float(GASTO_GRUPO))


def test_el_personal_le_gana_al_del_grupo(harness):
    client, factory, headers = harness
    key_id, _ = _sembrar(factory, con_presupuesto_personal=True, con_grupo=True)

    assert _llave(client, headers, key_id)["spend_usd"] == pytest.approx(float(GASTO_FINO))


def test_el_detalle_por_llave_ya_no_devuelve_null_en_selfhosted(harness):
    """`GET /keys/{id}/spend` sin `engine_key_token` (el caso normal acá) responde con
    NUESTROS números en vez del `null` que pintaba «Consumo Real —»."""
    client, factory, headers = harness
    key_id, _ = _sembrar(factory, con_presupuesto_personal=True)

    cuerpo = client.get(f"/api/v1/keys/{key_id}/spend", headers=headers).json()

    assert cuerpo["spend_usd"] == pytest.approx(float(GASTO_FINO))
    assert cuerpo["max_budget"] == pytest.approx(5.0)
    assert cuerpo["remaining"] == pytest.approx(5.0 - float(GASTO_FINO))


def test_el_detalle_sin_presupuesto_sigue_diciendo_null(harness):
    """Honestidad: sin presupuesto configurado no hay consumo que informar. Un 0 acá se
    leería como "no gastó nada", que es una afirmación distinta."""
    client, factory, headers = harness
    key_id, _ = _sembrar(factory)

    cuerpo = client.get(f"/api/v1/keys/{key_id}/spend", headers=headers).json()

    assert cuerpo == {"spend_usd": None, "max_budget": None, "remaining": None}
