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

── lectura (nuevo en 017): NO minteable todavía ────────────────────────────────────────────
``lectura`` no está en ``ck_users_role`` ni en ``VALID_ROLES`` (Regla 2: paquete acoplado de
~5 ediciones que cierra T006). No se puede crear el usuario → sus filas de la matriz (vitrinas
R, chat 403) NO son testeables en vivo. Se documentan como divergencia conocida y se prueba la
no-minteabilidad en ``test_rol_lectura_todavia_no_es_minteable``.
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
from seat_gate_harness import build_app_client, mock_engine  # noqa: E402

from src.auth.matrix import Rol, roles_con_escritura, roles_con_lectura  # noqa: E402

require_postgres()

DB = "basa_test_role_matrix"
PASS = "matriz-rol-superficie-12345"  # respeta el mínimo del producto (validar_password)

# Roles canónicos que SÍ se pueden mintear hoy (ck_users_role). ``lectura`` queda afuera a
# propósito (ver docstring). En C2 super_admin ≡ tenant_admin: ambos expanden a `admin` vía el
# shim; se prueban por separado igual, para que el harness hable el idioma de la matriz.
MINTABLES = [Rol.SUPER_ADMIN, Rol.TENANT_ADMIN, Rol.COMPLIANCE_OFFICER, Rol.CLIENT]

# Traducción canónico→literal-legacy que hace `require_role` vía `effective_roles` (referencia;
# el harness NO la aplica a mano — la ejerce el código real al loguear cada rol):
#   super_admin/tenant_admin → admin ·  compliance_officer → compliance_officer
#   client → client (+ label sectorial si lo tuviera) ·  lectura → lectura (aún no minteable)


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
    # config_producto — guardians, policy, router_config, governance, budgets
    ("GET",    "/api/v1/guardians",                  "config_producto",       "read"),
    ("GET",    "/api/v1/governance/status",          "config_producto",       "read"),
    ("GET",    "/api/v1/budgets",                    "config_producto",       "read"),
    ("GET",    "/api/v1/security/policy",            "config_producto",       "read"),
    ("PUT",    "/api/v1/security/policy",            "config_producto",       "write"),
    # compliance_config — retention, consent admin
    ("GET",    "/api/v1/compliance/retention",       "compliance_config",     "read"),
    ("PUT",    "/api/v1/compliance/retention",       "compliance_config",     "write"),
    ("POST",   "/api/v1/compliance/consent",         "compliance_config",     "write"),
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
    """Mintéa un usuario del rol canónico por DB directa (bypass del gate de seats de POST
    /users: lo que probamos es el rol, no la licencia) con hash real, y devuelve su sesión.
    Mismo patrón que test_router_config_api.py."""
    from src.auth.passwords import hash_password
    from src.models.user import User

    # @basa.com.ar (no .test): UserResponse.email es EmailStr y rechaza el TLD reservado .test,
    # con lo que GET /users —que serializa a todos— explotaría al listar estos usuarios.
    nombre = f"matriz-{rol.value}{sufijo}-{uuid.uuid4().hex[:8]}"
    db = factory()
    try:
        db.add(User(
            username=nombre, email=f"{nombre}@basa.com.ar",
            password_hash=hash_password(PASS), role=rol.value,
            display_label=display_label, is_active=True,
        ))
        db.commit()
    finally:
        db.close()

    login = client.post("/api/v1/users/login", json={"username": nombre, "password": PASS})
    assert login.status_code == 200, f"login {rol.value}: {login.text}"
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


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


def _rechazo_por_rol(rol):
    return f"Acción no permitida para el rol '{rol.value}'"


def _cumple(resp, permitido, rol):
    if permitido:
        return resp.status_code not in (401, 403)
    return resp.status_code == 403 and _rechazo_por_rol(rol) in resp.text


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


# ── lectura: aún no minteable (Regla 2) → sus filas son divergencia no-testeable ────────────


def test_vocabulario_de_rol_todavia_no_incluye_lectura():
    from src.models.user import VALID_ROLES
    assert "lectura" not in VALID_ROLES, (
        "T006 agrega 'lectura' al vocabulario (VALID_ROLES + ck_users_role + normalize + shim + "
        "frontend, Regla 2). Hasta entonces sus filas de la matriz no se testean en vivo.")


def test_rol_lectura_todavia_no_es_minteable(harness):
    """El CHECK ck_users_role rechaza 'lectura': prueba en vivo por qué las vitrinas no lo gatean
    todavía (no existe el usuario). T006 lo habilita como paquete acoplado."""
    from sqlalchemy.exc import IntegrityError
    from src.auth.passwords import hash_password
    from src.models.user import User

    _, factory = harness
    db = factory()
    try:
        db.add(User(username=f"lectura-probe-{uuid.uuid4().hex[:8]}",
                    email="lectura-probe@basa.com.ar", password_hash=hash_password(PASS),
                    role="lectura", is_active=True))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


# ── Fugas del shim por label sectorial legacy (divergencia conocida; honestidad, no las cierro) ──
# El shim expande client+display_label a {client, <label>}; routers legacy que gatean por el
# label dejan pasar permiso que la matriz colapsó en client=PROPIO. Se afirma la fuga VIVA: el
# día que T006 la cierre, estos tests se dan vuelta y se mueven al RED de la matriz.


def test_label_developer_todavia_filtra_escritura_de_keys(sesiones_label, harness):
    """client(developer) escribe keys porque keys.py gatea (admin, developer). La matriz dice
    gestion_iam client=PROPIO (sin escritura de grupo): fuga que T006 cierra."""
    client, _ = harness
    resp = client.delete(f"/api/v1/keys/{uuid.uuid4()}", headers=sesiones_label["developer"])
    assert resp.status_code != 403, (
        f"Se esperaba la fuga viva (NO-403); si es 403, T006 ya la cerró → movela al RED de la "
        f"matriz y actualizá DIVERGENCIAS. Obtuvo {resp.status_code}.")


def test_label_clinician_todavia_resuelve_human_reviews(sesiones_label, harness):
    """client(clinician) entra a human-reviews porque compliance.py gatea (…, clinician). La
    matriz dice human_reviews client=NINGUNO: fuga que T006 cierra al sacar el literal legacy."""
    client, _ = harness
    resp = client.get("/api/v1/compliance/review/pending", headers=sesiones_label["clinician"])
    assert resp.status_code != 403, (
        f"Se esperaba la fuga viva (NO-403); si es 403, T006 ya la cerró → actualizá el harness. "
        f"Obtuvo {resp.status_code}.")
