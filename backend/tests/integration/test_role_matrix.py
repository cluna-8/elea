"""Harness FR-005: la matriz canónica rol×superficie es la LEY del backend (spec 017, T004).

Recorre los grupos de superficie de ``src/auth/matrix.py`` (users/keys/groups, config de
producto, compliance, human-reviews, vitrinas, costs, chat) contra endpoints reales gateados
por ``require_role`` y afirma, para cada (endpoint × rol canónico):

- **403-por-rol** (con el texto propio de ``rbac.require_role``) si la matriz NIEGA, o
- **NO-403** (2xx/404/422/409 — cualquier cosa menos 401/403) si la matriz PERMITE.

La verdad esperada NO se re-declara: sale de ``matrix.MATRIZ`` vía
``roles_con_escritura``/``roles_con_lectura``. El harness autentica MINTEANDO un usuario por
rol canónico y logueándose, así ejercita el shim real (``rbac.effective_roles``) que traduce
canónico→literal-legacy — es comportamiento de punta a punta, no introspección de closures.

── RED-first (T004, media parte del entregable) ────────────────────────────────────────────
Corrido HOY (pre-T006) este archivo FALLA en los endpoints donde el código todavía diverge de
la matriz nueva. **Eso es esperado y es el entregable**: el rojo ES el diff documentado, no un
test roto. Las divergencias vivas están enumeradas una por una en
``DIVERGENCIAS_CONOCIDAS_PRE_T006`` y ``test_las_divergencias_rojas_son_exactamente_las_documentadas``
prueba que el rojo actual == esa lista (ni una de más = regresión; ni una de menos = ya la cerró
T006). Las cierra Jeff en T006 (auth caliente): mover las 8 escrituras del compliance_officer a
tenant_admin (Regla 1 del contrato) y abrirle la lectura de IAM/config.

Las divergencias vivas son TODAS de ``compliance_officer`` y de dos clases:
  (A) LECTURA que la matriz le da (R en gestion_iam/config_producto) y el código todavía niega
      (routers admin-only) → hoy 403, la matriz espera NO-403.
  (B) ESCRITURA que la matriz le saca (pierde W en compliance/costs/policy) y el código todavía
      permite → hoy NO-403, la matriz espera 403.

⚠ Nota de superficie para T006 (heads-up, no lo resuelvo acá): la clase (A) implica que el
   auditor pasa a LEER /users, /keys, /guardians, /governance, /budgets. Eso contradice el
   ``NO_PUEDE`` de ``test_rol_auditor.py`` y el requerimiento del piloto ("sin entrar a llaves
   ni administración"). El contrato (Regla 5) ya prevé que ese test ancla se actualiza en el
   MISMO PR del recorte; se deja anotado para que la decisión de darle esa lectura sea explícita.

── lectura (nuevo en 017): minteable y en la matriz-ley (T009 + T010) ───────────────────────
``lectura`` ya entró al vocabulario (``VALID_ROLES`` + ``ck_users_role`` vía migración 016,
T009) y está en ``MINTABLES``: sus filas de la matriz se ejercen EN VIVO como cualquier otro
rol. T009 cableó sus vitrinas (``vitrinas_lectura`` = R) y T010 cerró el ``chat_playground``
(=NINGUNO → 403) en el camino JWT de ``chat_completions`` — recién con ese gate presente
``lectura`` puede sumarse a ``MINTABLES`` sin volver roja la fila de chat.
"""
import sys
import uuid
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import (  # noqa: E402
    ROLE_PASS, build_app_client, headers_for_role, mock_engine, rechazo_por_rol,
)

from src.auth.matrix import Rol, roles_con_escritura, roles_con_lectura  # noqa: E402

require_postgres()

DB = "sentinel_test_role_matrix"

# Roles canónicos minteables (ck_users_role). `lectura` entra con T010: su gate de chat ya
# existe, así que la fila `chat_playground`=NINGUNO (403) se asserta en vivo sin volver roja la
# matriz. En C2 super_admin ≡ tenant_admin: ambos expanden a `admin` vía el shim; se prueban por
# separado igual, para que el harness hable el idioma de la matriz.
MINTABLES = [Rol.SUPER_ADMIN, Rol.TENANT_ADMIN, Rol.COMPLIANCE_OFFICER, Rol.CLIENT, Rol.LECTURA]

# Traducción canónico→literal-legacy que hace `require_role` vía `effective_roles` (referencia;
# el harness NO la aplica a mano — la ejerce el código real al loguear cada rol):
#   super_admin/tenant_admin → admin ·  compliance_officer → compliance_officer
#   client → client (+ label sectorial si lo tuviera) ·  lectura → lectura (vitrinas=R, chat=403)


# ── Catálogo endpoint→grupo (comentarios de MATRIZ + contrato + call-sites de require_role) ──
# Cada fila: (método, template, grupo, acción). {ID}=uuid inexistente (el gate corre en el
# APIRouter/dependency, ANTES del handler, así que un allow cae a 404 sin necesitar la fila);
# {TOKEN}=token de review inexistente. Los writes van con cuerpo {} (o el gate niega en 403, o
# pasa y pydantic corta en 422): ninguna mutación real, orden-independiente.
CATALOG = [
    # gestion_iam — users, keys, groups
    ("GET",    "/api/v1/users",                      "gestion_iam",           "read"),
    ("GET",    "/api/v1/keys",                       "gestion_iam",           "read"),
    ("PUT",    "/api/v1/users/{ID}",                 "gestion_iam",           "write"),
    ("DELETE", "/api/v1/keys/{ID}",                  "gestion_iam",           "write"),
    ("GET",    "/api/v1/groups",                      "gestion_iam",           "read"),   # #247: CO lee grupos
    ("PUT",    "/api/v1/groups/{ID}/compliance",      "gestion_iam",           "write"),  # #247: write admin-only
    # config_producto — guardians, policy, router_config, governance, budgets
    ("GET",    "/api/v1/guardians",                  "config_producto",       "read"),
    ("GET",    "/api/v1/governance/status",          "config_producto",       "read"),
    ("GET",    "/api/v1/budgets",                    "config_producto",       "read"),
    ("GET",    "/api/v1/security/policy",            "config_producto",       "read"),
    ("PUT",    "/api/v1/security/policy",            "config_producto",       "write"),
    ("GET",    "/api/v1/chat/router-config",         "config_producto",       "read"),   # #247: CO lee auto-router
    ("PUT",    "/api/v1/chat/router-config",         "config_producto",       "write"),  # #247: write admin-only, developer dropeado
    ("GET",    "/api/v1/chat/models/status",         "config_producto",       "read"),   # spec 033 T004
    ("POST",   "/api/v1/chat/models/apply",          "config_producto",       "write"),  # spec 033 T005, developer dropeado
    # compliance_config — retention, consent admin
    ("GET",    "/api/v1/compliance/retention",       "compliance_config",     "read"),
    ("PUT",    "/api/v1/compliance/retention",       "compliance_config",     "write"),
    ("POST",   "/api/v1/compliance/consent",         "compliance_config",     "write"),
    # Políticas de contenido (spec 036 US2) — misma superficie que la pestaña "Contenido" de
    # Políticas de Cumplimiento: el CO las LEE, sólo admin las muta.
    ("GET",    "/api/v1/content-policies",           "compliance_config",     "read"),
    ("POST",   "/api/v1/content-policies",           "compliance_config",     "write"),
    ("PUT",    "/api/v1/content-policies/{ID}",      "compliance_config",     "write"),
    ("DELETE", "/api/v1/content-policies/{ID}",      "compliance_config",     "write"),
    # artefactos_compliance — projects, DPAs, DSRs
    ("GET",    "/api/v1/compliance/projects",        "artefactos_compliance", "read"),
    ("POST",   "/api/v1/compliance/projects",        "artefactos_compliance", "write"),
    ("DELETE", "/api/v1/compliance/projects/{ID}",   "artefactos_compliance", "write"),
    ("POST",   "/api/v1/compliance/dpas",            "artefactos_compliance", "write"),
    ("POST",   "/api/v1/compliance/dsr",             "artefactos_compliance", "write"),
    # human_reviews_resolver — la única escritura nombrada del auditor
    ("GET",    "/api/v1/compliance/review/pending",  "human_reviews_resolver", "read"),
    ("POST",   "/api/v1/compliance/review/{TOKEN}",  "human_reviews_resolver", "write"),
    # vitrinas_lectura — audit, reports, costs-read
    ("GET",    "/api/v1/audit-logs",                 "vitrinas_lectura",      "read"),
    ("GET",    "/api/v1/reports/rat",                "vitrinas_lectura",      "read"),
    ("GET",    "/api/v1/costs/summary",              "vitrinas_lectura",      "read"),
    # costs_config — compression global, budgets write
    ("PUT",    "/api/v1/costs/config",               "costs_config",          "write"),
    ("POST",   "/api/v1/budgets",                    "costs_config",          "write"),
    # chat_playground — POST /chat/completions (camino JWT; FR-003 aún NO gatea rol → ver nota)
    ("POST",   "/api/v1/chat/completions",           "chat_playground",       "write"),
    # config_producto — SSO: `GET/PUT /api/v1/auth/sso/config` NO entran a este catálogo, y no
    # es un olvido. Ese router va detrás del gate de LICENCIA (`require_sso_enabled`) además del
    # de rol, y la licencia de la suite trae `["monitor"]` sin `sso`: acá todos los roles darían
    # 403 de licencia, que este harness no distingue del 403-por-rol (`_rechazo_por_rol` mira el
    # texto). Meterlos daría rojo para los cinco roles y por el motivo equivocado.
    # Su reparto —admin RW · compliance_officer R · client/lectura ninguno, o sea
    # `config_producto`— se ejerce en `test_sso_config_api.py`, en estos tres tests NOMBRADOS
    # (para que el próximo pueda verificar esta nota sin creerme):
    #   test_el_auditor_LEE_la_config · test_el_auditor_NO_escribe_la_config ·
    #   test_los_roles_sin_config_producto_ni_leen_ni_escriben[client|lectura]
    # Allá el 403-de-rol SÍ se distingue del de licencia: montan la licencia CON `sso`, así que
    # cada caso afirma el texto de `require_role` y la AUSENCIA de `sso_no_licenciado`.
    # Si algún día la licencia de la suite trae `sso`, estas dos filas entran acá.
]


# ── Divergencias conocidas pre-T006 (todas compliance_officer). Clave = (método, template,
#    rol.value). El valor apunta al recorte de T006 (Regla 1 del contrato). ─────────────────
_R = "compliance_officer"
# Registro histórico del diff RED-first (T004): las 13 divergencias que documentó el harness
# ANTES de T006. Se conserva como memoria; ya NO es la lista activa (ver abajo).
_DIVERGENCIAS_HISTORICAS_PRE_T006 = {
    # (A) lecturas que la matriz le da (R) y el código todavía niega (routers admin-only):
    ("GET", "/api/v1/users", _R):
        "gestion_iam R: la matriz da lectura al compliance_officer; users.py gatea admin-only "
        "→ 403. T006 le abre la lectura de IAM. (heads-up: flipea el NO_PUEDE de test_rol_auditor)",
    ("GET", "/api/v1/keys", _R):
        "gestion_iam R: keys.py gatea (admin, developer) → compliance 403. T006 le abre lectura.",
    ("GET", "/api/v1/guardians", _R):
        "config_producto R: guardians.py admin-only → compliance 403. T006 le abre lectura.",
    ("GET", "/api/v1/governance/status", _R):
        "config_producto R: governance.py admin-only → compliance 403. T006 le abre lectura.",
    ("GET", "/api/v1/budgets", _R):
        "config_producto R: budgets.py admin-only → compliance 403. T006 le abre lectura.",
    # (B) escrituras que la matriz le saca (pierde W) y el código todavía permite:
    ("PUT", "/api/v1/security/policy", _R):
        "config_producto W: la matriz le saca W; policy.py (admin, compliance_officer) todavía "
        "lo deja escribir → NO-403. Regla 1 (policy.py:76-138) → mueve a tenant_admin en T006.",
    ("PUT", "/api/v1/compliance/retention", _R):
        "compliance_config W: la matriz pasa a R; retention todavía admite compliance → NO-403. "
        "Regla 1 (compliance.py:319).",
    ("POST", "/api/v1/compliance/consent", _R):
        "compliance_config W: consent.py (admin, compliance_officer) todavía admite → NO-403. "
        "Regla 1 (consent.py:91,125).",
    ("POST", "/api/v1/compliance/projects", _R):
        "artefactos_compliance W: la matriz pasa a R; projects todavía admite compliance → "
        "NO-403. Regla 1 (compliance.py:133-271).",
    ("DELETE", "/api/v1/compliance/projects/{ID}", _R):
        "artefactos_compliance W: DELETE de projects todavía admite compliance → NO-403 (404). "
        "Regla 1 (compliance.py:133-271).",
    ("POST", "/api/v1/compliance/dpas", _R):
        "artefactos_compliance W: DPAs todavía admite compliance → NO-403. Regla 1.",
    ("POST", "/api/v1/compliance/dsr", _R):
        "artefactos_compliance W: DSRs todavía admite compliance → NO-403. Regla 1.",
    ("PUT", "/api/v1/costs/config", _R):
        "costs_config W: la matriz pasa a R; el interruptor global de compresión todavía admite "
        "compliance → NO-403. Regla 1 (costs.py:299,338).",
}

# T006 cerró las 13 divergencias de arriba: 324df19 (writes compliance.py → admin),
# e462ff9 (split router-level policy/consent/costs), 4664e3a (lecturas IAM/config para el
# auditor). El harness es ahora el guardarraíl VERDE: la lista activa está VACÍA, así que
# cualquier rojo vivo en `test_las_divergencias_...` = regresión real, no diff documentado.
DIVERGENCIAS_CONOCIDAS_PRE_T006 = {}


# ── Helpers ─────────────────────────────────────────────────────────────────────────────────


def _headers_for_role(client, factory, rol, *, display_label=None, sufijo=""):
    """Mintea la sesión del rol canónico. El minteo vive en `seat_gate_harness` desde que lo
    comparte `test_sso_config_api.py`; acá queda el `prefijo` histórico de este harness."""
    return headers_for_role(client, factory, rol, display_label=display_label,
                            sufijo=sufijo, prefijo="matriz")


def _build_path(template):
    return template.replace("{ID}", str(uuid.uuid4())).replace("{TOKEN}", uuid.uuid4().hex)


def _hit(client, method, path, headers):
    kwargs = {"json": {}} if method in ("POST", "PUT") else {}
    return getattr(client, method.lower())(path, headers=headers, **kwargs)


def _expected_allow(group, action, rol):
    """La matriz es la ley: permitir = el rol está en el conjunto de escritura/lectura del grupo.
    (PROPIO/NINGUNO quedan afuera de ambos conjuntos por diseño de matrix.py.)"""
    permitidos = roles_con_escritura(group) if action == "write" else roles_con_lectura(group)
    return rol in permitidos


def _cumple(resp, permitido, rol):
    if permitido:
        return resp.status_code not in (401, 403)
    return resp.status_code == 403 and rechazo_por_rol(rol) in resp.text


# ── Fixtures ─────────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def harness():
    client, factory, cleanup = build_app_client(DB)
    yield client, factory
    cleanup()


@pytest.fixture(autouse=True)
def motor(monkeypatch):
    """Motor mockeado por si algún handler alcanzado lo toca; el gate corre antes igual."""
    return mock_engine(monkeypatch)


@pytest.fixture(autouse=True)
def _content_policies_mockeadas(monkeypatch):
    """GET y DELETE de content-policies pegan la red real — NO sólo GET (corrección de
    Jeff, 26-ago-2026, medida con canario que hace explotar `_get`): `mock_engine`
    (arriba) sólo patchea `generate_key`/`create_user`/`delete_key`, nada de
    `list_content_policies`/`create_content_policy`/`update_content_policy`/
    `delete_content_policy`. GET nunca tiene body que Pydantic pueda rechazar, así que
    para los roles con lectura SIEMPRE llega al handler y llama `list_content_policies`.
    DELETE tampoco tiene body/schema (el ENDPOINT `delete_content_policy(policy_id: str)`
    de este router — no el del cliente en `ai_engine_client`, que recibe `guardrail_id` —
    no tiene `payload`) — para los roles con escritura SIEMPRE llega también, con o sin
    el guard de abajo. Antes del fix del bloqueante #315, PUT se sumaba (el guard "al
    menos una regla" no corría con el body vacío) — canario con el bug presente: 7/28
    celdas tocan `_get` (GET×3 + PUT×2 + DELETE×2, por los roles que tienen ese acceso).
    Con el fix, PUT vuelve a cortar en 422 antes del handler: quedan 5/28 celdas del
    CATALOG (GET×3 + DELETE×2) — pero **6 tests en total** (Jeff, medido con canario,
    26-ago-2026): `test_las_divergencias_rojas_son_exactamente_las_documentadas`
    recorre el mismo CATALOG × MINTABLES A MANO (loop propio, no vía
    `@pytest.mark.parametrize`) para comparar las divergencias vivas contra
    `DIVERGENCIAS_CONOCIDAS_PRE_T006`, así que también pega GET/DELETE de
    content-policies sin figurar en el conteo de celdas parametrizadas. Sin este
    aislamiento cada una de esas celdas/tests dispara un `httpx` real
    contra `http://litellm:4000/v2/guardrails/list` o `/guardrails/{id}`
    (`_TIMEOUT = 10.0`) — el gate de rol cumple igual (502 no es 401/403), pero es red
    viva que este harness no necesita para probar rol; la lógica del glue la cubre
    `test_content_policy_service.py` mockeando `_post`/`_get`/`_delete_by_id`. Local a
    este archivo (no en `seat_gate_harness.mock_engine`, que comparten otros módulos que
    no tocan content-policies), mismo patrón que `_sentinel_aislado` de abajo.

    ⚠ Si algún día se te ocurre achicar este fixture a "sólo mockeo lo que el bug de
    turno necesita": los 4 `setattr` son necesarios TODOS — sacar uno reintroduce una
    llamada viva que el gate de rol no va a detectar (pasa igual con 502)."""
    from src.services import ai_engine_client

    async def _list(*a, **kw):
        return []

    async def _crear(*a, **kw):
        return {"policy_id": "mock", "guardrail_id": "mock-id", "name": "sentinel-policy-mock",
                "description": "", "blocked_words": [], "categories": [], "active": False}

    async def _actualizar(*a, **kw):
        return {"policy_id": "mock", "guardrail_id": "mock-id", "name": "sentinel-policy-mock",
                "description": "", "blocked_words": [], "categories": [], "active": False}

    async def _borrar(*a, **kw):
        return None

    monkeypatch.setattr(ai_engine_client, "list_content_policies", _list)
    monkeypatch.setattr(ai_engine_client, "create_content_policy", _crear)
    monkeypatch.setattr(ai_engine_client, "update_content_policy", _actualizar)
    monkeypatch.setattr(ai_engine_client, "delete_content_policy", _borrar)


@pytest.fixture(autouse=True)
def _sentinel_aislado(monkeypatch, tmp_path):
    """`POST /chat/models/apply` (spec 033, T005) ESCRIBE de verdad cuando el rol lo permite:
    a diferencia del resto de los writes de `CATALOG`, su body `{}` es válido (sin campos
    obligatorios), así que sin este aislamiento cada corrida de esta suite tocaría el
    `litellm/apply.trigger` real del checkout (mismo motivo que `config_temporal` en
    `test_router_config_api.py` — la suite no escribe en el repo)."""
    from src.api import chat
    monkeypatch.setattr(chat, "_get_engine_sentinel_path",
                        lambda: str(tmp_path / "apply.trigger"))


@pytest.fixture(scope="module")
def sesiones(harness):
    """Una sesión JWT por rol canónico minteable."""
    client, factory = harness
    return {rol: _headers_for_role(client, factory, rol) for rol in MINTABLES}


@pytest.fixture(scope="module")
def sesiones_label(harness):
    """Clients con label sectorial legacy: el shim los expande y filtra permiso extra."""
    client, factory = harness
    return {
        "developer": _headers_for_role(client, factory, Rol.CLIENT,
                                       display_label="developer", sufijo="-dev"),
        "clinician": _headers_for_role(client, factory, Rol.CLIENT,
                                       display_label="clinician", sufijo="-clin"),
    }


# ── El harness es la ley: cada (endpoint × rol) cumple la matriz o es rojo documentado ──────


@pytest.mark.parametrize("method,template,group,action", CATALOG,
                         ids=[f"{m}:{t}" for m, t, _g, _a in CATALOG])
@pytest.mark.parametrize("rol", MINTABLES, ids=lambda r: r.value)
def test_la_matriz_es_ley(sesiones, harness, rol, method, template, group, action):
    client, _ = harness
    resp = _hit(client, method, _build_path(template), sesiones[rol])
    permitido = _expected_allow(group, action, rol)
    key = (method, template, rol.value)

    if _cumple(resp, permitido, rol):
        return  # cumple la matriz

    if key in DIVERGENCIAS_CONOCIDAS_PRE_T006:
        pytest.fail(
            f"DIVERGENCIA ESPERADA pre-T006 (rojo = diff documentado, se cierra en T006):\n"
            f"  {method} {template}  rol={rol.value}  grupo={group}/{action}\n"
            f"  matriz espera {'NO-403' if permitido else '403-por-rol'}, obtuvo {resp.status_code}\n"
            f"  → {DIVERGENCIAS_CONOCIDAS_PRE_T006[key]}")
    pytest.fail(
        f"DIVERGENCIA INESPERADA (NO está en DIVERGENCIAS_CONOCIDAS_PRE_T006 — revisá el mapeo "
        f"endpoint→grupo o es una regresión real):\n"
        f"  {method} {template}  rol={rol.value}  grupo={group}/{action}\n"
        f"  matriz espera {'NO-403' if permitido else '403-por-rol'}, obtuvo {resp.status_code}: "
        f"{resp.text[:200]}")


def test_las_divergencias_rojas_son_exactamente_las_documentadas(sesiones, harness):
    """El rojo actual == la lista documentada. Falla si aparece una divergencia no documentada
    (bug de mapeo o regresión) o si una documentada dejó de serlo (¿la cerró T006? → borrala)."""
    client, _ = harness
    vivas = {}
    for method, template, group, action in CATALOG:
        for rol in MINTABLES:
            resp = _hit(client, method, _build_path(template), sesiones[rol])
            permitido = _expected_allow(group, action, rol)
            if not _cumple(resp, permitido, rol):
                vivas[(method, template, rol.value)] = resp.status_code

    documentadas = set(DIVERGENCIAS_CONOCIDAS_PRE_T006)
    assert set(vivas) == documentadas, (
        "El rojo vivo no coincide con DIVERGENCIAS_CONOCIDAS_PRE_T006:\n"
        f"  inesperadas (vivas, sin documentar): {sorted(set(vivas) - documentadas)}\n"
        f"  documentadas que ya NO divergen (¿cerró T006?): {sorted(documentadas - set(vivas))}\n"
        f"  detalle de las vivas (status observado): {vivas}")


# ── lectura: ya minteable (T009, Regla 2) → vocabulario y no-mint flipeados ──────────────────
# T009 (spec 017 FR-003) cerró el paquete acoplado: `lectura` entra al vocabulario canónico
# (VALID_ROLES + ck_users_role vía migración 016 + shim de vitrinas + frontend). Sus filas de
# `vitrinas_lectura` (R) se ejercen en `test_rol_lectura_lee_vitrinas_y_nada_mas`; el 403 del
# chat (chat_playground = NINGUNO) lo asserta T010 cuando suma el gate JWT y mete LECTURA en
# MINTABLES. Estos dos tests eran los guards RED-first previos a T009 (ahora flipeados).


def test_vocabulario_de_rol_incluye_lectura():
    from src.models.user import VALID_ROLES
    assert "lectura" in VALID_ROLES, (
        "T009 agrega 'lectura' al vocabulario canónico (VALID_ROLES + ck_users_role + shim + "
        "frontend, Regla 2).")


def test_rol_lectura_es_minteable(harness):
    """El CHECK ck_users_role (migración 016) ya admite 'lectura': el usuario se crea sin
    IntegrityError. Contracara viva del RED-first previo a T009."""
    from src.auth.passwords import hash_password
    from src.models.user import User

    _, factory = harness
    db = factory()
    try:
        fila = User(username=f"lectura-probe-{uuid.uuid4().hex[:8]}",
                    email="lectura-probe@sentinel.com.ar", password_hash=hash_password(ROLE_PASS),
                    role="lectura", is_active=True)
        db.add(fila)
        db.commit()  # sin IntegrityError: el CHECK ya lo admite
        db.refresh(fila)
        assert fila.role == "lectura"
    finally:
        db.rollback()
        db.close()


# Las superficies del grupo `vitrinas_lectura` que `lectura` SÍ lee (R) — las tres vitrinas que
# el nav de T012 (#244) le muestra (costos/auditoría/conexiones) + el RAT exportable (Art. 30).
_LECTURA_VITRINAS = [
    ("GET", "/api/v1/audit-logs"),     # rastro de auditoría (nav: Logs de Auditoría)
    ("GET", "/api/v1/gw/events"),      # monitor en vivo (nav: Conexiones en vivo) — ring compartido
    ("GET", "/api/v1/costs/summary"),  # resumen de costes (nav: Costos)
    ("GET", "/api/v1/reports/rat"),    # RAT (GDPR Art. 30, metadata organizativa — no PII)
]
# "y nada más": una muestra por grupo NINGUNO para `lectura` — gestion_iam, config_producto,
# artefactos, costs_config (write), los costs NO-vitrina que T009 re-cierra endpoint-level, y el
# chat (`chat_playground`=NINGUNO → 403 vía el gate JWT de T010). Los que están en el CATALOG los
# reafirma además `test_la_matriz_es_ley` ahora que `lectura` entró a MINTABLES; acá quedan
# explícitos —incluidas las rutas no-CATALOG (gw/events, costs re-cerrados)— para contar la
# historia completa del rol en un solo test.
_LECTURA_DENEGADOS = [
    ("GET",  "/api/v1/users"),                 # gestion_iam read
    ("GET",  "/api/v1/guardians"),             # config_producto read
    ("POST", "/api/v1/compliance/projects"),   # artefactos write
    ("PUT",  "/api/v1/costs/config"),          # costs_config write (admin-only)
    ("GET",  "/api/v1/costs/config"),          # costs config read (re-cerrado admin+compliance)
    ("POST", "/api/v1/costs/calculator"),      # costs calculator (re-cerrado admin+compliance)
    ("GET",  "/api/v1/costs/groups/{ID}/compression"),  # compresión por grupo (3ª ruta re-cerrada)
    ("POST", "/api/v1/chat/completions"),      # chat_playground=NINGUNO → 403 (gate JWT de T010)
]


def test_rol_lectura_lee_vitrinas_y_nada_mas(harness):
    """`lectura` (ya minteable, T009) LEE las vitrinas del grupo `vitrinas_lectura` y NADA MÁS:
    403-por-rol en gestion_iam / config_producto / artefactos / costs_config y en los costs
    no-vitrina re-cerrados. Ejerce el shim real (`effective_roles`) minteando y logueando el rol.
    El 403 del chat (chat_playground=NINGUNO) lo asserta T010 con el gate JWT; acá no se toca
    porque ese gate aún no existe (sería falso rojo). Contracara viva del RED-first previo a T009."""
    client, factory = harness
    headers = _headers_for_role(client, factory, Rol.LECTURA)

    for method, path in _LECTURA_VITRINAS:
        resp = _hit(client, method, _build_path(path), headers)
        assert _cumple(resp, True, Rol.LECTURA), (
            f"lectura debe LEER la vitrina {method} {path} (vitrinas_lectura=R); "
            f"obtuvo {resp.status_code}: {resp.text[:160]}")

    for method, path in _LECTURA_DENEGADOS:
        resp = _hit(client, method, _build_path(path), headers)
        assert _cumple(resp, False, Rol.LECTURA), (
            f"lectura NO debe acceder {method} {path} (matriz=NINGUNO); "
            f"esperaba 403-por-rol, obtuvo {resp.status_code}: {resp.text[:160]}")


def test_put_content_policy_sin_reglas_da_422_no_borra_en_silencio(sesiones, harness):
    """Bloqueante #315 (Jeff, 26-ago-2026): `_al_menos_una_regla` era un
    `@field_validator("categories")`, y en Pydantic 2 un field validator NO corre cuando el
    campo viene AUSENTE y toma su default — sólo disparaba con `categories: []` EXPLÍCITO, la
    forma que ningún cliente manda. Como `update_content_policy` es borra+crea (hallazgo del
    11-ago), un `PUT {"description": "..."}` —la llamada más normal del mundo— pasaba el
    guard y borraba las reglas de la política EN SILENCIO. Fix: `@model_validator(mode="after")`,
    que sí ve el default.

    Testigo: corrido contra el CONTROL (revert del fix en content_policies.py, mismo test) da
    ROJO acá — 200/404, no 422. Un test que pasa en los dos árboles no prueba nada."""
    client, _ = harness
    resp = client.put(
        "/api/v1/content-policies/una-politica-cualquiera",
        json={"description": "actualización de texto, sin tocar reglas"},
        headers=sesiones[Rol.SUPER_ADMIN],
    )
    assert resp.status_code == 422, (
        f"PUT sin blocked_words ni categories debe cortar en 422 ANTES de tocar el motor "
        f"(así nunca llega a borrar+crear con la lista de reglas vacía); obtuvo "
        f"{resp.status_code}: {resp.text[:200]}")


# ── Fold de las variantes client+display_label a la matriz-ley (#247, cierra el punto ciego) ──
# El shim expande client+label a {client, <label>}; el harness ahora chequea esas variantes
# CONTRA LA MATRIZ del rol CANÓNICO (client: gestion_iam=PROPIO, human_reviews=NINGUNO), no solo
# como tests de honestidad sueltos. Un router legacy que todavía gatee por el label sectorial
# (keys/developer, human_reviews/clinician) ROJEA acá — que un over-permit de label futuro rojee
# en la matriz-ley, y no quede en un test aparte, es la feature (cierra el punto ciego de #247).
_LABELS_LEGACY = ["developer", "clinician"]


@pytest.mark.parametrize("method,template,group,action", CATALOG,
                         ids=[f"{m}:{t}" for m, t, _g, _a in CATALOG])
@pytest.mark.parametrize("label", _LABELS_LEGACY)
def test_la_matriz_es_ley_para_labels_legacy(sesiones_label, harness, label, method, template, group, action):
    """La variante client+display_label cumple la matriz del rol CANÓNICO (client): el label
    sectorial es display, NO da acceso de grupo. Rojo = un router legacy todavía gatea por el label."""
    client, _ = harness
    resp = _hit(client, method, _build_path(template), sesiones_label[label])
    permitido = _expected_allow(group, action, Rol.CLIENT)
    assert _cumple(resp, permitido, Rol.CLIENT), (
        f"Variante client({label}): {method} {template} grupo={group}/{action} — la matriz (client) "
        f"espera {'NO-403' if permitido else '403-por-rol'}, obtuvo {resp.status_code}. Over-permit de "
        f"label legacy → #247 lo cierra dropeando el literal del gate.")
