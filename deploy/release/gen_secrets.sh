#!/usr/bin/env bash
# Genera los secretos de UNA instalación (spec 020 US5 — el glue que faltaba,
# hallazgo de la auditoría pre-piloto 2026-07-22): el compose prod exige todas
# estas variables con ${VAR:?} y el repo no traía generador — cada install las
# inventaba a mano. Produce un env file completo con permisos 600.
#
# Uso: deploy/release/gen_secrets.sh <client-slug> [outfile]
#   outfile default: deploy/clients/<slug>/rendered/secrets.env (gitignored)
#
# El archivo resultante se pasa a compose junto al instance.env del perfil:
#   docker compose -f deploy/docker/compose.prod.yml --profile selfhosted \
#     --env-file deploy/clients/<slug>/rendered/instance.env \
#     --env-file deploy/clients/<slug>/rendered/secrets.env up -d
set -euo pipefail

SLUG="${1:?uso: gen_secrets.sh <client-slug> [outfile]}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${2:-$REPO_ROOT/deploy/clients/$SLUG/rendered/secrets.env}"

[ -d "$REPO_ROOT/deploy/clients/$SLUG" ] || {
    echo "❌ no existe deploy/clients/$SLUG (armar el perfil primero)"; exit 2; }
if [ -e "$OUT" ]; then
    echo "❌ $OUT ya existe — regenerar secretos rompe una instalación viva."
    echo "   Si es intencional, borralo a mano primero."
    exit 2
fi

rand_hex()    { openssl rand -hex "$1"; }
rand_b64url() { openssl rand -base64 "$1" | tr '+/' '-_' | tr -d '='; }

mkdir -p "$(dirname "$OUT")"
umask 177
cat > "$OUT" <<EOF
# Secretos de la instalación '$SLUG' — generados $(date -u +%FT%TZ).
# chmod 600. JAMÁS commitear ni reutilizar entre instalaciones.
POSTGRES_HOST=db
POSTGRES_DB=basa_guardian
POSTGRES_USER=basa
POSTGRES_PASSWORD=$(rand_hex 24)
REDIS_HOST=redis
JWT_SECRET_KEY=$(rand_b64url 48)
FERNET_SECRET_KEY=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
LITELLM_MASTER_KEY=sk-$(rand_hex 20)
EOF

echo "✅ secretos generados en $OUT (600)"
echo "   Falta del lado del perfil: *_IMAGE (release), BASA_DEPLOYMENT_TENANT_ID,"
echo "   y las API keys de los proveedores LLM del cliente (se añaden a este archivo)."
