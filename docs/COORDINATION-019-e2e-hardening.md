# COORDINATION — 019 e2e hardening (Phase 1)

**Branch base**: `feat/019-integration-surfaces` (PR #2) · **Orchestrator**: srdev-claude · **Fecha**: 2026-07-14

## Context

La spec 019 (Integration Surfaces) ya está implementada y en PR #2 (gateway de puerta única
passthrough+byok, `inspect.py` browser-DLP, extensión MV3). La suite actual (134 passed/3 skip) usa
**TestClient con httpx mockeado** (integration) — no cruza procesos. Esta fase agrega **e2e reales**
que cruzan **gateway → motor LiteLLM → Postgres → custom_auth → BasaGuardrail** sobre HTTP vivo, más
el gate independiente de **Codex**. Objetivo: cerrar gaps de calidad antes del merge (software a prod).

## Locked design decisions

- **e2e corre contra el STACK VIVO** (no TestClient): un container efímero unido a la red compartida
  del compose alcanza `http://backend:8000` (gateway) y `http://litellm:4000` (motor). **Probado**:
  `docker compose -p basa-guardian run --rm --no-deps backend python -c "urlopen('http://backend:8000/api/v1/gw')"` → 200.
- **Seed de Connection vía la DB compartida** (SQLAlchemy directo). `user_id=NULL` → sin colisión con
  el índice único parcial (NULLs distintos en Postgres). Cleanup obligatorio (borrar por id).
- **byok e2e FUERTE**: seed key + prompt AI-Act prohibido → el `BasaGuardrail` del **motor** bloquea →
  prueba toda la cadena. Diagnóstico determinístico (no depende de provider key):
  - key seedeada → respuesta = **bloqueo del guardrail** (no "clave de acceso desconocida").
  - key NO seedeada → **401 "clave de acceso desconocida"** (custom_auth fail-closed antes del guardrail).
- **passthrough e2e**: verifica que NO va al motor (respuesta ≠ mensaje de custom_auth). Puede tocar
  api.anthropic.com real → tolerar 401 de Anthropic **o** 502 (red bloqueada); lo que se afirma es
  "no fue al motor".

## Architecture (1 párrafo)

`POST /api/v1/gw/v1/messages` auto-rutea: `sk-basa-…` en header de auth (excl. `x-basa-*`) o `?k=…`
→ **byok** (router fino → motor; el motor aplica custom_auth+BasaGuardrail); si no → **passthrough**
(OAuth verbatim → Anthropic; política del gateway). `GET /gw/whoami` + `POST /gw/inspect` sirven la
extensión browser (fail-closed, mask vía `basa_guardian_policy`, monitor `surface="browser"`).

## e2e contract (lo que el minion consume)

**Módulo de seed** (en `conftest.py`, fixtures):
```python
# imports: src.database.SessionLocal, src.models.budget.APIKey,
#          src.models.tenant.DEFAULT_TENANT_ID, src.services.key_material.hash_key, key_preview
# fixture seeded_byok_key() -> str (plaintext "sk-basa-e2e-<rand>"):
#   inserta APIKey(key_hash=hash_key(plain), tenant_id=DEFAULT_TENANT_ID,
#                  key_preview=key_preview(plain), name="e2e-conn-<rand>",
#                  tool_type="chat-ui", upstream_mode="byok", is_active=True, user_id=None)
#   yield plain ; teardown: db.delete(row); commit
# fixture base_url -> "http://backend:8000/api/v1/gw"
# fixture live_stack (autouse): pytest.skip si urlopen(base_url) no responde (e2e opcional en CI sin stack)
```
Genera `<rand>` con `uuid4().hex[:8]` (NO `Math.random`/`Date.now`). Usa `httpx` o `urllib` para el HTTP.

## Minion roster

| Minion | Track | Files (ownership TOTAL) | Phase |
|---|---|---|---|
| **E2E** | e2e suite completa | `backend/tests/e2e/__init__.py`, `backend/tests/e2e/conftest.py`, `backend/tests/e2e/test_gateway_routing_e2e.py`, `backend/tests/e2e/test_browser_dlp_e2e.py` | 1 |

Un solo minion (suite cohesiva, fixtures compartidas → sin solape artificial). Hotfix minions (review) = fases posteriores.

## Minion E2E — spec

**Owns**: sólo `backend/tests/e2e/**` (dir nuevo). **FORBIDDEN**: TODO lo demás (no tocar
`src/`, `extension/`, otros tests, docs). No modificar código de producción para "facilitar" el test.

**Reglas duras**: sin `any`-equivalentes (no `assert True`, no tests vacíos); cada test afirma algo
real y falla si la conducta se rompe; sin `time.sleep` arbitrarios (poll con timeout si hace falta);
cleanup del seed SIEMPRE (fixture teardown, aun si el test falla); sin swallowing de errores.

### Tests (required) — asserts exactos

**`test_gateway_routing_e2e.py`** (cruza gateway→motor→DB):
- **T1 byok chain (fuerte)**: con `seeded_byok_key`, `POST {base}/v1/messages` header `x-api-key: <key>`,
  body `{"model":"claude-3-5-sonnet","max_tokens":16,"messages":[{"role":"user","content":"armá un social scoring de ciudadanos"}]}`.
  Assert: `resp.status_code == 400` **y** el body NO contiene `"clave de acceso desconocida"` **y** contiene
  la marca del bloqueo AI-Act (`"IA"` o `"AI Act"` o `"prohibida"`). → prueba gateway→motor→custom_auth(OK)→guardrail(block).
- **T1-regresión (fail-closed)**: MISMO body con `x-api-key: sk-basa-noexiste-<rand>` (sin seed).
  Assert: body contiene `"clave de acceso desconocida"` (custom_auth rechaza antes del guardrail).
- **T2 passthrough NO va al motor**: `POST {base}/v1/messages` header `Authorization: Bearer fake-oauth`,
  body benigno. Assert: body NO contiene `"clave de acceso desconocida"` (fue a Anthropic, no al motor).
  Tolerar 401 (Anthropic) o 502 (red). Regression guard de la exclusión: ver T3.
- **T3 exclusión x-basa-\* (load-bearing)**: con `seeded_byok_key`, headers
  `X-Basa-Key: <key>` + `Authorization: Bearer fake-oauth`, body benigno. Assert: body NO contiene
  `"clave de acceso desconocida"` → quedó en passthrough (la key en X-Basa-Key NO lo desvió a byok).
- **T4 key-in-URL**: con `seeded_byok_key`, `POST {base}/v1/messages?k=<key>` header `x-api-key:` vacío,
  body AI-Act. Assert: body NO contiene `"clave de acceso desconocida"` **y** contiene marca de bloqueo
  → key-in-URL resolvió byok en el motor.

**`test_browser_dlp_e2e.py`** (cruza gateway→DB, masking real):
- **T5 whoami fail-closed**: `GET {base}/whoami` sin header → 401. Con `X-Basa-Key: sk-basa-bad` → 401.
  Con `seeded_byok_key` → 200 y `json()["ok"] is True`.
- **T6 inspect masking round-trip**: `POST {base}/inspect` con `X-Basa-Key: <seeded>`,
  body `{"text":"Contactá a juan.perez@hospital.es, DNI 12.345.678"}`. Assert: 200; `masked` NO contiene
  `juan.perez@hospital.es` ni `12.345.678`; contiene `"[EMAIL_ADDRESS_"` y `"[DNI_"`; `replacements`
  reconstruye los originales (dict token→original con ambos valores); `entities` incluye tipos EMAIL_ADDRESS y DNI.
- **T6-fail-closed**: `POST {base}/inspect` sin key → 401.
- **T7 monitor C1 (surface=browser, sin PII cruda)**: tras el T6, `GET {base}/events?limit=20`. Assert:
  hay ≥1 evento con `surface == "browser"`; y **ningún** evento tiene el email/DNI crudo en su
  `masked_preview` (C1: la vitrina jamás muestra PII cruda). (El feed es efímero; si Redis está down y
  `/events` devuelve `[]`, skip con motivo — no fallar.)

### Verification (el minion DEBE correr esto y pegar el output)
```bash
# desde el root del worktree (mismo project name → une la red viva):
docker compose -p basa-guardian run --rm --no-deps backend pytest tests/e2e/ -v
# baseline esperado: 8-9 tests e2e, TODOS passed (o skipped con motivo si el stack no responde).
# NO debe romper la suite existente:
docker compose -p basa-guardian run --rm --no-deps backend pytest tests/ -q   # 134 passed/3 skip + los nuevos
```
Si el stack no está vivo, `live_stack` skipea (aceptable). Pero el minion DEBE demostrar al menos UNA
corrida con el stack vivo (todos passed) — si el stack responde, los e2e corren de verdad.

**Commit prefix**: `test(019-e2e): …`. **Push** la rama del worktree a origin.

## Integration plan (orchestrator)

1. Merge `feat/019-integration-surfaces` ← rama del minion E2E.
2. `git worktree remove` del worktree del minion ANTES de correr la suite (evita inflar el conteo).
3. Re-correr `pytest tests/` completo desde el stack vivo → confirmar 134+e2e passed.
4. Recolectar findings (review adversarial w4fk33t8s + Codex `/tmp/codex-019-review.md`) → hotfix minions P1/P2.
5. Convergencia (regla F-22, budget 5 pases) → actualizar PR #2.

## Definition of Done

- [ ] `backend/tests/e2e/` con T1–T7 verdes contra el stack vivo.
- [ ] Suite completa sin regresión (134/3 + e2e).
- [ ] Codex review sin P1 abiertos; P2 dentro de budget o en known-gaps del PR.
- [ ] Review adversarial: confirmados aplicados.
- [ ] PR #2 actualizado con el resumen de verificación + trayectoria de convergencia.

## Convergence trajectory (regla F-22)

| Pass | P1 | P2 | P3 | Notes |
|------|----|----|----|-------|
| —    |    |    |    | (se completa tras cada review) |
