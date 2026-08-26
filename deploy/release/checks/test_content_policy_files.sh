#!/usr/bin/env bash
# Invariante category_file (#143, brief de Jeff): un guardrail de LiteLLM cuyo
# archivo de categorías no existe NO falla — deja pasar el tráfico sin filtrar
# (fail-open, medido por Jeff en contenedores reales). Este check es la red que
# impide que eso llegue a un cliente.
#
# Verifica, en los DOS planos que declaran guardrails:
#   - litellm/config.yaml              → config de DEV
#   - deploy/clients/*/config.yaml.tmpl → 3 perfiles de PROD (fuente del config
#     que se ENTREGA: render_profile.sh → rendered/config.yaml → populate_volumes.sh)
#
# Por cada category_file declarado en cualquiera de esos archivos:
#   (i-bis) el path empieza con /app/policy_categories/ (el único mount que
#           entrega el compose); path fuera ⇒ ❌ guiado (fail-closed)
#   (i)   el archivo existe en el repo (mapeo /app/policy_categories/X.yaml
#         → litellm/policy_categories/X.yaml)
#   (ii)  si hay ≥1 category_file declarado, el canal de entrega está cableado:
#         compose.prod.yml monta policy_categories Y populate_volumes.sh lo nombra
#   (iii) si el VALOR de category_file contiene ${ sin resolver → ❌: el .tmpl
#         no sustituye y no se puede verificar un path que todavía no existe.
#         (El guard busca en el VALOR, no en el archivo: los .tmpl tienen ${}
#         legítimas por diseño — ${TENANT_SLUG}, ${REGION}… — que resuelve envsubst.)
#
# Hoy pasa trivial: los 4 archivos declaran guardrails pero CERO category_file.
# La red se pone antes de que llegue la carga.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

DEV_CONFIG="$REPO_ROOT/litellm/config.yaml"
PROD_COMPOSE="$REPO_ROOT/deploy/docker/compose.prod.yml"
POPULATE="$REPO_ROOT/deploy/release/populate_volumes.sh"

fail=0
error() { echo "❌ $1"; fail=1; }

# Archivos que declaran guardrails: dev + perfiles de cliente (.tmpl)
declare -a PLANOS=("$DEV_CONFIG")
for tmpl in "$REPO_ROOT"/deploy/clients/*/config.yaml.tmpl; do
    [ -f "$tmpl" ] && PLANOS+=("$tmpl")
done

# Extrae los category_file declarados.
# grep devuelve "17:    category_file: /app/policy_categories/X.yaml"
# Filtra comentarios con grep -vE '^[[:space:]]*#' (un anchor a ^[[:space:]]*category_file:
# NO ve declaraciones YAML válidas como item de lista: "- category_file: ...").
# El filtro de comentarios cubre: comentario a inicio de línea y comentario indentado,
# sin perder declaraciones indentadas, items de lista, ni declaraciones con comentario al final.
#
# LÍMITE DECLARADO: el filtro re-abre el substring-match — 'otro_category_file:' o una
# mención de 'category_file:' dentro de un string también disparan. Es el precio explícito
# de no anclar a ^[[:space:]]*category_file: (que perdía items de lista). Para una red de
# compliance es el lado correcto: rojo ruidoso (falso positivo) antes que verde falso.
# Refinamiento futuro: ver issue de seguimiento del PR.
#
# ESTO es un parser de LÍNEA, no un parser de YAML: toda forma nueva de escribir el valor
# (comillas, bloques folded, anchors, aliases) es un caso nuevo. El stripping de comillas
# de abajo cubre la forma idiomática más común; lo demás se descubre por rojo ruidoso.
extraer_category_files() {
    local plano="$1"
    grep 'category_file:' "$plano" 2>/dev/null | grep -vE '^[[:space:]]*#' || true
}

# Recolecta todos los category_file declarados: <plano>\t<path>
declarados=""

for plano in "${PLANOS[@]}"; do
    [ -f "$plano" ] || { error "$plano: no existe"; continue; }
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        # Extraer el valor: todo lo que venga después de "category_file:"
        path="$(echo "$line" | sed -nE 's/.*category_file:[[:space:]]*([^[:space:]]+).*/\1/p')"
        # YAML idiomático puede citar el valor: category_file: "/app/..." o '/app/...'
        # El sed captura las comillas como parte del valor; las stripping acá para
        # que los guards de prefijo y existencia comparen contra el path real.
        # Va ANTES del guard de vacío: category_file: "" (string vacío citado) pasa
        # el sed como no-vacío, el strip lo deja vacío, y sin esta orden el check
        # reportaría ❌ de canal en vez de ❌ de declaración malformada.
        path="${path%\"}"; path="${path#\"}"
        path="${path%\'}"; path="${path#\'}"
        if [ -z "$path" ]; then
            error "$(basename "$plano"): línea con 'category_file:' sin path —
   declaración malformada. Completala con el path o borrala."
            continue
        fi
        declarados+="${plano}"$'\t'"${path}"$'\n'
    done < <(extraer_category_files "$plano")
done

# ── (iii) Guard de variable sin resolver en el VALOR ──────────────────────────
while IFS=$'\t' read -r plano path; do
    [ -z "$path" ] && continue
    if [[ "$path" == *'${'* ]]; then
        error "$(basename "$plano"): category_file parametrizado ('$path'):
   este check no lo puede resolver; si el caso es legítimo, hay que extender
   el check para resolver contra el perfil"
    fi
done <<<"$declarados"

# ── (i-bis) Prefijo del mount conocido + escape por ../ ─────────────────────────
# El compose sólo monta ./litellm/policy_categories:/app/policy_categories:ro.
# Un category_file fuera de ese prefijo no llega al contenedor — el guardrail
# lee /app/otra/X.yaml, no existe, y LiteLLM fail-open: deja pasar sin filtrar.
# El case rechaza la PRESENCIA de '..' en el path — no resuelve el path, valida
# la forma: ../ escapa del prefijo aunque empiece con /app/policy_categories/
# (ej: /app/policy_categories/../otra/X.yaml). Es fail-closed: path fuera o con
# .. ⇒ ❌ guiado, aunque el archivo exista.
while IFS=$'\t' read -r plano path; do
    [ -z "$path" ] && continue
    case "$path" in
        *..*) error "$(basename "$plano"): category_file '$path' con '..' (escape del mount)
   el path resuelve fuera de /app/policy_categories/ aunque empiece con el prefijo.
   LiteLLM no lo encontraría y falla abierto (fail-open). Usá un path lineal." ;;
        /app/policy_categories/*) ;;
        *) error "$(basename "$plano"): category_file '$path' fuera del mount conocido
   (/app/policy_categories/). El compose no lo entrega al contenedor: el guardrail
   no lo encontraría y LiteLLM falla abierto (fail-open). Mové el archivo
   a policy_categories/ o extendé el mount Y este check." ;;
    esac
done <<<"$declarados"

# ── (i) El archivo existe ─────────────────────────────────────────────────────
while IFS=$'\t' read -r plano path; do
    [ -z "$path" ] && continue
    # Mapeo: /app/policy_categories/X.yaml → litellm/policy_categories/X.yaml
    # El mount del compose es ./litellm/policy_categories:/app/policy_categories:ro,
    # así que el path real en el repo es litellm/ + el relativo del contenedor.
    rel="${path#/app/}"
    repo_path="$REPO_ROOT/litellm/$rel"
    if [ ! -f "$repo_path" ]; then
        error "$(basename "$plano"): category_file '$path' declarado pero
   no existe en el repo ($repo_path)"
    fi
done <<<"$declarados"

# ── (ii) Canal de entrega cableado (sólo si hay ≥1 declarado) ─────────────────
total_declarados=$(echo -n "$declarados" | grep -c . || true)
if [ "$total_declarados" -gt 0 ]; then
    if ! grep -q 'policy_categories' "$PROD_COMPOSE"; then
        error "compose.prod.yml: no monta policy_categories
   hay category_file declarados y el canal de entrega (mount) no está cableado"
    fi
    if ! grep -q 'policy_categories' "$POPULATE"; then
        error "populate_volumes.sh: no nombra policy_categories
   hay category_file declarados y el canal de entrega (copia) no está cableado"
    fi
fi

if [ "$fail" = 0 ]; then
    if [ "$total_declarados" -eq 0 ]; then
        echo "✅ invariante category_file OK: 0 declarados (red puesta, sin carga)"
    else
        echo "✅ invariante category_file OK: $total_declarados declarado(s), todos existen y el canal de entrega está cableado"
    fi
fi
exit $fail
