#!/usr/bin/env bash
# 022 v2 (post-OK del template): LINTER DE ESTRUCTURA del sitio — la "estructura
# siempre igual" es un contrato verificado, no buena voluntad (ver docs/README.md).
# Corre sobre las FUENTES ES (docs/docs/**.md, sin *.en.md ni referencias generadas).
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
D="$REPO_ROOT/docs/docs"

fail() { echo "❌ estructura: $1"; exit 1; }

GUIAS=(overview/index.md install-deploy/index.md install-deploy/infrastructure.md \
       install-deploy/licensing.md install-deploy/partner-enablement.md \
       white-label/index.md administration/index.md administration/gobernanza.md \
       integrations/index.md integrations/modelo-propio.md \
       compliance/index.md compliance/dpa-dsr-retention.md)
RUNBOOKS=(operations/index.md integrations/gotchas.md)

links_internos() { grep -oE '\]\((\.\./|\./)?[a-z0-9_/-]+\.md' "$1" | wc -l | tr -d ' '; }

for p in "${GUIAS[@]}"; do
    f="$D/$p"
    [ -f "$f" ] || fail "$p no existe"
    grep -q '^```mermaid' "$f"        || fail "$p (GUÍA) sin diagrama Mermaid"
    grep -q '^## Relacionado' "$f"    || fail "$p (GUÍA) sin sección '## Relacionado'"
    grep -q '\*\*Para quién\*\*' "$f" || fail "$p (GUÍA) sin línea '**Para quién**'"
    n=$(links_internos "$f"); [ "$n" -ge 3 ] || fail "$p (GUÍA) con $n links internos (<3)"
done

for p in "${RUNBOOKS[@]}"; do
    f="$D/$p"
    grep -q '^## Relacionado' "$f" || fail "$p (RUNBOOK) sin sección '## Relacionado'"
    n=$(links_internos "$f"); [ "$n" -ge 3 ] || fail "$p (RUNBOOK) con $n links internos (<3)"
done

# Cero huérfanas: toda página de contenido recibe ≥1 link entrante desde otra página.
while IFS= read -r f; do
    rel="${f#"$D/"}"
    case "$rel" in index.md|*.en.md|api-reference/*) continue ;; esac
    base=$(basename "$rel")
    grep -rq --include='*.md' "$base" "$D" --exclude="$base" \
        || fail "página huérfana: $rel (ninguna otra página la linkea)"
done < <(find "$D" -name '*.md')

echo "✅ estructura OK: template de GUÍA/RUNBOOK cumplido, diagramas presentes, 0 huérfanas"
