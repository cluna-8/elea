#!/usr/bin/env bash
# Entorno extra opcional (EXTRA_ENV_FILE) en compose.prod.yml: backend y engine declaran
# un env_file con la sintaxis larga (`path` + `required: false`, Compose ≥ 2.24) que por
# default apunta a /dev/null. Sin la variable el env efectivo no cambia; con ella, las
# variables del fichero se SUMAN y `environment:` sigue ganando en un choque.
#
# (a) ESTRUCTURA, siempre (python3 + PyYAML): el bloque exacto en los dos servicios.
# (b) EFECTIVO, si hay `docker compose` (sólo `config`: no levanta ni contacta contenedores):
#     el env renderizado con y sin la variable, contra el compose sin los bloques.
#     Sin el plugin se anuncia y se omite — un gate que se degrada en silencio no es un gate.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
COMPOSE="$REPO_ROOT/deploy/docker/compose.prod.yml"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
fail() { echo "❌ $1"; exit 1; }
python3 -c 'import yaml' 2>/dev/null || fail "necesita python3 con PyYAML"

# (a) Estructura.
python3 - "$COMPOSE" <<'PY' || fail "estructura del env_file extra inválida en compose.prod.yml"
import sys, yaml
src = open(sys.argv[1], encoding="utf-8").read()
svcs = yaml.safe_load(src)["services"]
want = [{"path": "${EXTRA_ENV_FILE:-/dev/null}", "required": False}]
for name in ("backend", "engine"):
    got = svcs[name].get("env_file")
    assert got == want, f"{name}: env_file = {got!r}, esperado {want!r}"
assert "2.24" in src.split("services:")[0], "la cabecera no documenta el mínimo Compose ≥ 2.24"
PY

# (b) Efectivo vía `docker compose config`.
if ! docker compose version >/dev/null 2>&1; then
    echo "⚠️  sin 'docker compose': se validó sólo la estructura (omitido el env efectivo)"
    echo "✅ entorno extra opcional OK (estructura)"
    exit 0
fi
# Valores de relleno para las ${VAR:?} obligatorias: `config` las exige para interpolar.
grep -oE '\$\{[A-Z_][A-Z0-9_]*:\?' "$COMPOSE" | grep -oE '[A-Z_][A-Z0-9_]*' | sort -u \
    | sed 's/$/=relleno/' > "$WORK/relleno.env"
# Mismo compose SIN los bloques env_file (lo que había antes), en el mismo directorio de
# proyecto para que los paths relativos resuelvan igual.
python3 - "$COMPOSE" "$WORK/sin_bloque.yml" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
for name in ("backend", "engine"):
    c["services"][name].pop("env_file")
yaml.safe_dump(c, open(sys.argv[2], "w", encoding="utf-8"), sort_keys=False)
PY
envs() { # fichero-compose → JSON {servicio: environment} de backend y engine
    docker compose --project-directory "$REPO_ROOT/deploy/docker" -f "$1" \
        --env-file "$WORK/relleno.env" --profile selfhosted config --format json \
      | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; print(json.dumps({k: s[k].get("environment", {}) for k in ("backend","engine")}, sort_keys=True))'
}
antes="$(unset EXTRA_ENV_FILE; envs "$WORK/sin_bloque.yml")"
sin="$(unset EXTRA_ENV_FILE; envs "$COMPOSE")"
[ "$antes" = "$sin" ] || fail "sin EXTRA_ENV_FILE el env efectivo de backend/engine cambió"
# Fichero inexistente: required=false ⇒ se ignora, sin error.
falta="$(EXTRA_ENV_FILE="$WORK/no-existe.env" envs "$COMPOSE")" || fail "un EXTRA_ENV_FILE inexistente rompió el config"
[ "$antes" = "$falta" ] || fail "un EXTRA_ENV_FILE inexistente cambió el env efectivo"
# Con fichero: suma la variable nueva a los dos servicios; en un choque gana environment:.
CHOCA="$(python3 -c 'import sys,yaml; print(next(iter(yaml.safe_load(open(sys.argv[1]))["services"]["backend"]["environment"])))' "$COMPOSE")"
printf 'EXTRA_ENV_PRUEBA=si\n%s=pisado-desde-extra\n' "$CHOCA" > "$WORK/extra.env"
con="$(EXTRA_ENV_FILE="$WORK/extra.env" envs "$COMPOSE")"
python3 - "$antes" "$con" "$CHOCA" <<'PY' || fail "con EXTRA_ENV_FILE el env efectivo no es 'antes + la variable extra'"
import json, sys
antes, con, choca = json.loads(sys.argv[1]), json.loads(sys.argv[2]), sys.argv[3]
for svc in ("backend", "engine"):
    esperado = dict(antes[svc], EXTRA_ENV_PRUEBA="si")
    if choca not in antes[svc]:
        esperado[choca] = "pisado-desde-extra"   # el engine no declara esa clave: la suma
    assert con[svc] == esperado, (svc, set(con[svc].items()) ^ set(esperado.items()))
PY

echo "✅ entorno extra opcional OK: estructura en backend/engine, sin variable = env idéntico, fichero ausente ignorado, con fichero suma variables y environment: gana"
