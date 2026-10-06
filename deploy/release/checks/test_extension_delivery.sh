#!/usr/bin/env bash
# S9 y S11 (spec 057, T020): entrega de extensiones del motor y de fragmentos de perfil en el
# camino de los PERFILES DE CLIENTE (render_profile.sh, populate_volumes.sh, bundle.sh).
#
#   S9  EXTRA_ENGINE_EXTENSIONS (rutas)  → los archivos viajan al volumen de extensiones del
#       motor (populate_volumes.sh) y al paquete air-gapped (bundle.sh) junto a
#       litellm/extensions/*.py.
#   S11 PROFILE_FRAGMENTS (rutas YAML)   → render_profile.sh los fusiona al config.yaml
#       renderizado con deploy/release/fragment_merge.py: model_list y guardrails se agregan
#       AL FINAL; un model_name o guardrail_name repetido hace fallar el render.
#
# Sin las dos variables (sin definir, vacías o solo espacios) el resultado es IDÉNTICO por hash:
# config.yaml renderizado, árbol del volumen y árbol del paquete (SC-002).
#
# SIN Docker: `docker` es un doble en Python (ver abajo) que ejecuta de verdad los `sh -c` de los
# scripts contra directorios locales que hacen de volúmenes. Los scripts bajo prueba corren desde
# una COPIA del repo en un directorio temporal: nunca tocan deploy/clients/ del repo real.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "❌ $1"; exit 1; }
python3 -c 'import yaml' 2>/dev/null || fail "necesita python3 con PyYAML"
command -v envsubst >/dev/null || fail "necesita envsubst (gettext)"
command -v sha256sum >/dev/null || fail "necesita sha256sum"

# ── Repo de prueba: los scripts reales + lo que leen, con un perfil mínimo ─────────────────────
R="$WORK/repo"
mkdir -p "$R/deploy/release" "$R/deploy/docker" "$R/litellm" "$R/deploy/clients/test"
cp "$REPO_ROOT"/deploy/release/*.sh "$R/deploy/release/"
[ -f "$REPO_ROOT/deploy/release/fragment_merge.py" ] && cp "$REPO_ROOT/deploy/release/fragment_merge.py" "$R/deploy/release/"
cp "$REPO_ROOT/deploy/release/THIRD_PARTY_NOTICES.txt" "$R/deploy/release/"
cp -R "$REPO_ROOT/deploy/release/trust-kit" "$R/deploy/release/trust-kit"
cp -R "$REPO_ROOT/deploy/release/checks" "$R/deploy/release/checks"
cp -R "$REPO_ROOT/deploy/docker/." "$R/deploy/docker/"
cp -R "$REPO_ROOT/litellm/extensions" "$R/litellm/extensions"
cp "$REPO_ROOT/litellm/supervisor.py" "$R/litellm/supervisor.py"
find "$R" -name __pycache__ -prune -exec rm -rf {} +

P="$R/deploy/clients/test"
{
    echo "TENANT_SLUG=test"
    echo "BASE_DOMAIN=example.test"
    echo "CLIENT_MODEL=gpt-de-prueba"
    # Las imágenes que compose.prod.yml exige (la misma derivación que usa render_profile.sh).
    grep -oE '^[[:space:]]*image:[[:space:]]*"\$\{[A-Z_]+:\?' "$REPO_ROOT/deploy/docker/compose.prod.yml" \
        | grep -oE '\{[A-Z_]+' | tr -d '{' | sort -u | sed 's#$#=registry.test/img:1#'
} > "$P/client.env"
cat > "$P/branding.env" <<'ENV'
BRAND_NAME=Prueba
BRAND_TAGLINE=tagline
BRAND_SUPPORT=soporte@example.test
BRAND_COLOR_PRIMARY=#111111
BRAND_COLOR_BACKGROUND=#ffffff
BRAND_COLOR_PANEL=#eeeeee
ENV
cat > "$P/config.yaml.tmpl" <<'YAML'
model_list:
- model_name: base-model
  litellm_params:
    model: openai/${CLIENT_MODEL}
    api_key: os.environ/OPENAI_API_KEY
guardrails:
- guardrail_name: sentinel-guardian
  litellm_params:
    guardrail: extensions.sentinel_guardrail.SentinelGuardrail
    mode: [pre_call, post_call]
    default_on: true
YAML

# ── Doble de `docker` ──────────────────────────────────────────────────────────────────────────
# `volume create` y `image inspect/save` no hacen nada real. `run … sh -c <cmd>`: cada `-v
# origen:destino[:ro]` se traduce a un directorio local (un volumen nombrado vive en
# $FAKE_VOLS/<nombre>) y el comando se ejecuta con sh sustituyendo los destinos por esas rutas.
mkdir -p "$WORK/shim"
cat > "$WORK/shim/docker" <<'PY'
#!/usr/bin/env python3
import os, re, subprocess, sys
a = sys.argv[1:]
if a[:1] == ["volume"]:
    os.makedirs(os.path.join(os.environ["FAKE_VOLS"], a[2]), exist_ok=True)
elif a[:2] == ["image", "inspect"]:
    print("amd64" if "Architecture" in " ".join(a) else "sha256:" + "0" * 64)
elif a[:1] == ["save"]:
    open(a[a.index("-o") + 1], "wb").close()
elif a[:1] == ["run"]:
    maps, i = {}, 1
    while i < len(a):
        if a[i] == "-v":
            src, dst = a[i + 1].split(":")[:2]
            if not src.startswith("/"):
                src = os.path.join(os.environ["FAKE_VOLS"], src)
                os.makedirs(src, exist_ok=True)
            maps[dst] = src
            i += 2
        elif a[i] == "--entrypoint":
            i += 2
        elif a[i].startswith("-"):
            i += 1
        else:
            break
    cmd = a[a.index("-c", i) + 1]
    for dst, src in maps.items():
        cmd = re.sub(r"(?<![\w./-])" + re.escape(dst) + r"(?![\w.-])", src, cmd)
    sys.exit(subprocess.run(["sh", "-c", cmd]).returncode)
else:
    sys.exit("docker simulado: no soporta " + " ".join(a))
PY
printf '#!/bin/sh\nexit 0\n' > "$WORK/shim/chown"
chmod +x "$WORK/shim/docker" "$WORK/shim/chown"
export PATH="$WORK/shim:$PATH"

tree_hash() { # directorio → "modo hash ruta" por archivo, ordenado
    (cd "$1" && find . -type f -printf '%m %p\n' | sort -k2 | while read -r m p; do
        echo "$m $(sha256sum "$p" | cut -d' ' -f1) $p"; done)
}
sha() { sha256sum "$1" | cut -d' ' -f1; }

render() { # → renderiza el perfil de prueba (las variables S9/S11 las pone el llamador)
    "$R/deploy/release/render_profile.sh" test >"$WORK/render.out" 2>&1
}
populate() { # <nombre-de-corrida> → árbol de volúmenes en $WORK/vols-<nombre>
    export FAKE_VOLS="$WORK/vols-$1"; rm -rf "$FAKE_VOLS"; mkdir -p "$FAKE_VOLS"
    : > "$WORK/test.lic"
    COMPOSE_PROJECT=t "$R/deploy/release/populate_volumes.sh" test "$WORK/test.lic" >"$WORK/populate.out" 2>&1
}
bundle() { # <nombre-de-corrida> → paquete en $WORK/bundle-<nombre> (sin MANIFEST: lleva fecha)
    export FAKE_VOLS="$WORK/vols-unused"; mkdir -p "$FAKE_VOLS"
    BACKEND_IMAGE=r/b:1 FRONTEND_IMAGE=r/f:1 SENTINEL_ENGINE_IMAGE=r/e:1 DOCS_IMAGE=r/d:1 \
    NLP_ANALYZER_IMAGE=r/n:1 \
        "$R/deploy/release/bundle.sh" test "$WORK/bundle-$1" >"$WORK/bundle.out" 2>&1 || return 1
    rm -f "$WORK/bundle-$1/MANIFEST" "$WORK/bundle-$1.tar.gz"
}

# Archivos de extensión de prueba (nombres que no chocan con los del motor).
mkdir -p "$WORK/ext/uno" "$WORK/ext/dos"
echo "# extension uno" > "$WORK/ext/uno/redirect_uno.py"
echo "# extension dos" > "$WORK/ext/dos/redirect_dos.py"
cat > "$WORK/frag-a.yaml" <<'YAML'
model_list:
  - model_name: frag-a-model
    litellm_params: {model: "openai/*"}
guardrails:
  - guardrail_name: frag-a-guard
    litellm_params: {guardrail: extensions.redirect_uno.Uno, mode: pre_call, default_on: true}
YAML
cat > "$WORK/frag-b.yaml" <<'YAML'
guardrails:
  - guardrail_name: frag-b-guard
    litellm_params: {guardrail: extensions.redirect_dos.Dos, mode: pre_call, default_on: true}
YAML

unset EXTRA_ENGINE_EXTENSIONS PROFILE_FRAGMENTS

# ═══ S11 · render_profile.sh ════════════════════════════════════════════════════════════════════
# (1) Sin variable ⇒ el config.yaml es la sustitución del template y nada más (hash).
render || fail "render sin PROFILE_FRAGMENTS falló: $(cat "$WORK/render.out")"
CFG="$P/rendered/config.yaml"
VARS="$(grep -oE '^[A-Za-z_][A-Za-z0-9_]*=' "$P/client.env" | sed 's/=$//;s/^/${/;s/$/}/' | tr '\n' ' ')"
(set -a; . "$P/client.env"; set +a; envsubst "$VARS" < "$P/config.yaml.tmpl") > "$WORK/esperado.yaml"
[ "$(sha "$CFG")" = "$(sha "$WORK/esperado.yaml")" ] \
    || fail "S11: sin PROFILE_FRAGMENTS el config.yaml renderizado no es la sustitución del template"
H_BASE="$(sha "$CFG")"
# (2) Vacía o solo espacios ⇒ idéntico por hash.
PROFILE_FRAGMENTS="" render
[ "$(sha "$CFG")" = "$H_BASE" ] || fail "S11: PROFILE_FRAGMENTS vacía cambió el config.yaml"
PROFILE_FRAGMENTS="   " render
[ "$(sha "$CFG")" = "$H_BASE" ] || fail "S11: PROFILE_FRAGMENTS con solo espacios cambió el config.yaml"

# (3) Con fragmentos: los del fragmento quedan AL FINAL, en el orden de la variable; el orden
#     efectivo de guardrails es sentinel-guardian ANTES que el del fragmento (QA A3: el guard de
#     la extensión ve el masking_report del guardrail de la base).
PROFILE_FRAGMENTS="$WORK/frag-a.yaml $WORK/frag-b.yaml" render \
    || fail "S11: el render con fragmentos válidos falló: $(cat "$WORK/render.out")"
python3 - "$CFG" <<'PY' || fail "S11: orden o contenido del config fusionado inesperado"
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
models = [m["model_name"] for m in c["model_list"]]
guards = [g["guardrail_name"] for g in c["guardrails"]]
assert models == ["base-model", "frag-a-model"], models
assert guards == ["sentinel-guardian", "frag-a-guard", "frag-b-guard"], guards
assert c["model_list"][0]["litellm_params"]["model"] == "openai/gpt-de-prueba"   # el template sigue templado
PY
# Una ruta relativa se resuelve contra la raíz del repo, no contra el directorio de trabajo.
mkdir -p "$R/frag" && cp "$WORK/frag-b.yaml" "$R/frag/b.yaml"
(cd / && PROFILE_FRAGMENTS="frag/b.yaml" "$R/deploy/release/render_profile.sh" test >/dev/null 2>&1) \
    || fail "S11: una ruta relativa de PROFILE_FRAGMENTS no se resolvió contra la raíz del repo"
grep -q "frag-b-guard" "$CFG" || fail "S11: el fragmento relativo no quedó en el config"
# El fragmento real de la extensión (si ya está) también fusiona limpio.
if [ -f "$REPO_ROOT/sentinel/engine/profile-fragment.yaml" ]; then
    PROFILE_FRAGMENTS="$REPO_ROOT/sentinel/engine/profile-fragment.yaml" render \
        || fail "S11: el fragmento real de la extensión no fusiona: $(cat "$WORK/render.out")"
    python3 - "$CFG" <<'PY' || fail "S11: el fragmento real no dejó redirect-guard después de sentinel-guardian"
import sys, yaml
g = [x["guardrail_name"] for x in yaml.safe_load(open(sys.argv[1], encoding="utf-8"))["guardrails"]]
assert g == ["sentinel-guardian", "redirect-guard"], g
PY
fi

# (4) Duplicados ⇒ el render FALLA y no deja un config a medias.
cat > "$WORK/dup-model.yaml" <<'YAML'
model_list:
  - model_name: base-model
    litellm_params: {model: "openai/*"}
YAML
cat > "$WORK/dup-guard.yaml" <<'YAML'
guardrails:
  - guardrail_name: sentinel-guardian
    litellm_params: {guardrail: x.Y, mode: pre_call}
YAML
for d in dup-model dup-guard; do
    if PROFILE_FRAGMENTS="$WORK/$d.yaml" render; then fail "S11: $d (duplicado contra el perfil) no hizo fallar el render"; fi
    grep -q "duplicado" "$WORK/render.out" || fail "S11: $d falló sin explicar el duplicado: $(cat "$WORK/render.out")"
    [ ! -f "$CFG" ] || fail "S11: tras un render fallido quedó un config.yaml (se podría desplegar sin la extensión)"
done
if PROFILE_FRAGMENTS="$WORK/frag-a.yaml $WORK/frag-a.yaml" render; then fail "S11: el mismo fragmento dos veces (duplicado entre fragmentos) no falló"; fi
# Fragmento inexistente o con claves ajenas ⇒ falla.
if PROFILE_FRAGMENTS="$WORK/no-existe.yaml" render; then fail "S11: un fragmento inexistente no hizo fallar el render"; fi
printf 'general_settings: {x: 1}\n' > "$WORK/frag-mala.yaml"
if PROFILE_FRAGMENTS="$WORK/frag-mala.yaml" render; then fail "S11: un fragmento con claves ajenas (general_settings) no hizo fallar el render"; fi

# (5) Paridad de contrato con el fusionador de la extensión: mismo resultado, byte a byte.
if [ -f "$REPO_ROOT/sentinel/engine/fragment_merge.py" ]; then
    render
    cp "$CFG" "$WORK/par-base.yaml"; cp "$CFG" "$WORK/par-ext.yaml"
    python3 "$R/deploy/release/fragment_merge.py" "$WORK/par-base.yaml" "$WORK/frag-a.yaml" "$WORK/frag-b.yaml" >/dev/null 2>&1
    python3 "$REPO_ROOT/sentinel/engine/fragment_merge.py" "$WORK/par-ext.yaml" "$WORK/frag-a.yaml" "$WORK/frag-b.yaml" >/dev/null 2>&1
    [ "$(sha "$WORK/par-base.yaml")" = "$(sha "$WORK/par-ext.yaml")" ] \
        || fail "S11: el fusionador de la base y el de la extensión no producen el mismo resultado"
fi

# ═══ S9 · populate_volumes.sh ═══════════════════════════════════════════════════════════════════
render
populate base || fail "populate_volumes sin EXTRA_ENGINE_EXTENSIONS falló: $(cat "$WORK/populate.out")"
V_BASE="$(tree_hash "$WORK/vols-base")"
# La base de comparación se arma sin mirar el script: extensiones = litellm/extensions/*.py.
for f in "$REPO_ROOT"/litellm/extensions/*.py; do
    grep -q " ./t_litellm_config/extensions/$(basename "$f")\$" <<<"$V_BASE" \
        || fail "S9: falta $(basename "$f") en el volumen de extensiones"
    grep -q "^[0-9]* $(sha "$f") ./t_litellm_config/extensions/$(basename "$f")\$" <<<"$V_BASE" \
        || fail "S9: $(basename "$f") en el volumen no es idéntico a la fuente"
done
[ "$(grep -c ' ./t_litellm_config/extensions/' <<<"$V_BASE")" = "$(ls "$REPO_ROOT"/litellm/extensions/*.py | wc -l)" ] \
    || fail "S9: el volumen de extensiones trae archivos que no están en litellm/extensions"
for v in "" "   "; do
    EXTRA_ENGINE_EXTENSIONS="$v" populate vacia
    [ "$(tree_hash "$WORK/vols-vacia")" = "$V_BASE" ] || fail "S9: EXTRA_ENGINE_EXTENSIONS='$v' cambió el volumen"
done

# Con extensiones: se SUMAN junto a las de la base (en el mismo directorio) sin alterar nada más.
EXTRA_ENGINE_EXTENSIONS="$WORK/ext/uno/redirect_uno.py $WORK/ext/dos/redirect_dos.py" populate ext \
    || fail "populate_volumes con EXTRA_ENGINE_EXTENSIONS falló: $(cat "$WORK/populate.out")"
V_EXT="$(tree_hash "$WORK/vols-ext")"
diff <(echo "$V_EXT") <(echo "$V_BASE") | grep -E '^[<>]' | sed 's/^\([<>]\) .* \(\.\/.*\)$/\1 \2/' > "$WORK/dif.txt" || true
printf '< ./t_litellm_config/extensions/redirect_dos.py\n< ./t_litellm_config/extensions/redirect_uno.py\n' | sort > "$WORK/dif-esperada.txt"
sort "$WORK/dif.txt" | diff - "$WORK/dif-esperada.txt" >/dev/null \
    || fail "S9: el volumen con extensiones difiere de la base en algo más que los dos archivos: $(cat "$WORK/dif.txt")"
grep -q "^644 $(sha "$WORK/ext/uno/redirect_uno.py") " <<<"$V_EXT" || fail "S9: redirect_uno.py no quedó 644 e idéntico"
# Una extensión que pisaría un archivo del motor, o que no existe ⇒ error (nada se pisa en silencio).
if EXTRA_ENGINE_EXTENSIONS="$WORK/no-existe.py" populate malo; then fail "S9: una extensión inexistente no hizo fallar populate_volumes"; fi
echo "# pisa" > "$WORK/ext/uno/sentinel_guardrail.py"
if EXTRA_ENGINE_EXTENSIONS="$WORK/ext/uno/sentinel_guardrail.py" populate malo; then
    fail "S9: una extensión con el nombre de un archivo del motor (sentinel_guardrail.py) no hizo fallar populate_volumes"; fi
rm -f "$WORK/ext/uno/sentinel_guardrail.py"

# ═══ S9 · bundle.sh ═════════════════════════════════════════════════════════════════════════════
bundle base || fail "bundle sin EXTRA_ENGINE_EXTENSIONS falló: $(cat "$WORK/bundle.out")"
B_BASE="$(tree_hash "$WORK/bundle-base")"
grep -q ' ./engine-extensions/sentinel_guardrail.py$' <<<"$B_BASE" || fail "S9: el paquete no trae las extensiones del motor"
[ "$(grep -c ' ./engine-extensions/' <<<"$B_BASE")" = "$(ls "$REPO_ROOT"/litellm/extensions/*.py | wc -l)" ] \
    || fail "S9: engine-extensions del paquete no es litellm/extensions/*.py"
for v in "" "   "; do
    EXTRA_ENGINE_EXTENSIONS="$v" bundle vacia
    [ "$(tree_hash "$WORK/bundle-vacia")" = "$B_BASE" ] || fail "S9: EXTRA_ENGINE_EXTENSIONS='$v' cambió el paquete"
done
EXTRA_ENGINE_EXTENSIONS="$WORK/ext/uno/redirect_uno.py $WORK/ext/dos/redirect_dos.py" bundle ext \
    || fail "bundle con EXTRA_ENGINE_EXTENSIONS falló: $(cat "$WORK/bundle.out")"
B_EXT="$(tree_hash "$WORK/bundle-ext")"
diff <(echo "$B_EXT") <(echo "$B_BASE") | grep -E '^[<>]' | sed 's/^\([<>]\) .* \(\.\/.*\)$/\1 \2/' | sort > "$WORK/dif.txt" || true
printf '< ./engine-extensions/redirect_dos.py\n< ./engine-extensions/redirect_uno.py\n' | sort | diff - "$WORK/dif.txt" >/dev/null \
    || fail "S9: el paquete con extensiones difiere de la base en algo más que los dos archivos: $(cat "$WORK/dif.txt")"
# El instalador del paquete copia `/ext/*.py` ⇒ las extras llegan al volumen de la sede.
grep -q 'cp /ext/\*.py /vol/extensions/' "$WORK/bundle-ext/install.sh" || fail "S9: el install.sh del paquete ya no copia engine-extensions/*.py completo"
# Con perfil + fragmento + extensión, el paquete lleva el config fusionado y el .py del guard.
EXTRA_ENGINE_EXTENSIONS="$WORK/ext/uno/redirect_uno.py" PROFILE_FRAGMENTS="$WORK/frag-a.yaml" bundle ambos \
    || fail "bundle con extensión + fragmento falló: $(cat "$WORK/bundle.out")"
grep -q 'frag-a-guard' "$WORK/bundle-ambos/profile/config.yaml" || fail "S11: el paquete no lleva el config fusionado"
[ -f "$WORK/bundle-ambos/engine-extensions/redirect_uno.py" ] || fail "S9: el paquete no lleva la extensión"
if EXTRA_ENGINE_EXTENSIONS="$WORK/no-existe.py" bundle malo; then fail "S9: una extensión inexistente no hizo fallar bundle.sh"; fi

echo "✅ entrega de extensiones (S9) y fragmentos de perfil (S11) OK: sin variables = config, volumen y paquete idénticos por hash; con ellas, extras copiadas, fragmentos fusionados al final (sentinel-guardian antes que el guard) y duplicados/inexistentes/pisadas fallan"
