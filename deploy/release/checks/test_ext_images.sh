#!/usr/bin/env bash
# Variantes `-ext` de las imágenes publicadas (spec 057 T091, QA B1, FR-004d; research R27, R29).
#
# Eleia publica elea-guardian-{backend,frontend,engine} (deploy/release/publish-elea.sh) y el
# instalador baja esas imágenes. Con `ELEA_REDIRECT=1` el instalador elige las variantes `-ext`:
# la misma imagen base + la extensión `sentinel/`, bajo un tag propio que NUNCA mueve `latest`.
# Este check fija, SIN Docker (lectura estática y `publish-elea.sh` en modo de prueba):
#
#   · los tres Dockerfiles derivan de `ARG BASE_IMAGE` (no reconstruyen la base);
#   · backend: `sentinel/` sin `onboarding/` ni tests, seeds de `deploy/redirect-seeds/` en
#     `/opt/sentinel-ext/seeds`, vocabulario `cl100k_base` de tiktoken horneado con
#     `TIKTOKEN_CACHE_DIR` (sin él el conteo de tokens cae en silencio a `caracteres/4`), y ningún
#     cambio de usuario (la imagen publicada del backend corre como el usuario de la base);
#   · panel: la base de Eleia es el servidor de desarrollo de Vite (`frontend/Dockerfile`), así que
#     las páginas se suman con `VITE_PLUGIN_PAGES_DIR` (costura S3) y un build de verificación;
#   · motor: `redirect_*.py` en `/app/extensions/`, `config.yaml` fusionado con
#     `deploy/release/fragment_merge.py` y `pypdf` exacto (≥ 6.19.0, con `pypdf.Configuration`) con
#     `--require-hashes` desde `sentinel/docker/engine-requirements.txt`;
#   · el contexto de build de las tres es la RAÍZ del repo (necesitan `sentinel/` y
#     `deploy/release/fragment_merge.py`, fuera de los contextos `litellm` y `frontend` de las base);
#   · ningún secreto;
#   · `publish-elea.sh` en modo de prueba (`DRY_RUN=1`) lista las tres `-ext` DESPUÉS de las base,
#     con tag `<versión>-ext`, sin tag `latest` y sin invocar a Docker.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
fail() { echo "❌ $1"; exit 1; }
python3 -c 'import yaml' 2>/dev/null || fail "necesita python3 con PyYAML"

D="$REPO_ROOT/sentinel/docker"
for f in backend.Dockerfile frontend.Dockerfile engine.Dockerfile engine-requirements.txt; do
    [ -f "$D/$f" ] || fail "falta sentinel/docker/$f"
done
PUBLISH="$REPO_ROOT/deploy/release/publish-elea.sh"

python3 - "$REPO_ROOT" <<'PY' || fail "los Dockerfiles -ext no cumplen el contrato de T091 (ver arriba)"
import re, sys
from pathlib import Path

root = Path(sys.argv[1])
D = root / "sentinel" / "docker"
problemas = []
def mal(msg): problemas.append(msg)

def instrucciones(path):
    """Instrucciones del Dockerfile con las continuaciones `\\` unidas y sin comentarios."""
    out, acc = [], ""
    for linea in path.read_text(encoding="utf-8").splitlines():
        if linea.lstrip().startswith("#"):
            continue
        if linea.rstrip().endswith("\\"):
            acc += linea.rstrip()[:-1] + " "
            continue
        out.append((acc + linea).strip()); acc = ""
    return [i for i in out if i]

SECRETO = re.compile(r"(sk-[A-Za-z0-9]{8,}|AKIA[A-Z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|eyJ[A-Za-z0-9_-]{10,}|"
                     r"\b[A-Z0-9_]*(PASSWORD|SECRET|TOKEN|API_?KEY|PRIVATE_KEY)=\S+)")
ACTIVADORAS = ("GATEWAY_PLUGINS", "PLUGIN_PACKAGES", "ALEMBIC_EXTRA_VERSION_LOCATIONS", "REDIRECT_INTERNAL_KEY",
               "REDIRECT_SEED_FILES", "SENTINEL_ENTITY_REGION")

todas = {}
for nombre in ("backend", "frontend", "engine"):
    path = D / f"{nombre}.Dockerfile"
    ins = instrucciones(path)
    todas[nombre] = ins
    crudo = path.read_text(encoding="utf-8")
    # 1) deriva de la base: ARG BASE_IMAGE antes del primer FROM y un FROM ${BASE_IMAGE} como etapa final
    froms = [i for i in ins if i.upper().startswith("FROM ")]
    if not ins or not ins[0].startswith("ARG BASE_IMAGE"):
        mal(f"{nombre}: la primera instrucción debe ser `ARG BASE_IMAGE`")
    if not froms or not re.match(r"FROM \$\{BASE_IMAGE\}(\s|$)", froms[-1]):
        mal(f"{nombre}: la etapa final debe ser `FROM ${{BASE_IMAGE}}`")
    if re.search(r"\bARG BASE_IMAGE=", crudo):
        mal(f"{nombre}: BASE_IMAGE no lleva valor por defecto (la pasa publish-elea.sh)")
    # 2) el contexto de build es la raíz: la línea `docker build` documentada en la cabecera termina en ` .`
    unido = re.sub(r"\\\n#\s*", " ", crudo)          # une las líneas de comentario continuadas con `\`
    bloque = next((l for l in unido.splitlines() if "docker build" in l), "")
    if f"-f sentinel/docker/{nombre}.Dockerfile" not in bloque or not re.search(r"BASE_IMAGE=\S+", bloque) \
            or not re.search(r"\s\.$", bloque.strip()):
        mal(f"{nombre}: la cabecera debe documentar `docker build -f sentinel/docker/{nombre}.Dockerfile --build-arg BASE_IMAGE=… .` (contexto = raíz del repo)")
    # 3) sin secretos ni variables que ACTIVEN la extensión (eso lo hace el archivo de entorno de S12)
    for i in ins:
        if SECRETO.search(i):
            mal(f"{nombre}: parece traer un secreto: {i[:80]}")
        if re.match(r"(ENV|ARG) ", i) and any(v in i for v in ACTIVADORAS):
            mal(f"{nombre}: una imagen -ext no activa nada por sí sola, y `{i[:60]}` la activa/configura")

# ── backend ────────────────────────────────────────────────────────────────────────────────────
b = todas["backend"]
copias = [i.split()[1:] for i in b if i.startswith("COPY ")]
origenes = [c[0] for c in copias if not c[0].startswith("--")]
if any("onboarding" in o for o in origenes) or any("/tests" in o or o.rstrip("/") == "sentinel/tests" for o in origenes):
    mal("backend: no debe copiar `sentinel/onboarding` ni los tests")
paquetes = sorted(p.name for p in (root / "sentinel").iterdir()
                  if p.is_dir() and (p / "__init__.py").exists() and p.name not in ("tests", "onboarding"))
for p in paquetes:
    if not any(c[0] == f"sentinel/{p}" and c[1].rstrip("/") == f"/opt/sentinel-ext/sentinel/{p}" for c in copias):
        mal(f"backend: no copia el paquete sentinel/{p} a /opt/sentinel-ext/sentinel/{p}")
for extra in ("migrations", "engine"):     # las migraciones (S4) y el código del motor que importa `sentinel.redirect.authz`
    if not any(c[0] == f"sentinel/{extra}" and c[1].rstrip("/") == f"/opt/sentinel-ext/sentinel/{extra}" for c in copias):
        mal(f"backend: no copia sentinel/{extra}")
if not any(c[0].rstrip("/") == "sentinel/__init__.py" for c in copias):
    mal("backend: no copia sentinel/__init__.py")
if not any(c[0].rstrip("/") == "deploy/redirect-seeds" and c[1].rstrip("/") == "/opt/sentinel-ext/seeds" for c in copias):
    mal("backend: los seeds de deploy/redirect-seeds van horneados en /opt/sentinel-ext/seeds")
if "ENV PYTHONPATH=/opt/sentinel-ext" not in b:
    mal("backend: falta `ENV PYTHONPATH=/opt/sentinel-ext`")
tk = [i for i in b if i.startswith("ENV ") and "TIKTOKEN_CACHE_DIR=" in i]
if not tk:
    mal("backend: falta `ENV TIKTOKEN_CACHE_DIR=…` (sin él el conteo de tokens cae a caracteres/4, QA re-análisis L9)")
if not any("cl100k_base" in i and i.startswith("RUN ") and "tiktoken" in i for i in b):
    mal("backend: falta el RUN que hornea el vocabulario cl100k_base de tiktoken")
if any(i.startswith("USER ") for i in b):
    mal("backend: la imagen publicada del backend (backend/Dockerfile.standalone) no declara usuario; la -ext no lo cambia")
if any(re.search(r"chown\b[^|;&]*\bsentinel\b", i) for i in b):
    mal("backend: la base de Eleia no tiene el usuario `sentinel` de la imagen de producción de Sentinel")
base_be = (root / "backend" / "Dockerfile.standalone").read_text(encoding="utf-8")
if re.search(r"^\s*USER\s", base_be, flags=re.M):
    mal("backend: la base ya declara USER; revisar la regla 'sin cambio de usuario' de este check")

# ── panel ───────────────────────────────────────────────────────────────────────────────────────
f = todas["frontend"]
copias_f = [i.split()[1:] for i in f if i.startswith("COPY ")]
pages = root / "sentinel" / "frontend" / "pages"
carpetas = {"pages"}
for t in pages.glob("*.tsx"):
    carpetas |= set(re.findall(r'from "\.\./([a-z]+)/', t.read_text(encoding="utf-8")))
for c in sorted(carpetas):
    if not any(x[0].rstrip("/") == f"sentinel/frontend/{c}" and x[1].startswith("/app/sentinel/frontend/") for x in copias_f):
        mal(f"panel: no copia sentinel/frontend/{c} dentro de /app (la base sirve /app con Vite)")
if any("node_modules" in x[0] for x in copias_f):
    mal("panel: no copia node_modules")
if not any("__tests__" in i and i.startswith("RUN ") and "rm -rf" in i for i in f):
    mal("panel: los __tests__ de las páginas no entran a la imagen (RUN rm -rf …/__tests__)")
if "ENV VITE_PLUGIN_PAGES_DIR=/app/sentinel/frontend/pages" not in f:
    mal("panel: falta `ENV VITE_PLUGIN_PAGES_DIR=/app/sentinel/frontend/pages` (costura S3; la lee vite.config.ts y tailwind)")
if not any(re.search(r"ln -s\S* /app/src /app/frontend/src", i) for i in f):
    mal("panel: las páginas importan `../../../frontend/src/…`: hace falta el enlace /app/frontend/src → /app/src (mismo módulo, no una copia)")
marcadores = []
for i in f:
    if i.startswith("RUN ") and "vite build" in i:
        marcadores = re.findall(r'grep -q "([^"]+)"', i)
if len(marcadores) < 2:
    mal("panel: falta el build de verificación (`vite build` + `grep -q` de marcadores) para que una imagen sin las páginas no se publique")
fuentes = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in (root / "sentinel" / "frontend").rglob("*.tsx")
                    if "__tests__" not in p.parts and "node_modules" not in p.parts)
for m in marcadores:
    if m not in fuentes:
        mal(f"panel: el marcador «{m}» ya no existe en sentinel/frontend: el build de la imagen fallaría")
if any(i.startswith("CMD ") or i.startswith("ENTRYPOINT ") for i in f):
    mal("panel: no redefine CMD/ENTRYPOINT (sigue sirviendo como la base)")

# ── motor ───────────────────────────────────────────────────────────────────────────────────────
e = todas["engine"]
copias_e = [i.split()[1:] for i in e if i.startswith("COPY ")]
if not any(x[0] == "sentinel/engine/redirect_*.py" and x[1].rstrip("/") == "/app/extensions" for x in copias_e):
    mal("motor: falta `COPY sentinel/engine/redirect_*.py /app/extensions/`")
if not any(x[0] == "deploy/release/fragment_merge.py" for x in copias_e):
    mal("motor: falta copiar deploy/release/fragment_merge.py (contrato S11) para fusionar el fragmento")
if not any(x[0] == "sentinel/engine/profile-fragment.yaml" for x in copias_e):
    mal("motor: falta copiar sentinel/engine/profile-fragment.yaml")
if not any(i.startswith("RUN ") and "fragment_merge.py" in i and "/app/config.yaml" in i and "profile-fragment.yaml" in i for i in e):
    mal("motor: falta el RUN que fusiona el fragmento en /app/config.yaml con fragment_merge.py")
if not any(x[0] == "sentinel/docker/engine-requirements.txt" for x in copias_e):
    mal("motor: falta copiar sentinel/docker/engine-requirements.txt")
inst = [i for i in e if i.startswith("RUN ") and "pip" in i and "install" in i]
if not inst or not all("--require-hashes" in i and "engine-requirements.txt" in i for i in inst):
    mal("motor: pypdf se instala con `pip install --require-hashes -r …engine-requirements.txt`")
if any(i.startswith("ENTRYPOINT ") or i.startswith("CMD ") for i in e):
    mal("motor: no redefine ENTRYPOINT/CMD (los de la base)")

# ── engine-requirements.txt: versión exacta ≥ 6.19.0 con hashes, y la API de límites ─────────────
req = (D / "engine-requirements.txt").read_text(encoding="utf-8")
lineas = [l for l in req.replace("\\\n", " ").splitlines() if l.strip() and not l.lstrip().startswith("#")]
if len(lineas) != 1:
    mal("engine-requirements.txt: debe fijar solo pypdf (una línea)")
else:
    m = re.match(r"pypdf==(\d+)\.(\d+)\.(\d+)\s+(--hash=sha256:[0-9a-f]{64}\s*)+$", lineas[0].strip() + " ")
    if not m:
        mal("engine-requirements.txt: `pypdf==X.Y.Z --hash=sha256:…` con versión exacta y al menos un hash")
    elif tuple(map(int, m.groups()[:3])) < (6, 19, 0):
        mal("engine-requirements.txt: pypdf debe ser 6.19.0 o posterior (pypdf.Configuration y límites de descompresión, R29 3b)")

if problemas:
    print("\n".join("  · " + p for p in problemas), file=sys.stderr)
    sys.exit(1)
PY

# ── publish-elea.sh en modo de prueba ───────────────────────────────────────────────────────────
mkdir -p "$WORK/shim"
printf '#!/bin/sh\necho "docker invocado: $*" >> "%s/docker-llamado"; exit 97\n' "$WORK" > "$WORK/shim/docker"
chmod +x "$WORK/shim/docker"
OUT="$(PATH="$WORK/shim:$PATH" DRY_RUN=1 VERSION=2099-01-01 REGISTRY=registry.test/org "$PUBLISH" 2>&1)" \
    || fail "publish-elea.sh con DRY_RUN=1 falló: $OUT"
[ ! -e "$WORK/docker-llamado" ] || fail "DRY_RUN=1 invocó a docker: $(cat "$WORK/docker-llamado")"

builds="$(grep -E '^\+ docker build ' <<<"$OUT" || true)"
pushes="$(grep -E '^\+ docker push ' <<<"$OUT" || true)"
n() { grep -c -e "$1" <<<"$2" || true; }
for k in backend frontend engine; do
    ref="registry.test/org/elea-guardian-$k"
    [ "$(n "-t $ref:2099-01-01-ext " "$builds")" = 1 ] || fail "falta el build de $k con tag 2099-01-01-ext: $builds"
    grep -q "docker push -q $ref:2099-01-01-ext\$" <<<"$pushes" || fail "falta el push de $ref:2099-01-01-ext"
    grep -q "docker push -q $ref:2099-01-01\$" <<<"$pushes" || fail "el push de la base $ref:2099-01-01 desapareció"
    ext_line="$(grep -- "-t $ref:2099-01-01-ext " <<<"$builds")"
    # contexto = raíz del repo (último argumento de la línea de build), Dockerfile y BASE_IMAGE de la imagen base
    grep -q -- "-f $REPO_ROOT/sentinel/docker/$k.Dockerfile " <<<"$ext_line" || fail "$k-ext: Dockerfile equivocado: $ext_line"
    grep -q -- "--build-arg BASE_IMAGE=$ref:2099-01-01 " <<<"$ext_line" || fail "$k-ext: BASE_IMAGE debe ser la base recién publicada: $ext_line"
    [ "${ext_line##* }" = "$REPO_ROOT" ] || fail "$k-ext: el contexto de build debe ser la raíz del repo ($REPO_ROOT), no ${ext_line##* }"
    grep -q -- "-t $ref:latest" <<<"$ext_line" && fail "$k-ext: una variante -ext no se taggea latest"
done
# NINGÚN push de una variante -ext a latest, y los latest de la base siguen como hoy.
grep -E 'push -q .*-ext:latest|:latest-ext' <<<"$pushes" && fail "se pushea un latest de una -ext"
[ "$(n ':latest$' "$pushes")" = 6 ] || fail "los latest de las 6 imágenes base cambiaron (esperados 6 pushes :latest): $(grep ':latest$' <<<"$pushes")"
# Orden: todas las base antes que la primera -ext.
ult_base="$(grep -nE '^\+ docker build ' <<<"$OUT" | grep -v -- '-ext ' | tail -1 | cut -d: -f1)"
prim_ext="$(grep -nE '^\+ docker build .*-ext ' <<<"$OUT" | head -1 | cut -d: -f1)"
[ -n "$ult_base" ] && [ -n "$prim_ext" ] && [ "$ult_base" -lt "$prim_ext" ] || fail "las -ext van DESPUÉS de todas las base"
# ONLY sigue filtrando como siempre: sin -ext si no se piden.
solo="$(PATH="$WORK/shim:$PATH" DRY_RUN=1 VERSION=2099-01-01 ONLY="backend tabular" "$PUBLISH" 2>&1)" || fail "ONLY con DRY_RUN falló"
grep -q -- '-ext' <<<"$solo" && fail "ONLY=\"backend tabular\" no debe construir ninguna -ext"

echo "✅ variantes -ext OK: Dockerfiles derivados de BASE_IMAGE (backend sin onboarding/tests y con seeds y tiktoken, panel con VITE_PLUGIN_PAGES_DIR, motor con redirect_*.py, config fusionado y pypdf con hashes), contexto = raíz del repo, sin secretos; publish-elea.sh en DRY_RUN las lista tras las base con tag <versión>-ext y sin latest"
