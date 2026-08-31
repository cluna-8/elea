#!/usr/bin/env bash
# T016 (US3): el perfil renderiza por cliente (config templado + brand + envs
# derivados del slug) y el seed materializa clients IDEMPOTENTE via 013.
# Necesita el compose de dev arriba (sentinel-db); usa una DB efímera propia.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
fail() { echo "❌ $1"; exit 1; }

# 1) Render: vars del perfil resueltas, dominio/workspace derivados del slug.
"$REPO_ROOT/deploy/release/render_profile.sh" example >/dev/null
R="$REPO_ROOT/deploy/clients/example/rendered"
grep -q "model: azure/gpt-4o-eu" "$R/config.yaml" || fail "model_list no templado por cliente"
grep -q "residencia eu-central-1" "$R/config.yaml" || fail "región no inyectada"
grep -q "PRODUCT_DOMAIN=example.clients.sentinel.example" "$R/instance.env" || fail "dominio no deriva del slug"
grep -q '"name": "Aegis AI Firewall"' "$R/brand.json" || fail "brand.json no renderizado"

# 2) Seed idempotente contra una DB efímera (jamás la DB viva de dev).
cd "$REPO_ROOT"
docker exec sentinel-db psql -U sentinel_admin -d sentinel_gateway -q -c "DROP DATABASE IF EXISTS sentinel_profile_check" 
docker exec sentinel-db psql -U sentinel_admin -d sentinel_gateway -q -c "CREATE DATABASE sentinel_profile_check"
trap 'docker exec sentinel-db psql -U sentinel_admin -d sentinel_gateway -q -c "DROP DATABASE IF EXISTS sentinel_profile_check"' EXIT

run_seed() {
  docker compose run --rm --no-deps -e POSTGRES_DB=sentinel_profile_check \
    -v "$REPO_ROOT/deploy/clients/example:/profile:ro" backend \
    sh -c "python -m alembic upgrade head >/dev/null 2>&1; python scripts/apply_profile_seed.py example /profile/seed.yaml"
}
run_seed >/dev/null || fail "primer seed falló"
out=$(run_seed) || fail "re-seed falló (no idempotente)"
echo "$out" | grep -q "2 clients sembrados" || fail "conteo inesperado: $out"

count=$(docker exec sentinel-db psql -U sentinel_admin -d sentinel_profile_check -tAc \
  "SELECT count(*) FROM users WHERE username LIKE 'aegis-%'")
[ "$count" = "2" ] || fail "idempotencia rota: $count users aegis-* (esperados 2)"

echo "✅ perfil por cliente OK: render templado + seed idempotente (2 clients, sin duplicar)"
