# Quickstart — 021 Licensing & Seat Enforcement

Ciclo completo en local: emitir token dev → inyectar (como lo hará la 020) →
arrancar sin egress → ver health → true-up. Todo offline (Principio VII).

## 1. Emitir un token de prueba (offline)

```bash
cd backend
python scripts/issue_dev_license.py
# → scripts/license_out/dev-demo.lic + basa_public_keys.pem (kid basa-dev-*,
#   payload fijo: tenant default, max_seats=50, sin expiry práctica)
```

La privada dev queda en `scripts/license_out/` (gitignored). En prod las licencias
las firma Basa (KMS); la caja solo tiene la pública embebida.

## 2. Inyectar el token (integración con la 020 — T038)

La 020 inyecta config, no builds: el MISMO binario/imagen opera para cualquier
cliente cambiando SOLO estas env (SC-010):

```yaml
# compose del deployment (020) — bloque de licencia
environment:
  BASA_LICENSE_TOKEN_FILE: /app/config/licenses/dev-demo.lic   # o BASA_LICENSE_TOKEN inline
  BASA_LICENSE_PUBLIC_KEYS_FILE: /app/config/licenses/basa_public_keys.pem  # default: embebido
  BASA_DEPLOYMENT_TENANT_ID: 00000000-0000-0000-0000-000000000001
  BASA_ALLOW_DEV_LICENSE: "true"      # SOLO dev/demo: sin esto, un kid basa-dev-* es invalid
  BASA_LICENSE_RECONCILE_INTERVAL_SECONDS: "300"   # <=0 desactiva el job
  BASA_LICENSE_HARD_BLOCK: "false"    # true = expired/over_seat cortan TODO /gw
  BASA_DEPLOYMENT_KEY_FILE: /app/config/licenses/deployment_key.pem  # volumen persistente
volumes:
  - ./licenses:/app/config/licenses    # token + deployment key (privada JAMÁS en el repo)
```

⚠️ **Fail-closed**: sin token válido el backend ARRANCA igual pero bloquea la
creación de seats (403). El deploy de guardian.basa-dev.com necesita este bloque.

## 3. Arrancar y verificar (sin egress)

La verificación Ed25519 y la reconciliación son 100% locales — no hay phone-home
que romper. Smoke:

```bash
docker compose up -d backend
curl -s localhost:8081/api/v1/health/license          # {"status":"active","clock_rollback_suspected":false}
# autenticado (JWT admin) agrega seats_used/max_seats/expiry/reconcile
```

E2E de la suite (Postgres real, migraciones a head, motor mockeado):
`docker compose run --rm --no-deps backend pytest tests/integration/test_offline_verify.py tests/integration/test_lifecycle.py tests/integration/test_reconcile.py -q`

## 4. True-up (renovación)

```bash
docker compose exec backend python scripts/generate_trueup.py > trueup-$(date +%F).json
```

El operador envía el JSON a Basa fuera de banda. En el onboarding Basa registró
la **pública** de la deployment key y la **génesis** (`license_id` inicial):
`trueup_export.verify_export(doc, public_pem, expected_genesis_license_id=…,
previous=export_anterior)` valida firma + cadena + continuidad (anti-truncado).

**Génesis efectiva**: la reporta `/api/v1/health/license` (tier admin, campo
`chain`). Si el PRIMER arranque fue sin `.lic` (estado soportado, SC-013), la
génesis queda `"unlicensed"` y la cadena la ata al primer `license_id` con
firma válida vía el evento `license_genesis_anchored` — `verify_export` acepta
una génesis `"unlicensed"` **solo** con ese anclaje apuntando al `license_id`
del onboarding (sin eventos licenciados previos). Basa registra el
`license_id` emitido; no hace falta coordinar nada más.

## Rotación de claves (resumen; detalle en el contract test)

- **Licencias**: keyset multi-`key_id` — publicar keyset con kid viejo+nuevo,
  emitir con el nuevo, retirar el viejo cuando no queden licencias vivas.
- **Deployment key**: regenerar en la caja + re-registrar la pública en el
  onboarding (la génesis NO cambia; la continuidad de exports se preserva).
