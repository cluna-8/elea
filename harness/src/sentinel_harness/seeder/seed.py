"""Orquestador del seeder + CLI (spec 035, T020; research R5; data-model §Población/Seed).

Aprovisiona reproduciblemente la población del examen contra la API REST real, en la
SECUENCIA de R5 y con las guardas que la spec pide:

  bootstrap admin  →  PRE-CHECK de seats (fail-fast)  →  users  →  keys  →  budgets

- **Pre-check de seats**: lee ``GET /health/license`` (max_seats/seats_used) y, si el
  headroom vivo no alcanza para las llaves planificadas, ABORTA antes de crear nada, con
  un mensaje accionable. Cubre el edge case "licencia insuficiente detectada tarde"
  (data-model §Run) y el caso T022 "licencia insuficiente" (licencia ausente/degradada).
- **Orden users→keys**: los users se crean ANTES que las keys porque el seat gate corre
  en ambos call-sites (``enforce_seat_gate`` en users.py:165 y keys.py:130); el seat sólo
  se CONSUME al crear la llave (seat = Connection activa, seat_counter.py).
- **Idempotente**: las identidades son estables (population.derive_username), así que un
  re-seed choca con 400 (user/budget duplicado) o 409 (Connection duplicada) y
  CONVERGE — no explota. Los duplicados esperados se capturan; cualquier otro status
  (402/403/422…) es fail-fast con contexto.
- **verify-only**: entre runs, sin crear nada — lista y comprueba que la población
  declarada está completa; reporta lo que falte.
- **Material de llave en el pool** (corrida real): ``POST /keys`` devuelve la key EN CLARO
  (``plain_key``) UNA sola vez — la DB guarda hash+preview y no hay endpoint que la
  recupere. Se captura al vuelo y viaja en el pool emitido como ``sentinel_key``, porque las
  superficies extensión/coding de k6 se autentican con ``X-Sentinel-Key`` (common.js
  ``authHeaders``) y sin ella NO pueden correr. Si alguna identidad de esas dos
  superficies queda sin material, el seeder termina con EXIT ≠ 0: el examen no corre a
  medias con dos superficies mudas.

DETERMINISMO: toda la lógica que los tests verifican deriva de ``(seed, gate, idx)`` —
sin ``uuid``/``time``/``random``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from .client import BackendClient, BackendError, SeedClient
from .population import (Member, Population, derive_password, load_population,
                        load_population_by_gate, plan_members)

# Semilla por defecto: fija para que "seedear una vez por despliegue" sea reproducible.
# Cambiarla cambia TODAS las passwords derivadas → exige DB fresca (down -v). Ver README.
DEFAULT_SEED = 20260808

# Cuántas credenciales derivadas se comprueban contra la DB antes de crear/verificar
# (FIX-7): suficientes para detectar un mismatch de semilla en masa sin pagar N logins.
_CREDENTIAL_SAMPLE = 4

# client_type cuyas superficies k6 se autentican con la KEY de la Connection (X-Sentinel-Key),
# no con JWT: `desktop` → extensión, `base_url` → coding-SSE (scenarios/common.js:144-152).
# `chat_ui` va por JWT, así que su identidad no necesita material de llave para correr.
KEY_SURFACE_CLIENT_TYPES: frozenset[str] = frozenset({"desktop", "base_url"})


class SeedError(RuntimeError):
    """Fallo accionable de seeding (pre-check, licencia, reconciliación imposible).

    Se distingue de ``BackendError`` (un status HTTP crudo): un ``SeedError`` ya trae el
    mensaje pensado para el operador."""


@dataclass
class SeedReport:
    gate: int
    state: str  # "absent" | "seeded" | "verified"
    planned_seats: int
    # FIX-3: la SEMILLA NO se guarda en el reporte ni se imprime — con ella + el código,
    # las passwords de toda la población (incluido admin) son derivables. Se pasa por
    # parámetro donde hace falta y nunca viaja a stdout ni a un archivo trackeable.
    license: dict = field(default_factory=dict)
    users_created: int = 0
    users_converged: int = 0
    keys_created: int = 0
    keys_converged: int = 0
    budgets_created: int = 0
    budgets_converged: int = 0
    missing: list[str] = field(default_factory=list)
    # FIX-4: budgets presentes pero con monto distinto al planificado (drift). No se
    # corrige automáticamente, pero se REPORTA (un budget mal contamina el gate).
    budget_drift: list[str] = field(default_factory=list)
    # Pool de credenciales (username/password/rol/client_type/tool_type/sentinel_key) para k6
    # y el lector de SLO.
    credentials: list[dict] = field(default_factory=list)
    # Identidades de extensión/coding que quedaron SIN material de llave (la Connection ya
    # existía y su key en claro no es recuperable). El pool las marca con `sentinel_key: null`;
    # el CLI sale con EXIT ≠ 0 porque esas dos superficies no podrían autenticarse.
    keys_sin_material: list[str] = field(default_factory=list)

    def summary(self) -> str:
        sin_key = (f" ⚠ {len(self.keys_sin_material)} identidades de extensión/coding SIN "
                   "material de llave" if self.keys_sin_material else "")
        if self.state == "verified":
            drift = f" (⚠ {len(self.budget_drift)} budgets con drift)" if self.budget_drift else ""
            return (f"gate {self.gate}: VERIFICADO — {self.planned_seats} seats, población "
                    f"completa{drift}.{sin_key}")
        if self.state == "absent":
            parts = []
            if self.missing:
                parts.append(f"faltan {len(self.missing)} elementos")
            if self.budget_drift:
                parts.append(f"{len(self.budget_drift)} budgets con drift")
            if self.keys_sin_material:
                parts.append(f"{len(self.keys_sin_material)} sin material de llave")
            return f"gate {self.gate}: INCOMPLETO — {', '.join(parts)} (ver detalle)."
        return (f"gate {self.gate}: SEEDED — users +{self.users_created}/~{self.users_converged}, "
                f"keys +{self.keys_created}/~{self.keys_converged}, "
                f"budgets +{self.budgets_created}/~{self.budgets_converged} "
                f"(seats {self.planned_seats}).{sin_key}")


# ── Licencia + pre-check de seats ─────────────────────────────────────────────────────

def _license_state(client: SeedClient) -> dict:
    """Lee ``GET /health/license`` y valida que la licencia EXISTE y es admin-visible.

    Corre SIEMPRE — también en ``verify-only`` (FIX-1): si la licencia está ausente o
    degradada, ni siquiera verificar tiene sentido, y esta comprobación NO depende de
    crear seats. NO chequea headroom (eso es exclusivo de la creación → ``precheck_seats``).

    Levanta ``SeedError`` accionable si la sesión no ve el detalle (no es admin) o si
    ``max_seats`` es nulo (licencia ausente/degradada, creación fail-closed).

    FIX-6 (límite del producto, NO se arregla acá): ``/health/license`` cuenta los seats
    del ``expected_tenant_id()`` (``SENTINEL_DEPLOYMENT_TENANT_ID``), mientras que el seat gate
    de ``keys.py`` cuenta contra ``DEFAULT_TENANT_ID`` hasta que la 013 resuelva tenant en
    los handlers. Si ambos difieren, ``seats_used`` acá podría contar otro tenant que el
    que el gate realmente enforcea. En el examen coinciden (client.env fija
    ``SENTINEL_DEPLOYMENT_TENANT_ID=00000000-…-0001`` = DEFAULT), así que el pre-check es fiel;
    queda advertido en el README del perfil.
    """
    health = client.license_health()
    if "max_seats" not in health:
        raise SeedError(
            "no se pudo leer la licencia: GET /health/license no devolvió el detalle de "
            "seats. ¿La sesión es admin (tenant_admin/compliance_officer) y la licencia "
            f"está instalada? status={health.get('status')!r}.")
    max_seats = health.get("max_seats")
    if max_seats is None:
        raise SeedError(
            "licencia ausente o degradada: max_seats es nulo, así que la CREACIÓN de "
            f"seats está bloqueada (fail-closed). status={health.get('status')!r} "
            f"reason={health.get('reason')!r}. Instalá la licencia definitiva ANTES de "
            "seedear (ver el comando issue_license.py en el README del perfil).")
    seats_used = int(health.get("seats_used") or 0)
    return {"max_seats": max_seats, "seats_used": seats_used,
            "available": max_seats - seats_used, "status": health.get("status")}


def precheck_seats(client: SeedClient, net_seats_needed: int) -> dict:
    """Falla ANTES de crear si no hay headroom para los seats que faltan CREAR.

    ``net_seats_needed`` es el NETO (planificados − ya presentes), no la población total
    (FIX-2): en un re-seed las llaves ya creadas por esta misma población siguen activas y
    cuentan en ``seats_used`` — compararlas contra la población entera las double-contaría
    y abortaría un re-seed que sólo iba a converger. Devuelve el bloque de licencia si pasa.
    """
    info = _license_state(client)
    if info["available"] < net_seats_needed:
        raise SeedError(
            f"licencia insuficiente: faltan crear {net_seats_needed} seats y sólo hay "
            f"{info['available']} disponibles ({info['seats_used']}/{info['max_seats']} en "
            "uso). Ampliá la licencia (issue_license.py --max-seats …) o reducí la "
            "población. No se creó nada.")
    return info


# ── Orquestación ──────────────────────────────────────────────────────────────────────

def seed(pop: Population, client: SeedClient, *, seed: Union[int, str] = DEFAULT_SEED,
         verify_only: bool = False, admin_password: Optional[str] = None,
         pool_previo: Optional[list] = None) -> SeedReport:
    """Ejecuta (o verifica) el seed de ``pop`` contra ``client``.

    ``client`` es cualquier cosa que cumpla ``SeedClient`` (el ``BackendClient`` real o el
    falso de los tests). ``seed`` fija identidades/passwords deterministas.

    ``pool_previo`` (sólo ``verify_only``): pool ya emitido en disco, del que se recuperan
    las ``sentinel_key`` — el backend no las devuelve dos veces. Se validan contra
    ``/gw/whoami`` sobre una muestra, mismo criterio que ``_assert_seed_matches``.

    OJO: ``report.keys_sin_material`` no vacío significa que el examen NO puede correr
    completo (extensión/coding sin autenticación). El CLI lo convierte en EXIT ≠ 0; un
    llamador programático DEBE mirarlo."""
    members = plan_members(pop, seed)
    admin_pwd = admin_password or derive_password(seed, pop.admin_username)

    # 1) Bootstrap del primer admin (o login si ya existe) — habilita el resto.
    #    FIX-7: si el admin ya existe con OTRA password (DB de otra semilla), el login da
    #    401 → abortamos ruidoso en vez de seguir con una sesión que no vamos a obtener.
    try:
        client.bootstrap_admin(pop.admin_username, admin_pwd)
    except BackendError as e:
        if e.status_code == 401:
            raise SeedError(
                "el admin de bootstrap ya existe con OTRA password: esta instalación fue "
                "sembrada con otra semilla (o con --admin-password distinto). Hacé `down -v` "
                "y re-seedeá, o pasá la semilla/password original. No se creó nada.") from e
        raise

    report = SeedReport(gate=pop.gate,
                        state="verified" if verify_only else "seeded",
                        planned_seats=pop.planned_seats,
                        credentials=_credentials(members, pop.admin_username, admin_pwd))

    if verify_only:
        # FIX-1: en verify NO se crea nada, así que NO se chequea headroom de seats (eso
        # abortaba verify-only sobre poblaciones 250/500 ya sembradas). Sólo se valida que
        # la licencia exista / sea admin-visible (legítimo también en verify).
        report.license = _license_state(client)
        return _verify(pop, client, members, report, pool_previo)
    return _apply(pop, client, members, report)


def _assert_seed_matches(client: SeedClient, present: list[Member]) -> None:
    """FIX-7: comprueba que las credenciales DERIVADAS autentican, sobre una muestra de los
    miembros que YA existen en la DB.

    Los usernames son seed-independientes (idempotencia), pero las passwords derivan de la
    semilla. Si alguien re-siembra una DB existente con OTRA semilla (se olvidó del
    ``down -v``), el alta da 400→converge SIN actualizar la password: el pool emitido
    llevaría passwords que el backend nunca aceptó y el login storm de k6 fallaría en masa
    por una causa imposible de diagnosticar. Verificar una muestra lo caza temprano y
    ANTES de crear/emitir nada. Sale barato: sólo se paga cuando hay miembros presentes
    (re-seed/verify), no en un seed fresco."""
    for m in present[:_CREDENTIAL_SAMPLE]:
        if not client.verify_credential(m.username, m.password):
            raise SeedError(
                f"la credencial derivada de {m.username!r} NO autentica contra la DB: esta "
                "instalación fue sembrada con OTRA semilla (o con --admin-password "
                "distinto). El pool de credenciales mentiría sobre lo que el backend acepta "
                "y el login storm de k6 fallaría en masa. Hacé `down -v` y re-seedeá, o "
                "pasá la semilla original.")


def _apply(pop: Population, client: SeedClient, members: list[Member],
           report: SeedReport) -> SeedReport:
    # Estado actual del backend: username→id y set de Connections activas. Se lista UNA vez
    # y se reusa para (a) el pre-check NETO y (b) la convergencia del re-seed. En un seed
    # fresco estas listas vuelven casi vacías (sólo el admin del bootstrap) — barato.
    users_map: dict[str, str] = {u["username"]: str(u["id"]) for u in client.list_users()}
    active_keys: set[tuple] = {
        (str(k["user_id"]), k["tool_type"]) for k in client.list_keys()
        if k.get("user_id") is not None and k.get("is_active", True)}

    # FIX-7: si esto es un re-seed (hay miembros ya presentes), verificar que la semilla
    # coincide ANTES de crear nada — así no emitimos un pool que la DB nunca aceptó.
    _assert_seed_matches(client, [m for m in members if m.username in users_map])

    # FIX-2: pre-check contra los seats NETOS a crear = clients cuya llave (user, tool_type)
    # todavía NO existe. Así un re-seed (llaves ya activas) no se double-cuenta a sí mismo.
    clients = [m for m in members if m.is_seat]
    net_seats = sum(
        1 for m in clients
        if users_map.get(m.username) is None
        or (users_map[m.username], m.tool_type) not in active_keys)
    report.license = precheck_seats(client, net_seats)

    # Users PRIMERO (todos), luego keys, luego budgets — el orden de R5 (el seat gate corre
    # en users.py y keys.py, pero el seat sólo se CONSUME al crear la llave).
    ids: dict[str, str] = {}
    creds = _credentials_by_username(report)
    for m in members:
        ids[m.username] = _create_or_converge_user(client, m, users_map, report)
    for m in clients:
        _create_or_converge_key(client, m, ids[m.username], active_keys, report,
                                creds.get(m.username))
    for m in clients:
        if m.budget is not None:
            _create_or_converge_budget(client, m, ids[m.username], report)

    _seal_key_material(members, creds, report)
    # El seal comprueba PRESENCIA del material; esto comprueba que SIRVE. Sin esta
    # llamada, `apply` emitía un pool con keys inservibles y EXIT 0 (una Connection
    # preexistente cuya key en claro ya no se recupera, o un stack re-creado): extensión y
    # coding fallarían en masa y el summary sólo mostraría `harness_errors`.
    _assert_keys_usable(client, report)
    return report


def _create_or_converge_user(client: SeedClient, m: Member,
                             users_map: dict, report: SeedReport) -> str:
    existing = users_map.get(m.username)
    if existing is not None:  # ya presente (re-seed) → convergemos sin tocar el backend
        report.users_converged += 1
        return existing
    try:
        resp = client.create_user(username=m.username, email=m.email, password=m.password,
                                  role=m.role, client_type=m.client_type)
        report.users_created += 1
        uid = str(resp["id"])
        users_map[m.username] = uid
        return uid
    except BackendError as e:
        if not e.is_duplicate:
            # 402/403 = seat gate/licencia mid-seed; 422 = user sin engine_user_id, etc.
            raise SeedError(
                f"alta de usuario {m.username!r} falló ({e.status_code}): {e.detail}. "
                "El pre-check pasó, así que esto es un cambio de estado del stack durante "
                "el seed (licencia que encogió, motor caído): revisá y reintentá."
            ) from e
        # Duplicado bajo carrera (listado stale): refrescar y reconciliar el id.
        users_map.update({u["username"]: str(u["id"]) for u in client.list_users()})
        uid = users_map.get(m.username)
        if uid is None:
            raise SeedError(
                f"usuario {m.username!r} reportó duplicado ({e.status_code}) pero no aparece "
                "al listar: estado inconsistente del backend."
            ) from e
        report.users_converged += 1
        return uid


def _create_or_converge_key(client: SeedClient, m: Member, user_id: str,
                           active_keys: set, report: SeedReport,
                           cred: Optional[dict] = None) -> None:
    if (user_id, m.tool_type) in active_keys:  # Connection ya activa → convergemos
        report.keys_converged += 1
        # La key en claro de una Connection preexistente NO es recuperable (la DB guarda
        # key_hash + key_preview, keys.py:194-206): `sentinel_key` queda en null y
        # `_seal_key_material` decide si eso deja al examen inservible.
        return
    try:
        resp = client.create_key(name=f"{m.username}-{m.tool_type}", user_id=user_id,
                                 tool_type=m.tool_type)
        report.keys_created += 1
        active_keys.add((user_id, m.tool_type))
        # `plain_key` viaja UNA sola vez (KeyGeneratedResponse, keys.py:221-230): o se
        # captura acá, o la identidad se queda sin material para siempre.
        material = resp.get("plain_key") if isinstance(resp, dict) else None
        if cred is not None and isinstance(material, str) and material:
            cred["sentinel_key"] = material
    except BackendError as e:
        # 409 = Connection duplicada (único duplicado que keys.py devuelve). 400 no existe
        # para keys; 402/403 = seat gate/licencia; 422 = user sin engine_user_id.
        if e.status_code != 409:
            raise SeedError(
                f"alta de Connection para {m.username!r} ({m.tool_type}) falló "
                f"({e.status_code}): {e.detail}. Si es 402/403 la licencia no alcanza "
                "para tantos seats (revisá el pre-check); si es 422 el usuario se creó sin "
                "engine_user_id (motor caído en el alta)."
            ) from e
        report.keys_converged += 1


def _create_or_converge_budget(client: SeedClient, m: Member, user_id: str,
                              report: SeedReport) -> None:
    assert m.budget is not None
    try:
        client.create_budget(user_id=user_id, max_spend_usd=m.budget.max_spend_usd,
                             max_tokens=m.budget.max_tokens,
                             reset_period=m.budget.reset_period)
        report.budgets_created += 1
    except BackendError as e:
        # FIX-5: budgets.py devuelve 400 tanto para "ya existe" (convergible) como para
        # payload inválido (user+group, ninguno de los dos…). Sólo el duplicado converge;
        # cualquier otro 400 debe fallar ruidoso en vez de tragarse como "ya estaba".
        if e.status_code == 400 and _looks_like_duplicate(e.detail):
            report.budgets_converged += 1
            return
        raise SeedError(
            f"alta de presupuesto para {m.username!r} falló ({e.status_code}): {e.detail}."
        ) from e


def _verify(pop: Population, client: SeedClient, members: list[Member],
            report: SeedReport, pool_previo: Optional[list] = None) -> SeedReport:
    users = {u["username"]: str(u["id"]) for u in client.list_users()}
    # FIX-7: verify-only también emite el pool de credenciales; comprobá una muestra para
    # no dar por buena una población sembrada con otra semilla.
    _assert_seed_matches(client, [m for m in members if m.username in users])
    keys = {(str(k["user_id"]), k["tool_type"]) for k in client.list_keys()
            if k.get("user_id") is not None and k.get("is_active", True)}
    # FIX-4: guardamos los MONTOS del budget por user (no sólo su presencia) para detectar
    # drift. GET /budgets devuelve max_spend_usd/max_tokens (BudgetResponse).
    budgets = {str(b["user_id"]): b for b in client.list_budgets()
               if b.get("user_id") is not None}

    missing: list[str] = []
    drift: list[str] = []
    for m in members:
        uid = users.get(m.username)
        if uid is None:
            missing.append(f"user {m.username}")
            continue
        if not m.is_seat:
            continue
        if (uid, m.tool_type) not in keys:
            missing.append(f"key {m.username}:{m.tool_type}")
        if m.budget is not None:
            got = budgets.get(uid)
            if got is None:
                missing.append(f"budget {m.username}")
            else:
                d = _budget_drift(m, got)
                if d:
                    drift.append(f"budget {m.username}: {d}")

    report.missing = missing
    report.budget_drift = drift
    # Material de llave: verify NO puede recrearlo (la key en claro no se recupera), así
    # que sale del pool ya emitido en disco y se COMPRUEBA contra el producto.
    creds = _credentials_by_username(report)
    _merge_key_material(creds, pool_previo)
    _assert_keys_usable(client, report)
    _seal_key_material(members, creds, report)
    # Sólo "verified" con población COMPLETA y sin drift: verify greenlightea un run, y un
    # budget mal (p.ej. generoso donde debía ser ínfimo) contaminaría el gate.
    report.state = "verified" if not missing and not drift else "absent"
    return report


# ── Material de llave del pool (X-Sentinel-Key de extensión/coding) ───────────────────────

def _credentials_by_username(report: SeedReport) -> dict:
    return {c["username"]: c for c in report.credentials}


def _merge_key_material(creds: dict, pool_previo: Optional[list]) -> None:
    """Recupera las ``sentinel_key`` de un pool ya emitido (verify-only).

    El backend devuelve la key en claro UNA vez; entre runs, la única fuente es el pool
    0600 que el seed dejó en disco. Se copia SOLO el material (nunca passwords ni roles:
    esos se re-derivan de la semilla y son la fuente de verdad)."""
    if not pool_previo:
        return
    for entry in pool_previo:
        if not isinstance(entry, dict):
            continue
        material = entry.get("sentinel_key")
        cred = creds.get(entry.get("username"))
        if cred is not None and isinstance(material, str) and material:
            cred["sentinel_key"] = material


def _assert_keys_usable(client: SeedClient, report: SeedReport) -> None:
    """Comprueba contra ``/gw/whoami`` que las ``sentinel_key`` del pool AUTENTICAN.

    Mismo criterio que ``_assert_seed_matches`` (FIX-7) y por la misma razón: un pool con
    keys que el backend ya no acepta (Connection revocada, stack re-creado, pool de otra
    instalación) haría fallar extensión y coding EN MASA por una causa imposible de
    diagnosticar desde el summary de k6 — ahí sólo se ve `harness_errors`.

    Se comprueban TODAS las identidades con material, no una muestra: sobre 119-500
    cuentas son unos cientos de GET baratos contra el propio SUT (segundos), y una
    revocación PARCIAL —la mitad de las Connections caídas— pasaba desapercibida con
    `[:4]`. El costo de la muestra no compensa certificar un examen a medias."""
    con_material = [c for c in report.credentials if c.get("sentinel_key")]
    for c in con_material:
        if not client.verify_sentinel_key(c["sentinel_key"]):
            raise SeedError(
                f"la sentinel_key de {c['username']!r} NO autentica contra /gw/whoami: el pool "
                "en disco es de OTRA instalación o esa Connection fue revocada. Las "
                "superficies extensión y coding fallarían en masa. Re-seedeá contra un "
                "stack fresco (`down -v`) y volvé a emitir el pool.")


def _seal_key_material(members: list[Member], creds: dict, report: SeedReport) -> None:
    """Marca las identidades de extensión/coding que quedaron SIN ``sentinel_key``.

    Fail-closed operativo: k6 no puede autenticar esas superficies sin la key
    (common.js ``authHeaders`` devuelve null y la iteración cuenta como `harness_errors`),
    así que el examen mediría 2 de 4 superficies y el veredicto no sería el del gate. El
    pool se emite igual —con el campo en null, para que se VEA cuál falta— pero el CLI
    sale con EXIT ≠ 0."""
    faltan = []
    for m in members:
        if m.client_type not in KEY_SURFACE_CLIENT_TYPES:
            continue
        cred = creds.get(m.username)
        if cred is None or not cred.get("sentinel_key"):
            faltan.append(m.username)
    report.keys_sin_material = faltan


def _budget_drift(m: Member, got: dict) -> Optional[str]:
    """Describe el drift entre el budget planificado y el observado, o None si coinciden."""
    assert m.budget is not None
    diffs: list[str] = []
    if "max_spend_usd" in got and float(got["max_spend_usd"]) != float(m.budget.max_spend_usd):
        diffs.append(f"max_spend_usd {got['max_spend_usd']}≠{m.budget.max_spend_usd}")
    if "max_tokens" in got and int(got["max_tokens"]) != int(m.budget.max_tokens):
        diffs.append(f"max_tokens {got['max_tokens']}≠{m.budget.max_tokens}")
    return ", ".join(diffs) if diffs else None


# Marcadores de "ya existe" en el detail (FastAPI, es/en) para distinguir un 400-duplicado
# de un 400 por payload inválido (FIX-5).
_ALREADY_EXISTS_MARKERS = ("already exist", "already registered", "duplicate", "ya existe")


def _looks_like_duplicate(detail: str) -> bool:
    d = (detail or "").lower()
    return any(marker in d for marker in _ALREADY_EXISTS_MARKERS)


def _credentials(members: list[Member], admin_username: str, admin_password: str) -> list[dict]:
    """Pool de credenciales para k6 (SharedArray) y el lector de SLO (una compliance).

    Passwords REALES conocidas — imprescindibles para el login storm del gate 250 y el
    JWT del chat (R5). Es material de RUN: se emite fuera del repo (``runs/`` es scratch
    gitignored), nunca se commitea.

    Shape PARITARIO con el pool que exporta el orquestador (``_export_identities``) y que
    consume ``scenarios/common.js``: ``username``/``password``/``role``/``client_type``
    (filtros de pool por superficie) + ``tool_type`` + ``sentinel_key`` (X-Sentinel-Key de
    extensión/coding, se rellena al crear la Connection)."""
    creds = [{"username": admin_username, "password": admin_password, "role": "tenant_admin",
              "client_type": None, "tool_type": None, "bootstrap": True, "sentinel_key": None}]
    for m in members:
        creds.append({"username": m.username, "password": m.password, "role": m.role,
                      "client_type": m.client_type, "tool_type": m.tool_type,
                      "sentinel_key": None})
    return creds


# ── CLI ───────────────────────────────────────────────────────────────────────────────

def _write_credentials(path: Path, credentials: list[dict]) -> None:
    """Escribe el pool con permisos 0600 (FIX-8): son passwords EN CLARO y el host puede
    ser compartido — no deben quedar world-readable ni un instante.

    Se crea con ``os.open`` en 0600 (nada de 0644 default). Residual del gate del core:
    si el archivo YA existía con permisos laxos, ``O_CREAT`` no cambia su modo, así que se
    hace ``fchmod`` sobre el fd ANTES de escribir — cero ventana world-readable ni en el
    path de sobrescritura (no solo el fresco)."""
    data = json.dumps(credentials, ensure_ascii=False, indent=2)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)  # cierra la ventana del path de sobrescritura de un 0644 previo
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)


def _load_population_arg(args) -> Population:
    if args.population:
        return load_population(args.population)
    if args.gate is None:
        raise SystemExit("error: indicá --gate <N> o --population <ruta>")
    return load_population_by_gate(args.gate)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m sentinel_harness.seeder.seed",
        description="Aprovisiona (o verifica) la población del examen vía la API real.")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--gate", type=int, choices=(125, 250, 500),
                     help="carga populations/gate-<N>.yaml")
    src.add_argument("--population", type=Path, help="ruta a un YAML de población")
    p.add_argument("--backend-url", default="http://localhost:8000",
                   help="base del backend (default: http://localhost:8000)")
    # FIX-3: default=None para poder distinguir "no pasó --seed" de un valor explícito. NO
    # se muestra el valor de la semilla (con ella + el código las passwords son derivables).
    p.add_argument("--seed", type=int, default=None,
                   help="semilla de identidades/passwords (un gate OFICIAL debe pasarla "
                        "explícita; sin ella se usa un default de dev con warning)")
    p.add_argument("--verify-only", action="store_true",
                   help="no crea nada: lista y comprueba que la población está completa")
    p.add_argument("--admin-password", default=None,
                   help="password del admin bootstrap (default: derivada de la semilla)")
    p.add_argument("--emit-credentials", type=Path, default=None,
                   help="escribe el pool de credenciales (JSON 0600) para k6; NO lo "
                        "commitees. Con --verify-only, si el archivo YA existe se LEE "
                        "primero para recuperar las sentinel_key (el backend no las devuelve "
                        "dos veces) y se validan contra /gw/whoami")
    p.add_argument("--timeout", type=float, default=30.0, help="timeout HTTP en segundos")
    args = p.parse_args(argv)

    pop = _load_population_arg(args)

    if args.seed is None:
        seed_value: int = DEFAULT_SEED
        print("⚠ usando la semilla de DEV por defecto: las passwords de la población son "
              "derivables de forma reproducible. Un gate OFICIAL debe pasar --seed explícito "
              "(secreto del run, fuera del repo).", file=sys.stderr)
    else:
        seed_value = args.seed

    # verify-only: el material de llave sale del pool YA emitido (el backend no devuelve
    # la key en claro dos veces). Sin ese archivo no hay nada que validar.
    try:
        pool_previo = _read_pool(args.emit_credentials) if args.verify_only else None
    except SeedError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2

    try:
        with BackendClient(args.backend_url, timeout=args.timeout) as client:
            report = seed(pop, client, seed=seed_value, verify_only=args.verify_only,
                          admin_password=args.admin_password, pool_previo=pool_previo)
    except SeedError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 2
    except BackendError as e:
        print(f"❌ backend: {e}", file=sys.stderr)
        return 2

    print(report.summary())
    for item in report.missing:
        print(f"  falta: {item}", file=sys.stderr)
    for item in report.budget_drift:
        print(f"  drift: {item}", file=sys.stderr)
    if args.emit_credentials:
        _write_credentials(args.emit_credentials, report.credentials)
        print(f"credenciales → {args.emit_credentials} (material de run 0600, no lo commitees)")
    # Sin material de llave, extensión y coding no pueden autenticarse: el examen correría
    # con 2 de 4 superficies mudas y su veredicto NO sería el del gate. Exit ≠ 0 SIEMPRE,
    # aunque la población esté completa.
    if report.keys_sin_material:
        muestra = ", ".join(report.keys_sin_material[:5])
        print(f"❌ {len(report.keys_sin_material)} identidad(es) de extensión/coding sin "
              f"sentinel_key (p. ej. {muestra}): sus Connections ya existían y la key en claro "
              "no es recuperable. k6 no podría autenticar esas superficies. Recreá el stack "
              "(`down -v`) y re-seedeá, o revocá esas Connections para que el seeder las "
              "vuelva a crear.", file=sys.stderr)
        return 3
    # verify-only con faltantes o drift = exit 1 (útil para gatear un run).
    return 1 if report.state == "absent" else 0


def _read_pool(path: Optional[Path]) -> Optional[list]:
    """Lee un pool ya emitido, si existe.

    Un pool que EXISTE pero no se puede leer (JSON corrupto, contenido que no es una
    lista) es fatal en ``verify-only``: la key en claro no se recupera del backend, así
    que el único material del run es ese archivo — y el paso siguiente lo SOBRESCRIBIRÍA
    con ``sentinel_key: null`` en todas las entradas, destruyendo material irrecuperable y
    obligando a un ``down -v``. Se aborta con ``SeedError`` en vez de tocarlo. Que el
    archivo no exista todavía es otra cosa (primer run): eso devuelve ``None``."""
    if path is None or not Path(path).exists():
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise SeedError(
            f"el pool previo {path} existe pero no se puede leer ({e}). En verify-only ese "
            "archivo es la ÚNICA fuente de las sentinel_key (el backend no las devuelve dos "
            "veces) y el seeder lo reescribiría con material en null, destruyéndolo. "
            "Restaurá el pool o recreá el stack (`down -v`) y re-seedeá desde cero.") from e
    if not isinstance(data, list):
        raise SeedError(
            f"el pool previo {path} no es una lista de credenciales (es "
            f"{type(data).__name__}): no se sobrescribe un archivo que no se entiende — "
            "las sentinel_key que pudiera contener no son recuperables.")
    return data


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
