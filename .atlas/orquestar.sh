#!/usr/bin/env bash
# .atlas/orquestar.sh — runner de orquestación de Atlas sobre Orca (kit atlas-coordinador).
#
# Convierte un PLAN (JSON con tareas, roles, dependencias y compuertas) en un Run de Orca,
# despacha cada tarea con el perfil de su rol y hace cumplir lo que Orca no hace cumplir solo:
#   - una compuerta pendiente bloquea el despacho y el cierre de su tarea (en Orca, la
#     compuerta solo marca la tarea `blocked`: un task-update la saltea sin aviso);
#   - un rol en pausa no se despacha;
#   - si el proyecto declara una base protegida (.atlas/config.json → base_protegida), tocar
#     un archivo de esa base sin su registro en el mismo diff es error (subcomando `verificar`).
#
# Guía completa (cuándo usar cada rol, el ciclo, cómo escribir un plan):
#   .atlas/ORQUESTACION.md
#
# Uso:
#   .atlas/orquestar.sh plan <plan.json> [--dry-run] [--run <run_id>]
#   .atlas/orquestar.sh despachar <plan.estado.json> <clave> [--dry-run] [--setup run|skip]
#   .atlas/orquestar.sh estado <plan.estado.json>
#   .atlas/orquestar.sh compuerta <plan.estado.json> <clave> <resolución>
#   .atlas/orquestar.sh cerrar <plan.estado.json> <clave>
#   .atlas/orquestar.sh verificar <plan.estado.json> <clave>
#   .atlas/orquestar.sh verificar --worktree <ruta> [--base <ref>] [--rutas 'glob1,glob2']
#
# Multi-repo: una tarea con "repo": "<nombre en Orca>" (y opcional "rama_base") abre su
# worktree en ese repo; el Run, las compuertas y la bandeja siguen siendo las de este repo.
#
# Plantillas de plan: .atlas/plantillas/{implementacion,spike,fix}.json
# Roles:             .atlas/roles.json      Config del proyecto: .atlas/config.json

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROLES_FILE="${ROLES_FILE:-$REPO_ROOT/.atlas/roles.json}"
CONFIG_FILE="${CONFIG_FILE:-$REPO_ROOT/.atlas/config.json}"

die()  { echo "[x] $*" >&2; exit 1; }
info() { echo "[i] $*" >&2; }
warn() { echo "[!] $*" >&2; }

command -v jq >/dev/null || die "falta jq"
[ -f "$ROLES_FILE" ] || die "no encuentro el catálogo de roles: $ROLES_FILE"
[ -f "$CONFIG_FILE" ] || die "no encuentro la config del proyecto: $CONFIG_FILE"
cfg() { jq -r "$1 // empty" "$CONFIG_FILE"; }
REGISTRO="$(cfg .base_protegida.registro)"
grep -q '{{' "$ROLES_FILE" "$CONFIG_FILE" && die "roles.json o config.json tienen marcadores {{...}} sin completar: el bootstrap no terminó"

# --- Ejecutable de Orca -----------------------------------------------------------------
# En Linux, `orca` a secas fuera de un terminal de Orca es el lector de pantalla de GNOME:
# jamás se usa como fallback ahí.
resolver_orca() {
  if [ -n "${ORCA_CLI_COMMAND:-}" ]; then echo "$ORCA_CLI_COMMAND"; return; fi
  if [ -n "$(cfg .orca_cli)" ]; then cfg .orca_cli; return; fi
  if [ -n "${ORCA_DEV_REPO_ROOT:-}" ] && command -v orca-dev >/dev/null; then echo orca-dev; return; fi
  if [ "$(uname -s)" = Linux ]; then
    command -v orca-ide >/dev/null && { echo orca-ide; return; }
    die "no encuentro orca-ide (en Linux no se usa 'orca' a secas: es el lector de pantalla)"
  fi
  command -v orca >/dev/null && { echo orca; return; }
  die "no encuentro el CLI de Orca"
}
ORCA=""
orca_json() {   # orca_json <args...> → imprime .result o muere con el error de Orca
  [ -n "$ORCA" ] || ORCA="$(resolver_orca)"
  local out
  out="$("$ORCA" "$@" --json 2>&1)" || true
  if ! echo "$out" | jq -e '.ok == true' >/dev/null 2>&1; then
    die "orca $1 $2 falló: $(echo "$out" | jq -r '.error.message // .' 2>/dev/null | head -5)"
  fi
  echo "$out" | jq '.result'
}

# --- Utilidades de estado ---------------------------------------------------------------
estado_get()  { jq -r "$2" "$1"; }
estado_set()  { local f="$1" expr="$2"; shift 2; local tmp; tmp="$(mktemp)"; jq "$@" "$expr" "$f" >"$tmp" && mv "$tmp" "$f"; }
plan_de()     { estado_get "$1" '.plan'; }
tarea_plan()  { jq -c --arg k "$2" '.tareas[] | select(.clave == $k)' "$(plan_de "$1")"; }
rol_de()      { jq -c --arg r "$1" '.roles[$r] // empty' "$ROLES_FILE"; }

repo_selector() {   # id:<repo> de Orca. Sin argumento: el checkout principal de este repo.
  # Con argumento: el repo de Orca con ese nombre (campo "repo" de una tarea: multi-repo).
  local nombre="${1:-}" principal id
  if [ -n "$nombre" ]; then
    id="$(orca_json repo list | jq -r --arg n "$nombre" '.repos[] | select(.displayName == $n or .name == $n) | .id' | head -1)"
    [ -n "$id" ] || die "Orca no tiene registrado un repo llamado '$nombre' (orca-ide repo list)"
    echo "id:$id"; return
  fi
  principal="$(cd "$(git -C "$REPO_ROOT" rev-parse --path-format=absolute --git-common-dir)/.." && pwd)"
  id="$(orca_json repo list | jq -r --arg p "$principal" '.repos[] | select(.path == $p) | .id' | head -1)"
  [ -n "$id" ] || die "Orca no tiene registrado el repo $principal (orca-ide repo list)"
  echo "id:$id"
}
base_de_tarea() {   # rama_base de la tarea, o la del plan
  echo "$1" | jq -r --arg b "$(jq -r '.rama_base // "origin/main"' "$2")" '.rama_base // $b'
}

ref_base_protegida() {   # vacío si el proyecto no declara base protegida (fork, vendor...)
  local r; r="${BASE_REF:-$(cfg .base_protegida.ref)}"
  [ -n "$r" ] || return 0
  git -C "$REPO_ROOT" rev-parse -q --verify "$r^{commit}" >/dev/null \
    || die "la base protegida '$r' no existe en local: git fetch de su remote"
  echo "$r"
}

# --- plan -------------------------------------------------------------------------------
validar_plan() {
  local plan="$1" errores
  errores="$(jq -r --slurpfile roles "$ROLES_FILE" '
    def rol($r): $roles[0].roles[$r];
    . as $p
    | ($p.tareas // []) as $t
    | [ (if ($t | length) == 0 then "el plan no tiene tareas" else empty end),
        (if ($p.objetivo // "") == "" then "falta objetivo" else empty end),
        ($t | group_by(.clave)[] | select(length > 1) | "clave repetida: \(.[0].clave)"),
        ($t[] | . as $x | (.depende_de // [])[]
           | select(. as $d | ($t | map(.clave) | index($d)) == null)
           | "\($x.clave): depende de una clave inexistente: \(.)"),
        ($t[] | select(rol(.rol) == null) | "\(.clave): rol desconocido: \(.rol)"),
        ($t[] | select(rol(.rol).pausado == true) | "\(.clave): el rol \(.rol) está en pausa (\(rol(.rol).motivo))"),
        ($t[] | select(.rol != "atlas") | . as $x
           | ("alcance","cambio","propiedad","aceptacion")
           | select(($x[.] // "") == "") | "\($x.clave): falta \(.)"),
        ($t[] | select(.rol != "atlas") | . as $x
           | (.worktree // "nuevo") as $w
           | if $w == "nuevo" then (if ($x.rama // "") == "" then "\($x.clave): worktree nuevo exige rama" else empty end)
             elif ($w | startswith("de:")) then
               (($w | ltrimstr("de:")) as $o
                | if (($x.depende_de // []) | index($o)) == null
                  then "\($x.clave): worktree de:\($o) exige depender de \($o)" else empty end)
             else "\($x.clave): worktree inválido: \($w) (nuevo | de:<clave>)" end),
        ($t[] | select(.repo != null and ((.worktree // "nuevo") != "nuevo"))
           | "\(.clave): repo solo va con worktree nuevo (de:<clave> hereda el repo de la otra tarea)"),
        ($t[] | select(.compuerta != null) | . as $x
           | if ((.compuerta.opciones // []) | length) < 2 then "\($x.clave): la compuerta necesita al menos 2 opciones (la primera es la que aprueba)" else empty end),
        ([del(._doc) | .. | strings | select(test("\\{\\{[^}]+\\}\\}"))] | if length > 0 then "plantilla sin completar: \(.[0])" else empty end)
      ] | .[]' "$plan")"
  [ -z "$errores" ] || die "plan inválido:
$errores"
  jq -e '[.tareas[] | select(.compuerta != null)] | length > 0' "$plan" >/dev/null \
    || warn "el plan no tiene ninguna compuerta: nada exige tu aprobación antes de integrar"
}

orden_topologico() {   # imprime las claves en un orden que respeta depende_de; muere si hay ciclo
  local plan="$1" hechas=() pendientes progreso k deps d ok
  mapfile -t pendientes < <(jq -r '.tareas[].clave' "$plan")
  while [ "${#pendientes[@]}" -gt 0 ]; do
    progreso=false; local resto=()
    for k in "${pendientes[@]}"; do
      mapfile -t deps < <(jq -r --arg k "$k" '.tareas[] | select(.clave == $k) | (.depende_de // [])[]' "$plan")
      ok=true
      for d in "${deps[@]}"; do [[ " ${hechas[*]} " == *" $d "* ]] || { ok=false; break; }; done
      if $ok; then hechas+=("$k"); echo "$k"; progreso=true; else resto+=("$k"); fi
    done
    $progreso || die "ciclo en depende_de entre: ${resto[*]}"
    pendientes=("${resto[@]}")
  done
}

componer_spec() {   # el spec autocontenido que recibe el worker (contrato de Orca)
  local plan="$1" k="$2"
  jq -r --arg k "$k" --slurpfile roles "$ROLES_FILE" '
    $roles[0] as $R
    | .tareas[] | select(.clave == $k) as $t
    | $R.roles[$t.rol] as $rol
    | if $t.rol == "atlas" then
        "PASO DEL COORDINADOR (no se despacha).\nAlcance: \($t.alcance // "-")\nCambio: \($t.cambio // "-")\nAceptación: \($t.aceptacion // "-")"
      else
        "Rol: \($t.rol) — \($rol.para)\n"
        + (if $t.repo then "Repo: \($t.repo) (no es el repo del coordinador; las reglas de AGENTS.md que valen son las de ese repo, si las tiene)\n" else "" end)
        + "Alcance: \($t.alcance)\n"
        + "Cambio: \($t.cambio)\n"
        + "Restricciones: \($R.reglas_comunes) \($rol.addenda) \($t.restricciones // "")\n"
        + "Propiedad: \($t.propiedad)"
        + (if (($t.rutas // []) | length) > 0 then " Rutas permitidas: \($t.rutas | join(", ")). Tocar otra ruta hace fallar la verificación del coordinador." else "" end) + "\n"
        + "Aceptación: \($t.aceptacion)"
      end' "$plan"
}

cmd_plan() {
  local plan="" dry=false run=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) dry=true ;;
      --run) run="$2"; shift ;;
      *) plan="$1" ;;
    esac; shift
  done
  [ -f "$plan" ] || die "uso: plan <plan.json> [--dry-run] [--run <run_id>]"
  plan="$(cd "$(dirname "$plan")" && pwd)/$(basename "$plan")"
  # El estado es local y no se commitea: vive fuera del repo.
  local dir_estado="${ATLAS_ORQ_ESTADO:-${XDG_STATE_HOME:-$HOME/.local/state}/atlas-orquestar/$(basename "$REPO_ROOT")}"
  local estado="$dir_estado/$(basename "$(dirname "$plan")")--$(basename "${plan%.json}").estado.json"
  [ -e "$estado" ] && ! $dry && die "ya existe $estado: este plan ya se materializó (borralo a mano si de verdad querés otro Run)"
  $dry || mkdir -p "$dir_estado"

  validar_plan "$plan"
  local orden; orden="$(orden_topologico "$plan")"
  info "plan válido; orden: $(echo $orden)"

  if $dry; then
    local k
    for k in $orden; do
      echo "=== $k  [$(jq -r --arg k "$k" '.tareas[]|select(.clave==$k)|"\(.rol) · deps \(.depende_de // [] | join(",")) · compuerta: \(.compuerta.pregunta // "no")"' "$plan")]"
      componer_spec "$plan" "$k"; echo
    done
    return
  fi

  if [ -z "$run" ]; then
    run="$(orca_json orchestration run-create --objective "$(jq -r .objetivo "$plan")" | jq -r .run.id)"
    info "Run creado y ligado a este terminal: $run"
  else
    orca_json orchestration run-use --id "$run" >/dev/null
    info "Run existente ligado: $run"
  fi
  jq -n --arg plan "$plan" --arg run "$run" '{plan:$plan, run:$run, tareas:{}}' >"$estado"

  local k titulo deps spec tid gid
  for k in $orden; do
    titulo="$(jq -r --arg k "$k" '.tareas[]|select(.clave==$k)|.titulo // .clave' "$plan")"
    deps="$(jq -c --arg k "$k" --slurpfile e "$estado" \
      '[.tareas[]|select(.clave==$k)|(.depende_de // [])[] as $d | $e[0].tareas[$d].task]' "$plan")"
    spec="$(componer_spec "$plan" "$k")"
    tid="$(orca_json orchestration task-create --run "$run" --task-title "$titulo" --spec "$spec" --deps "$deps" | jq -r .task.id)"
    estado_set "$estado" '.tareas[$k] = {task:$t}' --arg k "$k" --arg t "$tid"
    if jq -e --arg k "$k" '.tareas[]|select(.clave==$k)|.compuerta != null' "$plan" >/dev/null; then
      gid="$(orca_json orchestration gate-create --task "$tid" \
        --question "$(jq -r --arg k "$k" '.tareas[]|select(.clave==$k)|.compuerta.pregunta' "$plan")" \
        --options "$(jq -c --arg k "$k" '.tareas[]|select(.clave==$k)|.compuerta.opciones' "$plan")" | jq -r .gate.id)"
      estado_set "$estado" '.tareas[$k].gate = $g' --arg k "$k" --arg g "$gid"
    fi
    info "$k → $tid${gid:+ (compuerta $gid)}"; gid=""
  done
  echo "$estado"
}

# --- despachar --------------------------------------------------------------------------
exigir_run_ligado() {   # Orca rechaza mutar un Run que no es el ligado a este terminal
  # (consumer_fenced). No se cambia solo: la bandeja de mensajes del coordinador va con el Run.
  local run actual
  run="$(estado_get "$1" .run)"
  actual="$(orca_json orchestration run-current | jq -r '.run.id // empty')"
  [ "$run" = "$actual" ] || die "este terminal está ligado a ${actual:-ningún Run}, no a $run. Si es a propósito: orca-ide orchestration run-use --id $run (la bandeja de mensajes cambia con él)"
}
estado_tarea_orca() {   # status actual de la tarea en Orca
  orca_json orchestration task-list --run "$(estado_get "$1" .run)" \
    | jq -r --arg t "$2" '.tasks[] | select(.id == $t) | .status'
}
deps_abiertas() {   # claves de depende_de cuya tarea no está completed. No se confía en el
  # 'ready' de Orca: al resolver una compuerta Orca pone la tarea en ready aunque sus
  # dependencias sigan abiertas (verificado el 2-oct-2026).
  local estado="$1" k="$2" tasks d tid s
  tasks="$(orca_json orchestration task-list --run "$(estado_get "$estado" .run)")"
  for d in $(tarea_plan "$estado" "$k" | jq -r '(.depende_de // [])[]'); do
    tid="$(estado_get "$estado" ".tareas[\"$d\"].task")"
    s="$(echo "$tasks" | jq -r --arg t "$tid" '.tasks[] | select(.id == $t) | .status')"
    [ "$s" = completed ] || echo "$d($s)"
  done
}
compuerta_pendiente() {
  local gid; gid="$(estado_get "$1" ".tareas[\"$2\"].gate // empty")"
  [ -n "$gid" ] || return 1
  orca_json orchestration gate-list --task "$(estado_get "$1" ".tareas[\"$2\"].task")" \
    | jq -e --arg g "$gid" '[.gates[] | select(.id == $g and .status == "pending")] | length > 0' >/dev/null
}
worker_de() {   # última fila de worker-list para la tarea de esa clave
  orca_json orchestration worker-list --run "$(estado_get "$1" .run)" \
    | jq -c --arg t "$(estado_get "$1" ".tareas[\"$2\"].task")" '[.workers[] | select(.taskId == $t)][0] // empty'
}
ruta_worktree_de() { worker_de "$1" "$2" | jq -r '.resource.worktreeId // empty | split("::")[1] // empty'; }

cmd_despachar() {
  local estado="" k="" dry=false setup="skip"
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run) dry=true ;;
      --setup) setup="$2"; shift ;;
      *) if [ -z "$estado" ]; then estado="$1"; else k="$1"; fi ;;
    esac; shift
  done
  [ -f "$estado" ] && [ -n "$k" ] || die "uso: despachar <plan.estado.json> <clave> [--dry-run] [--setup run|skip]"
  local t rol perfil tid status desde=""
  t="$(tarea_plan "$estado" "$k")"; [ -n "$t" ] || die "no hay tarea $k en el plan"
  rol="$(echo "$t" | jq -r .rol)"; perfil="$(rol_de "$rol")"
  [ "$rol" != atlas ] || die "$k es un paso de Atlas: no se despacha (se hace en la sesión del coordinador y se cierra con 'cerrar')"
  echo "$perfil" | jq -e '.pausado != true' >/dev/null || die "el rol $rol está en pausa: $(echo "$perfil" | jq -r .motivo)"
  tid="$(estado_get "$estado" ".tareas[\"$k\"].task")"
  $dry || exigir_run_ligado "$estado"
  compuerta_pendiente "$estado" "$k" && die "$k tiene una compuerta pendiente: la resuelve el owner (subcomando compuerta)"
  local abiertas; abiertas="$(deps_abiertas "$estado" "$k")"
  [ -z "$abiertas" ] || die "$k depende de tareas sin cerrar: $(echo $abiertas)"
  status="$(estado_tarea_orca "$estado" "$tid")"
  [ "$status" = ready ] || die "$k está en '$status', no en 'ready' (¿dependencias sin cerrar?)"

  local args=(orchestration worker-start --task "$tid" --run "$(estado_get "$estado" .run)" --agent "$(echo "$perfil" | jq -r .agente)")
  local modelo esfuerzo; modelo="$(echo "$perfil" | jq -r '.modelo // empty')"; esfuerzo="$(echo "$perfil" | jq -r '.esfuerzo // empty')"
  [ -n "$modelo" ] && args+=(--model "$modelo") && [ -n "$esfuerzo" ] && args+=(--effort "$esfuerzo")

  local wt; wt="$(echo "$t" | jq -r '.worktree // "nuevo"')"
  if [ "$wt" = nuevo ]; then
    local base; base="$(base_de_tarea "$t" "$(plan_de "$estado")")"
    args+=(--worktree new-top-level --name "$(echo "$t" | jq -r .rama)" --base-branch "$base" --setup "$setup")
    if $dry; then args+=(--repo "<${t_repo:=$(echo "$t" | jq -r '.repo // "este repo"')}>"); else args+=(--repo "$(repo_selector "$(echo "$t" | jq -r '.repo // empty')")"); fi
  else
    local origen ruta; origen="${wt#de:}"
    if $dry; then ruta="<worktree de $origen>"; else
      ruta="$(ruta_worktree_de "$estado" "$origen")"
      [ -n "$ruta" ] && [ -d "$ruta" ] || die "no encuentro el worktree de $origen (¿se borró?)"
    fi
    args+=(--worktree "path:$ruta")
    # Commit de arranque: 'verificar' de esta tarea compara desde acá, no desde la base del
    # plan (si no, le atribuye los cambios de la tarea dueña del worktree).
    $dry || desde="$(git -C "$ruta" rev-parse HEAD)"
  fi

  if $dry; then printf '%q ' "${ORCA:-orca-ide}" "${args[@]}"; echo; return; fi
  [ -n "$ORCA" ] || ORCA="$(resolver_orca)"
  local out; out="$("$ORCA" "${args[@]}" --json 2>&1)" || {
    echo "$out" | jq . 2>/dev/null || echo "$out"
    die "worker-start no llegó a ready: NO relanzar; leer failedStage/residualResources (referencia recovery-and-cleanup de Orca)"; }
  local w; w="$(worker_de "$estado" "$k")"
  [ -n "${desde:-}" ] && estado_set "$estado" '.tareas[$k].desde = $c' --arg k "$k" --arg c "$desde"
  estado_set "$estado" '.tareas[$k].dispatch = $d | .tareas[$k].worktree = $w' --arg k "$k" \
    --arg d "$(echo "$w" | jq -r .dispatchId)" --arg w "$(echo "$w" | jq -r '.resource.worktreeId // "" | split("::")[1] // ""')"
  info "$k despachado: $(echo "$w" | jq -r '"\(.dispatchId) · \(.workerState) · \(.resource.worktreeId | split("::")[1])"')"
}

# --- estado -----------------------------------------------------------------------------
cmd_estado() {
  local estado="$1"; [ -f "$estado" ] || die "uso: estado <plan.estado.json>"
  local run tasks workers gates=() k tid
  run="$(estado_get "$estado" .run)"
  tasks="$(orca_json orchestration task-list --run "$run")"
  workers="$(orca_json orchestration worker-list --run "$run")"
  echo "Run $run — $(jq -r .objetivo "$(plan_de "$estado")")"
  printf '%-14s %-13s %-11s %-22s %-12s %s\n' CLAVE ROL TAREA COMPUERTA WORKER WORKTREE
  for k in $(jq -r '.tareas[].clave' "$(plan_de "$estado")"); do
    tid="$(estado_get "$estado" ".tareas[\"$k\"].task // empty")"
    local g="-"
    if [ -n "$(estado_get "$estado" ".tareas[\"$k\"].gate // empty")" ]; then
      g="$(orca_json orchestration gate-list --task "$tid" | jq -r '.gates[0] | if .status == "pending" then "PENDIENTE" else "→ \(.resolution)" end')"
    fi
    printf '%-14s %-13s %-11s %-22s %-12s %s\n' "$k" \
      "$(jq -r --arg k "$k" '.tareas[]|select(.clave==$k)|.rol' "$(plan_de "$estado")")" \
      "$(echo "$tasks" | jq -r --arg t "$tid" '.tasks[]|select(.id==$t)|.status')" "$g" \
      "$(echo "$workers" | jq -r --arg t "$tid" '[.workers[]|select(.taskId==$t)][0].workerState // "-"')" \
      "$(echo "$workers" | jq -r --arg t "$tid" '[.workers[]|select(.taskId==$t)][0].resource.worktreeId // "-" | split("::")[-1]')"
  done
}

# --- compuerta / cerrar -----------------------------------------------------------------
cmd_compuerta() {
  local estado="$1" k="$2" res="${3:-}"
  [ -f "$estado" ] && [ -n "$k" ] && [ -n "$res" ] || die "uso: compuerta <plan.estado.json> <clave> <resolución>"
  local gid; gid="$(estado_get "$estado" ".tareas[\"$k\"].gate // empty")"
  [ -n "$gid" ] || die "$k no tiene compuerta"
  jq -e --arg k "$k" --arg r "$res" '.tareas[]|select(.clave==$k)|.compuerta.opciones|index($r) != null' "$(plan_de "$estado")" >/dev/null \
    || die "'$res' no es una opción: $(jq -c --arg k "$k" '.tareas[]|select(.clave==$k)|.compuerta.opciones' "$(plan_de "$estado")")"
  exigir_run_ligado "$estado"
  warn "una compuerta la decide el owner: correr esto solo con su respuesta literal"
  orca_json orchestration gate-resolve --id "$gid" --resolution "$res" | jq -r '.gate | "compuerta \(.id) → \(.resolution)"'
}

cmd_cerrar() {
  local estado="$1" k="$2"
  [ -f "$estado" ] && [ -n "$k" ] || die "uso: cerrar <plan.estado.json> <clave>"
  local t; t="$(tarea_plan "$estado" "$k")"
  [ "$(echo "$t" | jq -r .rol)" = atlas ] || die "$k no es un paso de Atlas: las tareas despachadas se cierran solas con el worker_done"
  exigir_run_ligado "$estado"
  local tid; tid="$(estado_get "$estado" ".tareas[\"$k\"].task")"
  if [ -n "$(estado_get "$estado" ".tareas[\"$k\"].gate // empty")" ]; then
    local g aprueba; g="$(orca_json orchestration gate-list --task "$tid" | jq -c '.gates[0]')"
    aprueba="$(echo "$t" | jq -r '.compuerta.opciones[0]')"
    [ "$(echo "$g" | jq -r .status)" = resolved ] || die "la compuerta de $k sigue pendiente: no se cierra"
    [ "$(echo "$g" | jq -r .resolution)" = "$aprueba" ] \
      || die "la compuerta de $k se resolvió '$(echo "$g" | jq -r .resolution)', no '$aprueba': replanificar, no cerrar"
  fi
  local abiertas; abiertas="$(deps_abiertas "$estado" "$k")"
  [ -z "$abiertas" ] || die "$k depende de tareas sin cerrar: $(echo $abiertas)"
  local s; s="$(estado_tarea_orca "$estado" "$tid")"
  [ "$s" = ready ] || die "$k está en '$s', no en 'ready'"
  orca_json orchestration task-update --id "$tid" --status completed --run "$(estado_get "$estado" .run)" >/dev/null
  info "$k cerrada"
}

# --- verificar --------------------------------------------------------------------------
cmd_verificar() {
  local wt="" base="" rutas="" estado="" k="" otro_repo=false
  while [ $# -gt 0 ]; do
    case "$1" in
      --worktree) wt="$2"; shift ;;
      --base) base="$2"; shift ;;
      --rutas) rutas="$2"; shift ;;
      *) if [ -z "$estado" ]; then estado="$1"; else k="$1"; fi ;;
    esac; shift
  done
  if [ -n "$estado" ]; then
    [ -f "$estado" ] && [ -n "$k" ] || die "uso: verificar <plan.estado.json> <clave> | --worktree <ruta> [--base <ref>] [--rutas 'g1,g2']"
    local t; t="$(tarea_plan "$estado" "$k")"
    local w; w="${wt:-$(echo "$t" | jq -r '.worktree // "nuevo"')}"
    # El worktree puede ser el de otra tarea (de:<clave>), pero las rutas, la base y el repo son
    # los de ESTA tarea: con de:X se verificaban contra las rutas de X (falso positivo, 6-oct-2026).
    local origen="$k"; [[ "$w" == de:* ]] && origen="${w#de:}"
    wt="$(ruta_worktree_de "$estado" "$origen")"
    local to; to="$(tarea_plan "$estado" "$k")"
    base="${base:-$(estado_get "$estado" ".tareas[\"$k\"].desde // empty")}"
    base="${base:-$(base_de_tarea "$to" "$(plan_de "$estado")")}"
    rutas="${rutas:-$(echo "$to" | jq -r '(.rutas // []) | join(",")')}"
    [ -n "$(echo "$to" | jq -r '.repo // empty')" ] && otro_repo=true
  fi
  [ -n "$wt" ] && [ -d "$wt" ] || die "worktree inexistente: ${wt:-<vacío>}"
  base="${base:-origin/main}"
  local upstream=""; $otro_repo || upstream="$(ref_base_protegida)"

  local mb; mb="$(git -C "$wt" merge-base HEAD "$base")" || die "no hay merge-base entre HEAD y $base en $wt"
  local cambios
  cambios="$( { git -C "$wt" diff --name-only "$mb"; git -C "$wt" ls-files --others --exclude-standard; } | sort -u)"
  [ -n "$(git -C "$wt" status --porcelain)" ] && warn "hay cambios sin commitear en $wt (se cuentan igual)"
  [ -n "$cambios" ] || { info "sin cambios respecto de $base"; return 0; }

  local f fallos=0 de_base=() fuera=() toca_registro=false
  IFS=',' read -r -a globs <<<"$rutas"
  while IFS= read -r f; do
    [ -n "$REGISTRO" ] && [ "$f" = "$REGISTRO" ] && toca_registro=true
    [ -n "$upstream" ] && git -C "$REPO_ROOT" cat-file -e "$upstream:$f" 2>/dev/null && de_base+=("$f")
    if [ -n "$rutas" ]; then
      local g dentro=false
      for g in "${globs[@]}"; do g="${g# }"; [[ "$f" == $g ]] && { dentro=true; break; }; done
      $dentro || fuera+=("$f")
    fi
  done <<<"$cambios"

  echo "Cambios: $(echo "$cambios" | wc -l) archivo(s) en $wt respecto de $base"
  if [ "${#de_base[@]}" -gt 0 ]; then
    if $toca_registro; then
      warn "toca ${#de_base[@]} archivo(s) de la base ($upstream), con $REGISTRO en el mismo diff: revisar que cada uno tenga su entrada"
    else
      echo "[x] BASE PROTEGIDA: toca archivos de $upstream sin entrada en ${REGISTRO:-<registro no configurado>}:"; fallos=1
    fi
    printf '      %s\n' "${de_base[@]}"
  fi
  if [ "${#fuera[@]}" -gt 0 ]; then
    echo "[x] fuera de las rutas permitidas ($rutas):"; printf '      %s\n' "${fuera[@]}"; fallos=1
  fi
  local n i patron
  n="$(jq '(.recordatorios // []) | length' "$CONFIG_FILE")"
  for ((i = 0; i < n; i++)); do
    patron="$(jq -r ".recordatorios[$i].patron" "$CONFIG_FILE")"
    grep -qE "$patron" <<<"$cambios" && warn "$(jq -r ".recordatorios[$i].mensaje" "$CONFIG_FILE")"
  done
  [ -n "$upstream" ] && info "aproximación: un archivo de la base renombrado no se detecta como de la base"
  [ "$fallos" -eq 0 ] && echo "[ok] verificación sin bloqueos"
  return "$fallos"
}

# --- main -------------------------------------------------------------------------------
sub="${1:-}"; shift || true
case "$sub" in
  plan) cmd_plan "$@" ;;
  despachar) cmd_despachar "$@" ;;
  estado) cmd_estado "$@" ;;
  compuerta) cmd_compuerta "$@" ;;
  cerrar) cmd_cerrar "$@" ;;
  verificar) cmd_verificar "$@" ;;
  -h|--help|"") sed -n '2,27p' "$0" ;;
  *) die "subcomando desconocido: $sub (ver --help)" ;;
esac
