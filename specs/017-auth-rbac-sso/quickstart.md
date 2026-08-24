# Quickstart — validar la 017 de punta a punta

Prerrequisitos: stack compose local; para §3 real, el tenant Entra de prueba de DevOps (hasta entonces, el IdP falso local de la suite).

## 1 · La matriz es la ley (SC-001/SC-002)

```bash
docker compose exec backend pytest tests/integration/test_role_matrix.py -v
```

Recorre los 15 routers + chat-JWT contra `contracts/matriz-roles.md`. A mano: login como auditor → `PUT /compliance/retention` = 403 con evento auditado; resolver una human review = 200. Login como `lectura` → dashboards OK, cualquier mutación o `POST /chat/completions` = 403. `grep -r PERMISSIONS backend/src` = 0.

## 2 · Actor propagado (FR-004)

Crear una key como admin → la fila de auditoría del alta trae actor (id + rol), no solo el hecho.

## 3 · SSO Entra (SC-003)

Con flag `sso` en la licencia de dev y la config del tenant sembrada por `PUT /api/v1/auth/sso/config`: `GET /api/v1/auth/sso/login` → flujo Entra → callback → sesión idéntica a la local (mismo formato de JWT, tenant claim presente). Con licencia SIN flag: superficie inaccesible, botón ausente, login local intacto. Con el IdP caído: login local sigue; el fallo SSO queda auditado.

El procedimiento completo contra el tenant Entra real, con captura por paso, está en **[RUNBOOK-e2e-sso.md](RUNBOOK-e2e-sso.md)** (instrumento: `frontend/e2e/017-sso-e2e.mjs`). Estado al 24-ago: los cuatro brazos automáticos en verde; el login humano completo, bloqueado por el client secret y el usuario piloto — **SC-003 medido a medias hasta que esa fase corra**.

## 4 · El mundo post-flip (SC-004)

```bash
docker compose exec backend pytest tests/integration/test_rls_post_flip.py -v
```

Fixture compartida con la 018 (bootstrap dropeada + NOSUPERUSER): aislamiento cross-tenant = 0 filas; jobs batch escriben vía contrato. La migración `016_rls_strict` NO corre por default — verificar que con `BASA_RLS_STRICT` sin setear el arranque es idéntico a hoy.

## 5 · Hardening (SC-005)

5 logins fallidos → lockout uniforme + evento; key con `expires_at` vencido → rechazada en byok, Playground y /gw (test por plano); `SELECT engine_key_token FROM api_keys` → cero material `sk-basa` en claro.

## 6 · Cero regresión Cámara (SC-007)

Suite completa existente verde sin migración de datos de usuarios; nota de release con el cambio de matriz.
