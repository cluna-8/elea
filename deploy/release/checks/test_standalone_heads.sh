#!/usr/bin/env bash
# S4 en la imagen publicada (spec 057 T088, QA B1): el CMD de backend/Dockerfile.standalone (la
# imagen que consume el instalador, publish-elea.sh) migra a `heads` SOLO si
# ALEMBIC_EXTRA_VERSION_LOCATIONS trae algo y a `head` si no —la misma lógica que backend/Dockerfile
# y deploy/docker/entrypoint/backend.sh—, y no arranca uvicorn si la migración falla.
#
# SIN Docker: se extrae el CMD del Dockerfile y se corre con `sh -c` contra dobles de `alembic` y
# `uvicorn` que registran sus argumentos.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOCKERFILE="$REPO_ROOT/backend/Dockerfile.standalone"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "❌ $1"; exit 1; }

# El CMD en forma exec (JSON) → la cadena que recibe `sh -c`.
CMD="$(python3 - "$DOCKERFILE" <<'PY'
import json, re, sys
src = open(sys.argv[1], encoding="utf-8").read()
m = re.search(r'^CMD (\[.*\])\s*$', src, flags=re.M)
assert m, "sin CMD en forma exec"
argv = json.loads(m.group(1))
assert argv[:2] == ["sh", "-c"] and len(argv) == 3, argv
print(argv[2])
PY
)" || fail "no se pudo leer el CMD de backend/Dockerfile.standalone"

mkdir -p "$WORK/bin"
cat > "$WORK/bin/alembic" <<SH
#!/bin/sh
echo "alembic \$*" >> "$WORK/calls"
[ "\${ALEMBIC_FALLA:-}" = 1 ] && exit 1
exit 0
SH
cat > "$WORK/bin/uvicorn" <<SH
#!/bin/sh
echo "uvicorn \$*" >> "$WORK/calls"
SH
chmod +x "$WORK/bin/alembic" "$WORK/bin/uvicorn"

corre() { # [VAR=valor ...] → el contenido de calls tras correr el CMD
    : > "$WORK/calls"
    env -i PATH="$WORK/bin:/usr/bin:/bin" "$@" sh -c "$CMD" >/dev/null 2>&1 || true
    cat "$WORK/calls"
}

[ "$(corre | head -1)" = "alembic upgrade head" ]  || fail "sin ALEMBIC_EXTRA_VERSION_LOCATIONS debe migrar a 'head' (hoy: $(corre | head -1))"
corre | grep -q '^uvicorn src.main:app' || fail "sin la variable, uvicorn no arrancó tras migrar"
[ "$(corre ALEMBIC_EXTRA_VERSION_LOCATIONS= | head -1)" = "alembic upgrade head" ] || fail "una variable vacía debe migrar a 'head'"
[ "$(corre ALEMBIC_EXTRA_VERSION_LOCATIONS=/opt/sentinel-ext/sentinel/migrations | head -1)" = "alembic upgrade heads" ] \
    || fail "con ALEMBIC_EXTRA_VERSION_LOCATIONS debe migrar a 'heads'"
corre ALEMBIC_EXTRA_VERSION_LOCATIONS=/x | grep -q '^uvicorn src.main:app' || fail "con la variable, uvicorn no arrancó tras migrar"
# Una migración que falla no deja arrancar el servidor (el `&&` del CMD), con o sin la variable.
corre ALEMBIC_FALLA=1 | grep -q '^uvicorn' && fail "con alembic fallando, uvicorn arrancó (sin la variable)"
corre ALEMBIC_FALLA=1 ALEMBIC_EXTRA_VERSION_LOCATIONS=/x | grep -q '^uvicorn' && fail "con alembic fallando, uvicorn arrancó (con la variable)"

# Paridad con las otras dos puertas de arranque del backend: mismo criterio `head`/`heads`.
grep -q 'ALEMBIC_TARGET=heads' "$REPO_ROOT/deploy/docker/entrypoint/backend.sh" || fail "el entrypoint de producción ya no decide heads"
grep -q 'alembic upgrade \$t' "$REPO_ROOT/backend/Dockerfile" || fail "el CMD de backend/Dockerfile ya no decide heads"

echo "✅ Dockerfile.standalone: 'heads' solo con ALEMBIC_EXTRA_VERSION_LOCATIONS, 'head' sin ella (vacía incluida) y sin uvicorn si la migración falla"
