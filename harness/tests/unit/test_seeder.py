"""Tests del SEEDER (spec 035, T021) — el instrumento con datos sintéticos, sin stack.

Frontera del módulo (DevFlow §3): pytest prueba el seeder con un cliente FALSO inyectable
(no httpx, no backend). El seeding REAL se valida en un run del examen. Acá se cubren las
propiedades que la spec/tarea piden:

- pre-check de seats: población que EXCEDE los seats → falla ANTES de crear nada;
- distribución: cada gate suma exacto su número y los seats entran en la licencia;
- orden: users se crean ANTES que las keys (el seat gate corre en ambos);
- idempotencia: re-seed con 400/409 esperados → converge, no explota;
- determinismo: mismas identidades/passwords con la misma semilla.
"""
from __future__ import annotations

import json

import pytest

from basa_harness.seeder import (
    DEFAULT_SEED,
    SeedError,
    derive_password,
    load_population_by_gate,
    plan_members,
    precheck_seats,
    seed,
    validate_population,
)
from basa_harness.seeder.client import BackendError

GATES = (125, 250, 500)
# Distribución canónica de R5 (client_total, tenant_admins, compliance, licencia).
EXPECTED = {
    125: {"clients": 119, "admins": 4, "comp": 2, "license": 300,
          "buckets": {"chat_ui": 75, "desktop": 31, "base_url": 13}},
    250: {"clients": 238, "admins": 8, "comp": 4, "license": 300,
          "buckets": {"chat_ui": 150, "desktop": 63, "base_url": 25}},
    500: {"clients": 475, "admins": 17, "comp": 8, "license": 500,
          "buckets": {"chat_ui": 300, "desktop": 125, "base_url": 50}},
}


# ── Cliente FALSO inyectable (in-memory; modela seat=llave y el seat gate) ─────────────

class FakeBackendClient:
    """Implementa el ``Protocol`` ``SeedClient`` con un store en memoria.

    Modela lo que importa del backend real: el seat es la LLAVE activa (no el user), el
    seat gate corta con 402 al tope, los duplicados devuelven 400 (user/budget) o 409
    (Connection), y ``list_*`` refleja el estado — para que el re-seed converja."""

    def __init__(self, *, max_seats=300, seats_used=0, admin_detail=True,
                 key_error_status=None, budget_error=None, whoami_ok=True):
        self.max_seats = max_seats
        self.seats_used = seats_used
        self.admin_detail = admin_detail
        self.key_error_status = key_error_status  # fuerza un status en create_key (fail-fast)
        self.budget_error = budget_error          # fuerza (status, detail) en create_budget
        self.whoami_ok = whoami_ok                # respuesta de GET /gw/whoami
        self.whoami_calls: list = []
        self.users: dict[str, dict] = {}
        self.keys: dict[tuple, str] = {}
        self.plain_keys: set = set()   # keys EN CLARO emitidas (el backend no las repite)
        self.budgets: dict[str, dict] = {}        # user_id -> fila con montos (FIX-4)
        self.events: list[tuple] = []  # log ordenado ("user"/"key"/"budget", clave)
        self._n = 0
        self.token = None

    def _nid(self) -> str:
        self._n += 1
        return f"id-{self._n}"

    # context-manager (el CLI usa `with BackendClient(...)`)
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    # -- protocolo --
    def bootstrap_admin(self, username, password):
        self.token = "tok"
        return self.token

    def verify_credential(self, username, password):
        # Modela POST /login de sólo-comprobación: True si la password guardada coincide.
        u = self.users.get(username)
        return bool(u and u.get("password") == password)

    def verify_basa_key(self, basa_key):
        # Modela GET /gw/whoami: 200 si la key en claro existe (fail-closed 401 si no).
        self.whoami_calls.append(basa_key)
        return bool(self.whoami_ok and basa_key in self.plain_keys)

    def license_health(self):
        body = {"status": "active", "clock_rollback_suspected": False}
        if self.admin_detail:
            body["max_seats"] = self.max_seats
            body["seats_used"] = self.seats_used
        return body

    def list_users(self):
        return [{"username": u, "id": v["id"], "role": v["role"]} for u, v in self.users.items()]

    def list_keys(self):
        return [{"user_id": k[0], "tool_type": k[1], "id": v, "is_active": True}
                for k, v in self.keys.items()]

    def list_budgets(self):
        return list(self.budgets.values())

    def create_user(self, *, username, email, password, role, client_type=None):
        if username in self.users:
            raise BackendError(400, "Username already registered")
        if role == "client" and self.seats_used >= self.max_seats:
            raise BackendError(402, "license_seat_limit_exceeded")
        uid = self._nid()
        self.users[username] = {"id": uid, "role": role, "client_type": client_type,
                                "engine_user_id": f"eng-{uid}", "password": password}
        self.events.append(("user", username))
        return {"id": uid, "username": username, "role": role}

    def create_key(self, *, name, user_id, tool_type):
        if self.key_error_status is not None:
            raise BackendError(self.key_error_status, "forced key error")
        key = (user_id, tool_type)
        if key in self.keys:
            raise BackendError(409, "Connection activa ya existe para esa herramienta")
        if self.seats_used >= self.max_seats:
            raise BackendError(402, "license_seat_limit_exceeded")
        self.seats_used += 1  # seat = llave activa
        kid = self._nid()
        self.keys[key] = kid
        plain = f"sk-{kid}"                  # plain_key: sólo en ESTA respuesta
        self.plain_keys.add(plain)
        self.events.append(("key", key))
        return {"id": kid, "plain_key": plain}

    def create_budget(self, *, user_id, max_spend_usd, max_tokens, reset_period):
        if self.budget_error is not None:
            raise BackendError(*self.budget_error)
        if user_id in self.budgets:
            raise BackendError(400, "Budget already exists for this user")
        bid = self._nid()
        self.budgets[user_id] = {"id": bid, "user_id": user_id,
                                 "max_spend_usd": max_spend_usd, "max_tokens": max_tokens,
                                 "reset_period": reset_period}
        self.events.append(("budget", user_id))
        return {"id": bid}


# ── Poblaciones: cargan, validan y la aritmética cierra ───────────────────────────────

@pytest.mark.parametrize("gate", GATES)
def test_poblacion_carga_y_valida(gate):
    pop = load_population_by_gate(gate)
    assert validate_population(pop.raw) == []
    assert pop.gate == gate


@pytest.mark.parametrize("gate", GATES)
def test_distribucion_suma_exacta_el_gate(gate):
    pop = load_population_by_gate(gate)
    exp = EXPECTED[gate]
    assert pop.tenant_admins == exp["admins"]
    assert pop.compliance_officers == exp["comp"]
    assert pop.total_clients == exp["clients"]
    # La suma total es EXACTAMENTE el número del gate (población canónica del tech tree).
    assert pop.total_population == gate
    # Los buckets por superficie coinciden con R5.
    got = {b.client_type: b.count for b in pop.buckets}
    assert got == exp["buckets"]


@pytest.mark.parametrize("gate", GATES)
def test_seats_entran_en_la_licencia(gate):
    pop = load_population_by_gate(gate)
    exp = EXPECTED[gate]
    # seats = clients = llaves ≤ licencia esperada (125/250 ≤ 300, 500 ≤ 500).
    assert pop.planned_seats == exp["clients"]
    assert pop.expected_max_seats == exp["license"]
    assert pop.planned_seats <= pop.expected_max_seats


def test_plan_members_cuenta_exacta_y_cohorte_402():
    pop = load_population_by_gate(125)
    members = plan_members(pop, DEFAULT_SEED)
    assert len(members) == 125
    roles = [m.role for m in members]
    assert roles.count("tenant_admin") == 4
    assert roles.count("compliance_officer") == 2
    assert roles.count("client") == 119
    # Cohorte 402 = round(2% · 119) = 2, a los primeros 2 clients por índice.
    assert pop.cohort_402_size == 2
    clients = [m for m in members if m.is_seat]
    cohort = [m for m in clients if m.budget and m.budget.kind == "cohort_402"]
    assert len(cohort) == 2
    assert clients[0].budget.kind == "cohort_402"
    assert clients[2].budget.kind == "default"
    # Todo client lleva tool_type (la Connection = el seat) y las admin no.
    assert all(m.tool_type for m in clients)
    assert all(m.tool_type is None for m in members if m.role != "client")


def test_validacion_detecta_suma_rota():
    pop = load_population_by_gate(125)
    bad = dict(pop.raw)
    bad["roles"] = dict(bad["roles"])
    bad["roles"]["tenant_admin"] = {"count": 99}  # rompe la suma
    errors = validate_population(bad)
    assert any("suma" in e for e in errors)


def test_validacion_detecta_seats_sobre_licencia():
    pop = load_population_by_gate(500)
    bad = dict(pop.raw)
    bad["license"] = {"expected_max_seats": 100}  # 475 seats > 100
    errors = validate_population(bad)
    assert any("headroom" in e or "licencia" in e for e in errors)


# ── Pre-check de seats ────────────────────────────────────────────────────────────────

def test_precheck_excede_seats_falla_antes_de_crear():
    pop = load_population_by_gate(125)  # 119 seats
    client = FakeBackendClient(max_seats=100, seats_used=0)  # sólo 100 disponibles
    with pytest.raises(SeedError) as ei:
        seed(pop, client, seed=1)
    assert "insuficiente" in str(ei.value)
    # Fail-fast: NO se creó NADA.
    assert client.users == {}
    assert client.keys == {}
    assert client.budgets == {}


def test_precheck_cuenta_seats_ya_usados():
    pop = load_population_by_gate(125)  # 119 seats
    # 300 de licencia pero 200 ya usados → sólo 100 disponibles < 119.
    client = FakeBackendClient(max_seats=300, seats_used=200)
    with pytest.raises(SeedError) as ei:
        precheck_seats(client, pop.planned_seats)
    assert "insuficiente" in str(ei.value)


def test_precheck_licencia_ausente_es_accionable():
    client = FakeBackendClient(max_seats=None)  # max_seats nulo = licencia ausente/degradada
    with pytest.raises(SeedError) as ei:
        precheck_seats(client, 10)
    assert "licencia" in str(ei.value).lower()


def test_precheck_sin_sesion_admin_es_accionable():
    client = FakeBackendClient(admin_detail=False)  # health sin bloque de seats
    with pytest.raises(SeedError) as ei:
        precheck_seats(client, 10)
    assert "admin" in str(ei.value).lower()


# ── Seed completo: orden, conteos, idempotencia ───────────────────────────────────────

def test_seed_crea_todo_y_orden_users_antes_de_keys():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    report = seed(pop, client, seed=7)

    assert report.state == "seeded"
    assert report.users_created == 125           # 4 + 2 + 119
    assert report.keys_created == 119            # una por client
    assert report.budgets_created == 119
    assert client.seats_used == 119              # seat = llave activa

    # ORDEN: todos los eventos "user" ocurren antes que cualquier "key".
    kinds = [e[0] for e in client.events]
    last_user = max(i for i, k in enumerate(kinds) if k == "user")
    first_key = min(i for i, k in enumerate(kinds) if k == "key")
    assert last_user < first_key
    # y las keys antes que los budgets.
    last_key = max(i for i, k in enumerate(kinds) if k == "key")
    first_budget = min(i for i, k in enumerate(kinds) if k == "budget")
    assert last_key < first_budget


def test_reseed_converge_con_400_409_sin_explotar():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=7)                    # primer seed
    seats_after_first = client.seats_used

    report = seed(pop, client, seed=7)           # re-seed idéntico
    # Todo choca con duplicado y CONVERGE (nada nuevo creado, nada explota).
    assert report.users_created == 0
    assert report.users_converged == 125
    assert report.keys_created == 0
    assert report.keys_converged == 119
    assert report.budgets_created == 0
    assert report.budgets_converged == 119
    # El re-seed no consumió seats nuevos.
    assert client.seats_used == seats_after_first == 119


def test_verify_only_no_crea_y_detecta_completo():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=7)                     # sembramos
    snapshot = dict(client.users), dict(client.keys), dict(client.budgets)

    report = seed(pop, client, seed=7, verify_only=True)
    assert report.state == "verified"
    assert report.missing == []
    # verify-only no tocó nada.
    assert (client.users, client.keys, client.budgets) == snapshot


def test_verify_only_reporta_faltantes():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    # Backend vacío: la población entera falta.
    report = seed(pop, client, seed=7, verify_only=True)
    assert report.state == "absent"
    assert len(report.missing) > 0
    assert any(item.startswith("user ") for item in report.missing)


def test_error_no_duplicado_es_fail_fast():
    pop = load_population_by_gate(125)
    # 403 en create_key (p.ej. licencia degradada mid-seed) NO es duplicado → SeedError.
    client = FakeBackendClient(max_seats=300, key_error_status=403)
    with pytest.raises(SeedError) as ei:
        seed(pop, client, seed=7)
    assert "403" in str(ei.value)


# ── Determinismo ──────────────────────────────────────────────────────────────────────

def test_determinismo_identidades_y_passwords():
    pop = load_population_by_gate(125)
    a = plan_members(pop, 42)
    b = plan_members(pop, 42)
    # Misma semilla → mismas identidades y passwords, byte a byte.
    assert [(m.username, m.password, m.email) for m in a] == \
           [(m.username, m.password, m.email) for m in b]


def test_determinismo_semilla_distinta_cambia_passwords_no_identidades():
    pop = load_population_by_gate(125)
    a = plan_members(pop, 42)
    c = plan_members(pop, 43)
    # Identidades son estables (idempotencia del re-seed); las passwords cambian.
    assert [m.username for m in a] == [m.username for m in c]
    assert [m.password for m in a] != [m.password for m in c]


def test_derive_password_cumple_politica_y_es_estable():
    p1 = derive_password(42, "itv-g125-cli-0000")
    p2 = derive_password(42, "itv-g125-cli-0000")
    assert p1 == p2
    assert len(p1) >= 12  # MIN_PASSWORD_LEN del backend
    # Sin azar: no depende de reloj ni de random global.
    assert derive_password(42, "otro") != p1


# ── Regresiones del gate adversarial (FIX-1..FIX-5) ───────────────────────────────────

def test_FIX1_verify_only_no_aborta_en_gate_ya_seedeado():
    # gate-250: 238 seats. Tras sembrarlo, available = 300-238 = 62 < 238. El pre-check de
    # headroom NO debe correr en verify-only (antes abortaba y nunca llegaba a comparar).
    pop = load_population_by_gate(250)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=7)
    assert client.seats_used == 238
    report = seed(pop, client, seed=7, verify_only=True)
    assert report.state == "verified"
    assert report.missing == []


def test_FIX2a_reseed_gate500_completo_converge_sin_abortar():
    # gate-500: 475 seats, licencia 500. En un re-seed las 475 llaves siguen activas
    # (seats_used=475, available=25). El pre-check debe mirar los seats NETOS (0), no la
    # población total (475), o abortaría un re-seed que sólo iba a converger.
    pop = load_population_by_gate(500)
    client = FakeBackendClient(max_seats=500)
    seed(pop, client, seed=7)
    assert client.seats_used == 475
    report = seed(pop, client, seed=7)  # re-seed idéntico
    assert report.state == "seeded"
    assert report.users_converged == 500
    assert report.keys_converged == 475
    assert client.seats_used == 475     # sin seats nuevos


def test_FIX2b_reseed_parcial_gate250_crea_lo_que_falta():
    # Seed a medias: 140 de los 238 clients ya tienen user+key. El re-seed completo debe
    # crear los 98 que faltan sin abortar (net=98 ≤ available=300-140=160).
    pop = load_population_by_gate(250)
    client = FakeBackendClient(max_seats=300)
    clients = [m for m in plan_members(pop, 7) if m.is_seat]
    for m in clients[:140]:
        r = client.create_user(username=m.username, email=m.email, password=m.password,
                               role="client", client_type=m.client_type)
        client.create_key(name="x", user_id=r["id"], tool_type=m.tool_type)
    assert client.seats_used == 140

    report = seed(pop, client, seed=7)
    assert report.state == "seeded"
    assert report.keys_created == 98        # completó lo que faltaba
    assert report.keys_converged == 140     # los ya presentes
    assert client.seats_used == 238         # 140 + 98


def test_FIX3_summary_no_filtra_la_semilla():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    report = seed(pop, client, seed=20260808)
    s = report.summary()
    assert "semilla" not in s.lower()
    assert "20260808" not in s
    assert not hasattr(report, "seed")      # el reporte ni siquiera guarda la semilla


def test_FIX3_credenciales_no_incluyen_la_semilla():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    report = seed(pop, client, seed=20260808)
    for c in report.credentials:
        assert "seed" not in c
        assert 20260808 not in c.values()
        assert "20260808" not in str(c.get("username", ""))


def test_FIX3_cli_avisa_con_semilla_default(monkeypatch, capsys):
    import importlib
    seedmod = importlib.import_module("basa_harness.seeder.seed")
    fake = FakeBackendClient(max_seats=300)
    monkeypatch.setattr(seedmod, "BackendClient", lambda *a, **k: fake)
    seedmod.main(["--gate", "125", "--verify-only"])
    err = capsys.readouterr().err
    assert "semilla de DEV" in err          # avisa que la default es de dev


def test_FIX3_cli_sin_aviso_con_semilla_explicita(monkeypatch, capsys):
    import importlib
    seedmod = importlib.import_module("basa_harness.seeder.seed")
    fake = FakeBackendClient(max_seats=300)
    monkeypatch.setattr(seedmod, "BackendClient", lambda *a, **k: fake)
    seedmod.main(["--gate", "125", "--verify-only", "--seed", "12345"])
    err = capsys.readouterr().err
    assert "semilla de DEV" not in err


def test_FIX4_verify_reporta_budget_drift():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=7)
    # Corromper el monto de un budget existente (drift, no ausencia).
    uid = next(iter(client.budgets))
    client.budgets[uid]["max_spend_usd"] = 123456
    report = seed(pop, client, seed=7, verify_only=True)
    assert report.budget_drift
    assert any("max_spend_usd" in d for d in report.budget_drift)
    assert report.missing == []             # no falta nada, sólo el monto está mal
    assert report.state == "absent"         # el drift baja el greenlight del run


def test_FIX5_budget_400_no_duplicado_es_fail_fast():
    from basa_harness.seeder.seed import _looks_like_duplicate
    pop = load_population_by_gate(125)
    # 400 por payload inválido (no "ya existe") NO debe tragarse como convergencia.
    client = FakeBackendClient(max_seats=300,
                               budget_error=(400, "Either user_id or group_id must be provided"))
    with pytest.raises(SeedError) as ei:
        seed(pop, client, seed=7)
    assert "presupuesto" in str(ei.value)
    # el discriminante: sólo el duplicado converge.
    assert _looks_like_duplicate("Budget already exists for this user")
    assert not _looks_like_duplicate("Either user_id or group_id must be provided")


def test_FIX7_reseed_semilla_distinta_aborta_ruidoso():
    # DB sembrada con semilla 100; re-seed con OTRA semilla (olvidó `down -v`). Los
    # usernames coinciden (seed-independientes) pero las passwords no autentican → el pool
    # emitido mentiría. Debe abortar ANTES de crear/emitir nada.
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=100)
    seats_before = client.seats_used

    with pytest.raises(SeedError) as ei:
        seed(pop, client, seed=999)
    msg = str(ei.value).lower()
    assert "otra semilla" in msg or "down -v" in msg
    # no se creó nada nuevo: no emitió un pool silenciosamente inválido.
    assert client.seats_used == seats_before


def test_FIX7_reseed_misma_semilla_no_aborta():
    # Control: el re-seed con la MISMA semilla verifica OK y converge (no debe abortar).
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=100)
    report = seed(pop, client, seed=100)
    assert report.state == "seeded"
    assert report.users_converged == 125


def test_FIX8_emit_credentials_es_0600(tmp_path, monkeypatch):
    import stat
    import importlib
    seedmod = importlib.import_module("basa_harness.seeder.seed")
    fake = FakeBackendClient(max_seats=300)
    monkeypatch.setattr(seedmod, "BackendClient", lambda *a, **k: fake)
    out = tmp_path / "creds.json"
    rc = seedmod.main(["--gate", "125", "--seed", "7", "--emit-credentials", str(out)])
    assert rc == 0
    assert out.exists()
    mode = stat.S_IMODE(out.stat().st_mode)
    assert mode == 0o600, f"el pool de credenciales no debe ser world-readable, es {oct(mode)}"


# ── Material de llave en el pool (X-Basa-Key de extensión/coding) ─────────────────────
#
# Sin `basa_key` en el pool, `authHeaders` de common.js devuelve null y las superficies
# extensión y coding NO corren: el examen mediría 2 de 4 y su veredicto no sería el del
# gate. La key en claro sólo viaja en la respuesta del POST /keys.

def _creds_por_username(report):
    return {c["username"]: c for c in report.credentials}


def test_seed_captura_la_basa_key_de_cada_connection():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    report = seed(pop, client, seed=7)

    creds = _creds_por_username(report)
    members = plan_members(pop, 7)
    seats = [m for m in members if m.is_seat]
    # Toda Connection creada dejó su material en el pool…
    assert all(creds[m.username]["basa_key"] for m in seats)
    # …y es la key EN CLARO que el backend devolvió (no el preview ni el id).
    assert all(creds[m.username]["basa_key"] in client.plain_keys for m in seats)
    # Las cuentas admin no son seats: no llevan material.
    assert creds[pop.admin_username]["basa_key"] is None
    assert report.keys_sin_material == []


def test_pool_conserva_la_paridad_de_shape_con_common_js():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    report = seed(pop, client, seed=7)
    # common.js filtra por role/client_type y autentica con basa_key; el orquestador
    # exporta además tool_type. El shape del pool del seeder debe traerlos todos.
    for c in report.credentials:
        assert set(c) >= {"username", "password", "role", "client_type", "tool_type",
                          "basa_key"}
    # Los pools por superficie de common.js no quedan vacíos.
    assert any(c["client_type"] == "desktop" for c in report.credentials)     # extensión
    assert any(c["client_type"] == "base_url" for c in report.credentials)    # coding
    assert any(c["role"] == "compliance_officer" for c in report.credentials)  # admin/SLO


def test_reseed_sin_key_recuperable_marca_las_identidades_y_no_regala_el_examen():
    # Las Connections ya existen (re-seed): el backend NO vuelve a dar la key en claro.
    # El pool sale con basa_key null y el reporte marca a las identidades afectadas.
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=7)
    report = seed(pop, client, seed=7)      # re-seed: todo converge

    assert report.keys_converged == 119
    creds = _creds_por_username(report)
    afectadas = [m for m in plan_members(pop, 7)
                 if m.client_type in ("desktop", "base_url")]
    assert report.keys_sin_material == [m.username for m in afectadas]
    assert all(creds[u]["basa_key"] is None for u in report.keys_sin_material)
    # chat_ui va por JWT: su falta de material no marca nada.
    assert not any(m.client_type == "chat_ui" and m.username in report.keys_sin_material
                   for m in plan_members(pop, 7))


def test_verify_only_recupera_las_keys_del_pool_previo_y_las_valida():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    sembrado = seed(pop, client, seed=7)
    pool_previo = sembrado.credentials          # el pool que quedó en disco

    client.whoami_calls.clear()                 # separar el apply del verify
    report = seed(pop, client, seed=7, verify_only=True, pool_previo=pool_previo)
    assert report.state == "verified"
    assert report.keys_sin_material == []
    creds = _creds_por_username(report)
    assert all(creds[c["username"]]["basa_key"] == c["basa_key"]
               for c in pool_previo if c.get("basa_key"))
    # se validan TODAS las keys del pool, no una muestra: una revocación PARCIAL (la
    # mitad de las Connections caídas) pasaba desapercibida con [:4] y dejaba el examen
    # midiendo superficies mudas.
    con_material = [c for c in pool_previo if c.get("basa_key")]
    assert len(client.whoami_calls) == len(con_material) > 4


def test_apply_tambien_valida_que_las_keys_sirvan():
    """M3: `_seal_key_material` sólo comprueba PRESENCIA. Sin esta validación, `apply`
    emitía un pool con keys inservibles y EXIT 0, y extensión/coding fallaban en masa
    durante el examen con `harness_errors` como único síntoma."""
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    report = seed(pop, client, seed=7)
    con_material = [c for c in report.credentials if c.get("basa_key")]
    assert len(client.whoami_calls) == len(con_material) > 0


def test_verify_only_sin_pool_previo_marca_las_superficies_sin_material():
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    seed(pop, client, seed=7)
    client.whoami_calls.clear()                            # separar el apply del verify
    report = seed(pop, client, seed=7, verify_only=True)   # sin pool en disco
    assert report.keys_sin_material                        # no se puede correr el examen
    assert client.whoami_calls == []                       # no había nada que validar


def test_verify_only_con_key_que_no_autentica_aborta_ruidoso():
    # Pool de OTRA instalación (o Connection revocada): las keys no resuelven en /gw/whoami.
    # Igual que el mismatch de semilla, aborta ANTES de dar el run por verificado.
    pop = load_population_by_gate(125)
    client = FakeBackendClient(max_seats=300)
    sembrado = seed(pop, client, seed=7)
    ajeno = [dict(c, basa_key=("sk-ajena" if c.get("basa_key") else None))
             for c in sembrado.credentials]

    with pytest.raises(SeedError) as ei:
        seed(pop, client, seed=7, verify_only=True, pool_previo=ajeno)
    assert "whoami" in str(ei.value).lower()


def test_cli_sale_distinto_de_cero_si_falta_material_de_llave(tmp_path, monkeypatch, capsys):
    import importlib
    seedmod = importlib.import_module("basa_harness.seeder.seed")
    fake = FakeBackendClient(max_seats=300)
    monkeypatch.setattr(seedmod, "BackendClient", lambda *a, **k: fake)
    out = tmp_path / "creds.json"

    assert seedmod.main(["--gate", "125", "--seed", "7", "--emit-credentials", str(out)]) == 0
    # Segundo seed: las Connections ya existen → sin key recuperable → EXIT ≠ 0.
    rc = seedmod.main(["--gate", "125", "--seed", "7", "--emit-credentials", str(out)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "basa_key" in err
    # El pool se emite igual, con el campo en null para que se VEA cuál falta.
    pool = json.loads(out.read_text(encoding="utf-8"))
    desktop = [c for c in pool if c["client_type"] == "desktop"]
    assert desktop and all(c["basa_key"] is None for c in desktop)


def test_cli_verify_only_lee_el_pool_emitido_para_recuperar_las_keys(tmp_path, monkeypatch):
    import importlib
    seedmod = importlib.import_module("basa_harness.seeder.seed")
    fake = FakeBackendClient(max_seats=300)
    monkeypatch.setattr(seedmod, "BackendClient", lambda *a, **k: fake)
    out = tmp_path / "creds.json"
    assert seedmod.main(["--gate", "125", "--seed", "7", "--emit-credentials", str(out)]) == 0

    rc = seedmod.main(["--gate", "125", "--seed", "7", "--verify-only",
                       "--emit-credentials", str(out)])
    assert rc == 0                       # el pool en disco tenía las keys y validaron
    assert fake.whoami_calls             # se comprobó la muestra contra /gw/whoami


def test_FIX8_emit_credentials_0600_incluso_si_ya_existia(tmp_path, monkeypatch):
    import stat
    import importlib
    seedmod = importlib.import_module("basa_harness.seeder.seed")
    fake = FakeBackendClient(max_seats=300)
    monkeypatch.setattr(seedmod, "BackendClient", lambda *a, **k: fake)
    out = tmp_path / "creds.json"
    out.write_text("viejo", encoding="utf-8")  # preexistente con permisos laxos
    out.chmod(0o644)
    seedmod.main(["--gate", "125", "--seed", "7", "--emit-credentials", str(out)])
    assert stat.S_IMODE(out.stat().st_mode) == 0o600


def test_verify_only_con_pool_corrupto_no_lo_pisa(tmp_path):
    """M5: el pool en disco es la ÚNICA fuente de las basa_key (el backend no las devuelve
    dos veces). Ante un JSON corrupto el seeder seguía adelante SIN material y el paso
    siguiente reescribía ese mismo archivo con basa_key: null — destruyendo material
    irrecuperable y obligando a un `down -v`. Ahora aborta sin tocarlo."""
    from basa_harness.seeder.seed import _read_pool

    pool = tmp_path / "pool.json"
    pool.write_text('{"esto": no es json', encoding="utf-8")
    with pytest.raises(SeedError) as ei:
        _read_pool(pool)
    assert "no se puede leer" in str(ei.value)
    assert pool.read_text(encoding="utf-8") == '{"esto": no es json'   # intacto

    # Tampoco se pisa un archivo cuyo contenido no se entiende.
    otro = tmp_path / "otro.json"
    otro.write_text('{"credenciales": []}', encoding="utf-8")
    with pytest.raises(SeedError):
        _read_pool(otro)

    # Que NO exista es otra cosa: primer run, se sigue sin material.
    assert _read_pool(tmp_path / "no-existe.json") is None
