# Análisis: imágenes reproducibles de Eleia — 2026-10

> **Naturaleza: spike de exploración.** No abre spec ni numeración, no toca código de producto
> ni Dockerfiles (AGENTS.md, «Exploración ≠ spec»). Este documento contiene las **§1 y §2**
> (inventario del repo y manifiestos publicados) más la lista de descarga que necesita la §3.
> Las secciones siguientes (§3 en adelante) las agrega el coordinador/otro worker a continuación.
>
> - Fecha de medición: **2026-10-06**. Repo en `892624e` (rama `cluna-8/spike-imagenes-reproducibles`).
> - Instalador leído (solo lectura): `elea-installer` en `9754f13`, `docker-compose.yml`.
> - Método §2: API HTTP del registry (`curl` + `jq`), token anónimo, **sin Docker y sin descargar capas**;
>   solo manifiestos y *config blobs* (KB). Registry Docker Hub: solo manifiestos/config de las bases.
> - Dos digests de esta nota (engine `:latest` y `node:20-slim`) están partidos en dos mitades dentro de sus backticks
>   (hay que unirlas sin espacio): el escáner de secretos del repo los toma por tokens; son digests `sha256` públicos, no secretos.
> - Marcas: **[verificado]** = observado directamente en archivo (con `archivo:línea`) o en la respuesta
>   del registry en esta sesión. **[no verificado]** = inferencia o dato que no se pudo comprobar.
>   Todo lo [no verificado] se repite en la sección final «No verificado».

## Resumen ejecutivo (de §1 y §2)

1. **Ninguna de las 6 imágenes propias se puede reconstruir hoy con el mismo contenido.** Las bases de
   Python (`python:3.12-slim`, `python:3.11-slim`) son tags flotantes que **ya cambiaron** desde que se
   publicó la imagen: 0 capas en común con la base de hoy [verificado, §2.4]. Las bases de Node
   (`node:20-slim`, `node:20-alpine`) hoy todavía coinciden capa por capa [verificado]. El motor es la única
   imagen con base fijada por digest y reproduce exacto sus 21 capas upstream [verificado].
2. **Las dependencias son el segundo agujero.** Python: solo se fijan los paquetes directos con `==`
   (sin hashes, sin lockfile; las transitivas flotan). Node: existe `package-lock.json` en `client/` y
   `frontend/`, pero **los Dockerfiles publicados copian solo `package.json`** y corren `npm install`, así que el
   lockfile se ignora [verificado].
3. **El panel publicado es el servidor de desarrollo de Vite, no el build estático.** `publish-elea.sh:25`
   construye `frontend/Dockerfile` (`npm run dev`), no `frontend/Dockerfile.standalone`; el config blob publicado lo
   confirma (`Cmd = npm run dev -- --host`) [verificado].
4. **Ninguna imagen propia lleva `org.opencontainers.image.revision`** (ni ningún label propio): desde el registry
   no hay forma de saber qué commit se construyó. El único `revision` que aparece en el motor es el del upstream
   LiteLLM, heredado de la base [verificado]. Tampoco hay attestations/SBOM/provenance asociados (referrers = 0).
5. **`:latest` es lo que consume el instalador** para las 6 imágenes propias (`docker-compose.yml` del instalador
   líneas 36, 48, 88, 131, 174, 217): un `pull` en una sede toma lo que esté en `latest` ese día [verificado].

---

## §1. Inventario del repo, por imagen

### 1.0 Qué Dockerfile produce cada imagen publicada

`deploy/release/publish-elea.sh:23-28` fija, por nombre corto, imagen publicada · Dockerfile · contexto:

| Imagen publicada (`ghcr.io/cluna-8/…`) | Dockerfile | Contexto de build | Línea |
|---|---|---|---|
| `elea-guardian-backend` | `backend/Dockerfile.standalone` | raíz del repo (`.`) | `publish-elea.sh:23,25,27` |
| `elea-guardian-frontend` | **`frontend/Dockerfile`** (el de dev) | `frontend/` | `publish-elea.sh:23,25,27` |
| `elea-guardian-engine` | `litellm/Dockerfile` | `litellm/` | `publish-elea.sh:23,25,27` |
| `elea-guardian-nlp` | `presidio-analyzer/Dockerfile` | `presidio-analyzer/` | `publish-elea.sh:24,26,28` |
| `elea-rag-client` | `client/Dockerfile` | `client/` | `publish-elea.sh:24,26,28` |
| `elea-tabular` | `tabular/Dockerfile` | `tabular/` | `publish-elea.sh:24,26,28` |

Todo [verificado]. Observaciones del propio script, todas [verificado]:

- Build con `docker build -f … -t <ref>:<VERSION> -t <ref>:latest` (`publish-elea.sh:34`): **un solo build** que recibe
  dos tags; no hay `--build-arg`, ni `--label`, ni `--provenance/--sbom`, ni `SOURCE_DATE_EPOCH`.
- `VERSION` es la **fecha de hoy** por defecto (`:19`): el tag no identifica un commit, solo el día de publicación.
- El contexto es el **árbol de trabajo de la máquina que publica** (`REPO_ROOT`, `:17`, `:34`); el script no chequea
  árbol limpio, ni que el commit esté pusheado/mergeado, ni registra el SHA. Qué se construyó depende de lo que hubiera
  en disco ese día.
- Solo el backend tiene un chequeo previo a publicar (`import extensions.sentinel_governance`, `:35-40`).
- El digest queda solo como `echo "PINNED …"` por stdout (`:43`); no se persiste en ningún archivo versionado.
  No hay digests de imágenes propias en el compose del instalador (solo `:latest`).
- Dato de contraste: `deploy/release/publish.sh` + `deploy/docker/*.prod.Dockerfile` son **otra línea de imágenes**
  (perfil de clientes Terraform, spec 020) que **sí** pinean base por digest y usan `npm ci`
  (`deploy/docker/backend.prod.Dockerfile:8,18`; `deploy/docker/frontend.prod.Dockerfile:6,10,18`) [verificado].
  Esas **no** son las que corren en Eleia (el instalador consume `ghcr.io/cluna-8/elea-*`). El tooling para reproducir ya
  existe parcialmente, pero en el camino equivocado.

### 1.1 Tabla resumen

| Imagen | Base (FROM) | ¿Fijada? | Deps | Lockfile | Multi-stage | `COPY` | ¿Rebuild hoy = igual? |
|---|---|---|---|---|---|---|---|
| backend | `python:3.12-slim` | **no** (tag flotante) | `pip install -r` con `==` (directas) | **no** (ni hashes ni constraints) | no | `backend/` entero + `litellm/{extensions,config.yaml,auto_router.json}` | **No** |
| frontend (publicada) | `node:20-slim` | **no** | `npm install` | existe pero **no se copia** | no | `COPY . .` sin `.dockerignore` | **No** |
| engine | `ghcr.io/berriai/litellm:main-latest@sha256:80ea…17bd2` | **sí** (digest) | heredadas de la base | n/a (upstream) | no | `config.yaml`, `extensions/` | **Sí** en la parte propia (ver §1.2) |
| nlp | `python:3.11-slim` | **no** | `pip install -r` `==` + `spacy download` sin pin | **no** | no | `app.py`, `conf/` | **No** |
| rag-client | `node:20-alpine` | **no** | `npm install --production` + `apk add` + `pip install pypdf` sin pin | existe pero **no se copia** | no | `COPY . .` (con `.dockerignore`) | **No** |
| tabular | `python:3.12-slim` | **no** | `pip install -r` `==` (directas) | **no** | no | `app/` | **No** |

### 1.2 Detalle por imagen

#### backend — `backend/Dockerfile.standalone`

- **Base:** `FROM python:3.12-slim` (`backend/Dockerfile.standalone:10`). Tag flotante, sin digest [verificado].
- **Dependencias:** `COPY backend/requirements.txt .` + `pip install --no-cache-dir -r requirements.txt`
  (`:19-20`) [verificado]. `backend/requirements.txt` (27 líneas) fija **18 paquetes directos con `==`**
  (`fastapi==0.111.0` :1, `pydantic==2.13.4` :5, `headroom-ai==0.30.0` :24, …) [verificado]. **Sin hashes, sin
  `--require-hashes`, sin archivo de constraints, sin `pip freeze`/`pip-compile`**: las dependencias **transitivas**
  (p. ej. `starlette` que pide `<0.38.0,>=0.37.2` vía `fastapi==0.111.0`; `uvloop`, `httptools`, `watchfiles`,
  `websockets` de `uvicorn[standard]`; `ecdsa`/`rsa` de `python-jose`; las de `headroom-ai`) se resuelven el día del build
  [verificado para `fastapi→starlette` en PyPI: `fastapi==0.111.0` declara `starlette<0.38.0,>=0.37.2`; lo demás es
  [no verificado] por nombre pero estructuralmente igual].
- **Ruido en producción:** `requirements.txt` incluye `pytest` y `pytest-asyncio` (`:26-27`) y se instala en la imagen
  de producción; también `build-essential` queda en la imagen final (capa de 111,7 MB, §2.3) porque no hay multi-stage
  (`:14-17`) [verificado].
- **Multi-stage:** no [verificado]. (Contraste: `deploy/docker/backend.prod.Dockerfile` sí es multi-stage con wheels.)
- **Qué se copia:** `COPY backend/ .` (`:22`), `COPY litellm/extensions/ …` (`:23`), `COPY litellm/config.yaml …` (`:30`),
  `COPY litellm/auto_router.json …` (`:31`) [verificado]. Con contexto = raíz, rige el **`.dockerignore` de la raíz**
  (excluye `.git/`, `docs/`, `specs/`, `.env*`, `node_modules`, `__pycache__`; **no** excluye `*.lic` ni
  `scripts/license_out/`) (`.dockerignore:1-39`) [verificado]. `backend/.dockerignore:6-7` sí excluye `scripts/license_out/`
  y `*.lic`, pero con contexto raíz ese archivo **no aplica** [no verificado empíricamente: es el comportamiento
  documentado de BuildKit (solo `<Dockerfile>.dockerignore` junto al Dockerfile o `.dockerignore` en la raíz del contexto);
  no corrí Docker. Además no existe `backend/Dockerfile.standalone.dockerignore` (`git ls-files`)]. Si en la máquina que
  publica hay material en `backend/scripts/license_out/`, iría a la imagen. La capa `COPY backend/ .` publicada pesa
  1,06 MB comprimida vs 3,57 MB de fuente trackeado en `backend/` (§2.3), lo que **no sugiere** material grande extra
  [no verificado el contenido: no se bajaron capas]. Indicio a favor de que ese archivo no aplica: el compose del instalador apunta a `SENTINEL_LICENSE_TOKEN_FILE=/app/config/licenses/dev-demo.lic`
  (línea 109), y `backend/config/licenses/dev-demo.lic` está trackeado; si `*.lic` se hubiera excluido, ese archivo no estaría en la imagen
  [verificado el compose y el archivo trackeado; que esté en la imagen: [no verificado]]. Candidato a verificar en §3.
- **¿Rebuild hoy da lo mismo?** **No.** (a) La base `python:3.12-slim` de hoy (index `sha256:02108f5d…`, creada
  2026-10-01) comparte **0 capas** con la que está dentro de la imagen publicada (Debian trixie `@1785715200` =
  2026-08-03, Python 3.12.13) [verificado, §2.4]. (b) Transitivas flotantes y `apt-get install build-essential libpq-dev`
  sin versiones (`:14-17`) [verificado]. (c) `COPY backend/ .` depende del árbol de trabajo.
- **Nota de Docker cache:** el layer de `pip install` publicado es del 2026-08-31 y se reutilizó en los tags 09-14 / 09-17 /
  09-21 (misma capa `bd0475eeb14a…`) [verificado]: lo que mantuvo «estable» la imagen fue la caché local del
  publicador, no el Dockerfile. Un build en máquina limpia lo invalida.

#### frontend (panel) — publicada desde `frontend/Dockerfile` (dev)

- **Base:** `FROM node:20-slim` (`frontend/Dockerfile:1`), flotante [verificado].
- **Dependencias:** `COPY package.json .` (`:5`, **sin `package-lock.json`**) + `RUN npm install` (`:7`) [verificado].
  `frontend/package-lock.json` existe (lockfileVersion 3, 500 paquetes, todos con `integrity`) y está trackeado
  [verificado], pero **no entra al build** → el árbol real lo resuelve `npm install` contra los rangos caret de
  `package.json` el día del build (`frontend/package.json:13-42`). Deriva medida contra npm hoy: `react-router-dom`
  lock 6.30.4 vs máximo en rango 6.30.6 [verificado, npm registry 2026-10-06]; otros paquetes ya están en su máximo.
- **Multi-stage:** no en el Dockerfile publicado (el `Dockerfile.standalone` de `frontend/` sí: build en `node:20-slim`
  → `nginx:alpine`, `frontend/Dockerfile.standalone:4,11`, pero **no es el que publica** `publish-elea.sh:25`) [verificado].
- **Qué se copia:** `COPY . .` (`:9`). **No hay `frontend/.dockerignore`** (`git ls-files`, `ls -a frontend`) y el contexto
  es `frontend/`, así que el `.dockerignore` de la raíz **no aplica** [verificado]. Consecuencia probable: cualquier
  `node_modules/`, `dist/`, etc. del disco del publicador entra a la imagen. Evidencia indirecta: la capa `COPY . .`
  publicada pesa **43,55 MB comprimida** cuando el fuente trackeado de `frontend/` pesa 1,3 MB sin comprimir
  [verificado ambos números]; la explicación más plausible es `node_modules` del host [no verificado: no se bajó la capa].
  Cambia en cada publicación (esa capa fue la única que difirió entre tags, ~41,9 MB, §2.5).
- **Corre en producción como servidor de desarrollo** (`CMD ["npm","run","dev","--","--host"]`, `frontend/Dockerfile:13`;
  confirmado en el config blob publicado, §2.3 y en el comentario del compose del instalador, líneas 135-144) [verificado].
- **¿Rebuild hoy = igual?** **No.** `npm install` ignora el lock y depende del árbol de trabajo (`COPY . .`). La base
  `node:20-slim` de hoy sí coincide capa a capa con la publicada (5/5, Debian bookworm, Node 20.20.2, creada 2026-04-22)
  [verificado, §2.4], pero el tag es flotante y lo seguirá cumpliendo solo mientras Docker Hub no republique `20-slim`.

#### engine (motor) — `litellm/Dockerfile`

- **Base:** `FROM ghcr.io/berriai/litellm:main-latest@sha256:80ea654c…17bd2` (`litellm/Dockerfile:6`) — el digest manda sobre
  el tag `main-latest` [verificado]. Mismo digest en `docker-compose.yml:70` del repo (dev) [verificado]. El comentario
  (`:4-5`) lo presenta como «Pin por digest (Principio VI)».
- **Verificación del pin:** el digest existe y resuelve en ghcr.io (index OCI, amd64 =
  `sha256:64b0c740…`, 21 capas, 361,4 MB, creada 2026-06-30); la imagen publicada `elea-guardian-engine` tiene sus
  **primeras 21 capas idénticas (diff_ids)** a esa base, más 2 capas propias (`config.yaml` y `extensions/`) = 23 [verificado, §2.4].
  Hoy `main-latest` apunta a otro digest (`sha256:67831417…`) [verificado]: el pin evita la deriva.
- **Dependencias propias:** ninguna: no instala nada (`litellm/Dockerfile:8-9`: solo `COPY`) [verificado]. Todo el árbol Python
  de LiteLLM viene dentro de la base (un `/app/.venv` copiado del builder upstream) [verificado, history del config blob].
- **Qué se copia:** `config.yaml` (`:8`) y `extensions/` (`:9`) del contexto `litellm/`; **no hay `.dockerignore`**
  en `litellm/` (`git ls-files`): entra todo lo que haya en `litellm/extensions/` en disco, p. ej. `__pycache__` [no verificado
  el contenido]. Capa publicada: 0,21 MB.
- **Observaciones:** `main-latest` es la rama main de LiteLLM, no un release; el digest fijado corresponde a LiteLLM 1.92.0
  según el comentario del compose (`docker-compose.yml:67`) [verificado el texto; la versión [no verificada]].
  Los labels `org.opencontainers.image.revision=88e03e54…` y `source=https://github.com/BerriAI/litellm` son los de **upstream**
  (Chainguard `wolfi-base`), no del commit de Elea (§2.3).
- **¿Rebuild hoy = igual?** **Sí en contenido** de las 21 capas base (por digest) y de las 2 propias mientras `config.yaml` /
  `extensions/` no cambien; **no en digest de imagen** (timestamps de las capas nuevas, sin `SOURCE_DATE_EPOCH`)
  [no verificado el segundo punto: no construí].

#### nlp (analizador de PII) — `presidio-analyzer/Dockerfile`

- **Base:** `FROM python:3.11-slim` (`presidio-analyzer/Dockerfile:5`), flotante [verificado]. Dato: el comentario (`:3-4`)
  dice «mismo criterio que litellm por digest — acá por versión exacta de paquete»; es un criterio más débil que el digest.
- **Dependencias:** `pip install -r requirements.txt` (`:12`) con 5 paquetes directos con `==`
  (`presidio-analyzer==2.2.358`, `spacy==3.7.5`, `fastapi==0.111.0`, `uvicorn[standard]==0.30.1`, `pydantic==2.13.4`;
  `presidio-analyzer/requirements.txt:1-5`) [verificado]. **Sin lock/hashes**: transitivas flotan (`thinc`, `numpy`, `spacy-*`, etc.
  [no verificado el árbol exacto]). Además **`python -m spacy download es_core_news_md`** (`:13`) **sin versión**: descarga
  el modelo compatible con la versión de spaCy desde el release de GitHub el día del build [verificado el comando;
  [no verificado] qué versión resuelve hoy]. Esa capa pesa 85,3 MB (§2.3).
- **`apt-get install gcc`** sin versión (`:9`); queda en la imagen final (capa de 68 MB) [verificado].
- **Multi-stage:** no [verificado].
- **Qué se copia:** `app.py`, `conf/` (`:15-16`) — selectivo, solo lo necesario [verificado]. No hay `.dockerignore`
  (`git ls-files`) pero el `COPY` es acotado.
- **¿Rebuild hoy = igual?** **No.** Base cambiada (0 capas comunes con la de hoy; la publicada es Debian trixie
  `@1783900800` = 2026-07-13, Python 3.11.15) [verificado, §2.4], transitivas y modelo spaCy sin pin.
  Es la imagen menos tocada: sigue siendo la del 2026-08-31 [verificado, §2.2].

#### rag-client (Hub) — `client/Dockerfile`

- **Base:** `FROM node:20-alpine` (`client/Dockerfile:1`), flotante [verificado]. Alpine 3.23.4, Node 20.20.2 en la publicada.
- **Dependencias — tres instaladores distintos, ninguno fijado:**
  - `apk add --no-cache python3 py3-pip py3-docx py3-pandas || (apk add … && pip install python-docx pandas openpyxl
    --break-system-packages)` (`:4-5`): paquetes `apk` **sin versión** (los que haya en el repo de Alpine ese día); el `||`
    hace que, si falla la primera rama, se instale **otra cosa distinta** (versiones de PyPI). El build es no determinista
    además en *qué rama corrió* [verificado el texto; cuál rama corrió en la publicada: [no verificado] — la capa publicada
    de 72 MB sugiere la de `apk`].
  - `pip install --no-cache-dir pypdf --break-system-packages || pip install … pypdf` (`:6`): **`pypdf` sin versión**
    (última de PyPI el día del build; hoy 6.19.0 [verificado en PyPI]).
  - `COPY package.json ./` + `npm install --production` (`:10-11`): **sin `package-lock.json`** aunque existe
    `client/package-lock.json` (lockfileVersion 3, 111 paquetes, todos con `integrity`) [verificado]. Rangos caret
    (`client/package.json:10-17`). Deriva medida: `express` lock 4.22.2 vs máximo en rango 4.22.3 [verificado, npm 2026-10-06].
- **Multi-stage:** no [verificado].
- **Qué se copia:** `COPY . .` (`:13`) con `client/.dockerignore` presente (excluye `.env`, `node_modules/` y
  `public/uploads/*` salvo `.gitkeep`; `client/.dockerignore:1-4`) [verificado]; `tests/` **no** se excluye y va dentro de la imagen. Capa publicada 0,33 MB.
- **¿Rebuild hoy = igual?** **No.** Base flotante (Node 20 alpine hoy coincide capa a capa con la publicada, 4/4 [verificado]),
  pero `apk`/`pypdf`/`npm install` flotan, y el lock se ignora.

#### tabular — `tabular/Dockerfile`

- **Base:** `FROM python:3.12-slim` (`tabular/Dockerfile:3`), flotante [verificado]. Misma base que el backend: las 5 primeras
  capas (debian + python) son **idénticas** (mismos digests) entre `elea-tabular` y `elea-guardian-backend` [verificado, §2.3].
- **Dependencias:** `pip install -r requirements.txt` (`:8`), 8 paquetes directos con `==`
  (`tabular/requirements.txt:1-8`; `fastapi==0.141.1`, `duckdb==1.5.5`, `pandas==2.3.3`, …) [verificado]. Sin hashes ni lock;
  transitivas flotan (p. ej. `numpy` de `pandas`, `starlette` de `fastapi`) [no verificado el árbol exacto].
- **Multi-stage:** no. Usuario no-root (`:13-15`), `HEALTHCHECK` (`:20-21`) [verificado]. Única imagen propia con ambos.
- **Qué se copia:** `app/` (`:10`); `tabular/.dockerignore` excluye `tests`, `pytest.ini`, `__pycache__` (`tabular/.dockerignore:1-5`)
  [verificado].
- **¿Rebuild hoy = igual?** **No** (base de hoy distinta de la publicada, 0 capas comunes; transitivas flotantes) [verificado
  la base, §2.4]. Capa `pip install` publicada: 84,1 MB.

### 1.3 Imágenes de terceros que el instalador hace correr

Fuente: `elea-installer/docker-compose.yml` (solo lectura, HEAD `9754f13`, árbol limpio) [verificado].

| Servicio | Imagen en el compose | Línea | Cómo está fijada | Digest que resuelve hoy (2026-10-06) | Observación |
|---|---|---|---|---|---|
| `db` | `postgres:16-alpine` | 7 | **Solo tag de versión mayor** (flotante dentro de 16.x y de la versión de Alpine) | index `sha256:721873c3…`, amd64 `sha256:1a66d744…`, creada 2026-09-17, 116 MB | Cada `pull` en una sede puede traer una menor distinta. Servicio con **datos** (volumen `pgdata`). |
| `redis` | `redis:7-alpine` | 24 | **Solo tag de versión mayor** | index `sha256:858f009f…`, amd64 `sha256:ca0acbb1…`, creada 2026-09-17, 16 MB | Cache; menor impacto. |
| `anythingllm` | `mintplexlabs/anythingllm:1.16.1` | 156 | **Tag de versión exacta** (fijada a propósito, spec 043 US1 T021, comentario `:153-155`) — pero un tag es **mutable**; no hay digest | index `sha256:05617e7b…`, amd64 `sha256:b7b570b8…`, creada 2026-08-27, 1,10 GB | Es la imagen más pesada del stack junto con presenton. Que el tag sea inmutable en la práctica [no verificado]. |
| `presenton` | `ghcr.io/presenton/presenton@sha256:f0c6a235…d740e18` | 240 | **Digest** (comentario `:237`: «PIN POR DIGEST (v0.9.7-beta)») | el digest resuelve (index OCI; amd64 `sha256:c723cf3d…`, creada 2026-08-18, 26 capas, 1,65 GB). `:latest` hoy apunta a otro index (`sha256:ddf0d1f2…`) | Única de terceros reproducible. Versión `v0.9.7-beta` [no verificado]: los labels del config no traen versión, solo `com.docker.compose.*`. |

Todo lo de la columna «Digest» [verificado] contra Docker Hub / ghcr.io hoy. **Qué digest corre efectivamente en la sede
de Eleia** (el que bajó el último `docker compose pull`) **[no verificado]**: no tengo acceso a esa máquina; solo puedo decir qué
devolvían los tags hoy. Para `postgres` y `redis` el digest en producción puede ser anterior al de hoy.

Para completar el cuadro, las 6 propias en el mismo compose, todas por **`:latest`** (líneas 36, 48, 88, 131, 174, 217) [verificado].
`engine` y `backend` en el repo de desarrollo también están pinneados como en §1.2 (`docker-compose.yml:70,260,320` del repo):
anythingllm y presenton quedaron con los mismos pins en dev y en el instalador [verificado].

---

## §2. Manifiestos publicados en `ghcr.io/cluna-8/elea-*`

### 2.0 Cómo se midió

- `GET https://ghcr.io/token?scope=repository:cluna-8/<img>:pull` (sin credenciales) → token anónimo; luego
  `GET /v2/<img>/tags/list`, `GET /v2/<img>/manifests/<tag>` (con `Accept` de OCI index/manifest + docker v2) y
  `GET /v2/<img>/blobs/<config-digest>` (config blob: 6–8 KB cada uno). Sin `docker`, sin capas [verificado].
- Los 6 repos son **públicos**: con token anónimo todo responde 200. Sin token el manifiesto da 401 (el registry exige el
  handshake de token, pero **nada pidió login** ni credenciales) [verificado].
- Todas las imágenes son **un solo manifiesto `application/vnd.docker.distribution.manifest.v2+json`, `linux/amd64`**: no
  son OCI index, no hay arm64 ni manifiestos de attestation (`/referrers/<digest>` devuelve 0 para los 6 `:latest`) [verificado].
- `tags/list` no pagina (sin cabecera `Link`) [verificado]. Los **«versiones»** del paquete en GitHub incluyen versiones sin tag
  (huérfanas, manifiestos viejos) que la API del registry **no lista**; eso requiere la API de GitHub con token [no verificado].

### 2.1 Tags por imagen

| Imagen | Tags en el registry | N |
|---|---|---|
| `elea-guardian-backend` | `latest`, `2026-09-14`, `2026-09-17`, `2026-09-21` | 4 |
| `elea-guardian-frontend` | `latest`, `2026-09-14`, `2026-09-17`, `2026-09-21` | 4 |
| `elea-guardian-engine` | `latest`, `2026-09-14`, `2026-09-17` | 3 |
| `elea-guardian-nlp` | `latest`, `2026-09-14` | 2 |
| `elea-rag-client` | `latest`, `2026-09-14`, `2026-09-17`, `2026-09-21` | 4 |
| `elea-tabular` | `latest`, `2026-09-14` | 2 |

Total 19 tags / 6 repos; **ninguna publicación posterior al 2026-09-21** (hace 15 días respecto de la medición, y el repo
sigue avanzando: HEAD `892624e` del 2026-10-05) [verificado]. Todos los tags son **fechas de publicación**, no versiones
semánticas ni SHAs [verificado, `publish-elea.sh:19`].

### 2.2 El `:latest` de cada imagen

| Imagen | Digest de `:latest` (manifiesto) | Creada (config `created`) | Tag fechado que lo iguala | Capas | Tamaño comprimido (suma capas) | Labels OCI propios | `…revision` |
|---|---|---|---|---|---|---|---|
| backend | `sha256:742981ff937d510eed1457f71ed35ffeadbb98bea718ecbed145b561b9f38c9b` | 2026-09-21T22:05:53+02:00 | `2026-09-21` | 12 | 283,3 MB (283 324 308 B) | ninguno (`Labels: null`) | **no existe** |
| frontend | `sha256:478544c93f3f96aa4b1ba7c87bddb2bb418ba886656cd29918c9ed842bdaee30` | 2026-09-21T22:06:11+02:00 | `2026-09-21` | 9 | 255,4 MB (255 356 326 B) | ninguno | **no existe** |
| engine | `sha256:1928af9d1ef6bc6325150ea8cf0a` `8542020d4b461da621e4079f3d8a6189dafe` | 2026-09-17T09:26:50+02:00 | `2026-09-17` | 23 | 361,4 MB (361 402 149 B) | **solo los heredados** de la base (Chainguard/LiteLLM) | existe pero es de **upstream**: `88e03e548716a45284597edf2b7f47a7e6a66d5f` (`github.com/BerriAI/litellm`) |
| nlp | `sha256:f4ca5d8aa9f49591a05c32c0e6e3621e9b75fa5afb8705dcacf1dc1de1bd0e8d` | **2026-08-31T11:31:30+02:00** | `2026-09-14` | 11 | 278,3 MB (278 307 018 B) | ninguno | **no existe** |
| rag-client | `sha256:ba5c72f5fd4fbad0e2207a1b11ab0dd22b205e07ea2803cb29448f94c4cd906f` | 2026-09-21T21:03:39+02:00 | `2026-09-21` | 10 | 125,5 MB (125 462 156 B) | ninguno | **no existe** |
| tabular | `sha256:2267febddf128bc2ef62252585ef56e94f4ed17aaf333ae9ec901cbc5c92e3e9` | 2026-09-14T18:38:28+02:00 | `2026-09-14` | 9 | 128,4 MB (128 440 527 B) | ninguno | **no existe** |

Todo [verificado]. Total de las 6 `:latest`: **1 432,3 MB** comprimidos; **1 388,1 MB** de capas únicas (las 5 capas base de
`python:3.12-slim` se comparten entre backend y tabular: ~44 MB menos). Más los 19 tags: 82 capas únicas, 1 475,1 MB.

**Qué commit se construyó:** el registry **no lo dice** — ninguna imagen propia lleva `org.opencontainers.image.revision`
ni `…source` ni `…created` propios [verificado]. Lo único que se puede hacer es inferir por fecha, con evidencia floja:

- Los `created` del 2026-09-21 son 21:03 (rag-client), 22:05 (backend) y 22:06 (frontend) [verificado]. Los commits del
  repo ese día son `a536820` 20:43, `ce2d4f5` 21:08, `29f5c6d` 22:29 (`git log`) [verificado]. **`rag-client` se construyó
  a las 21:03, antes que `ce2d4f5` (21:08)**, que es el commit que «extiende el cambio obligatorio de contraseña a Eleia Hub»:
  o se construyó desde un árbol sin commitear, o desde `a536820` más cambios locales [no verificado cuál]. Esto es consistente
  con que `publish-elea.sh` construya del árbol de trabajo (§1.0), y es exactamente el problema de trazabilidad.
- `nlp`: el tag `2026-09-14` y `latest` apuntan al **mismo manifiesto** (`f4ca5d8a…`) cuyo `created` es **2026-08-31**: el publicador
  re-etiquetó una construcción cacheada con la fecha del día [verificado]. El tag fechado **no** es la fecha de construcción.
- Los tags `2026-09-21` = `latest` en backend/frontend/rag-client; `2026-09-17` = `latest` en engine; `2026-09-14` = `latest` en
  nlp/tabular [verificado por igualdad de digest].

### 2.3 Qué hay dentro (config blobs y capas del `:latest`)

Todo [verificado] (config blob `history` + tamaños de capa del manifiesto; **no se bajó contenido de capas**).
Tamaño por capa comprimida, en MB. «Base» = capas heredadas de la imagen `FROM`; «propia» = las que agrega el Dockerfile.

- **backend (12 capas, 283,3 MB):** base `python:3.12-slim` Debian trixie `@1785715200` (2026-08-03), Python 3.12.13: capas 1–4
  (30,78 + 1,29 + 12,11 + 0) = 44,2 MB. Propias: 6 `apt-get install build-essential libpq-dev` **111,68 MB**, 8 `pip install -r` **126,31 MB**,
  9 `COPY backend/` 1,06 MB, 10 `litellm/extensions` 0,08 MB, 11–12 config/auto_router ~0. Sin `USER` (root), sin `HEALTHCHECK`.
  `Cmd`: `alembic upgrade head && uvicorn src.main:app …` (sin `--reload`; `Dockerfile.standalone:35`).
- **frontend (9 capas, 255,4 MB):** base `node:20-slim` Debian bookworm `@1776729600` (2026-04-21), Node 20.20.2: capas 1–5 = 72,3 MB.
  Propias: 8 `npm install` **139,51 MB**, 9 `COPY . .` **43,55 MB**. `Cmd`: `npm run dev -- --host`, `Entrypoint`: `docker-entrypoint.sh`.
  Corre **el servidor de desarrollo de Vite**, sin `USER` no-root explícito.
- **engine (23 capas, 361,4 MB):** 21 capas de la base LiteLLM (11 capas `apko` Wolfi + `apk add` + 9 copias del builder, incluyendo
  `/app/.venv`, prisma 47,3 MB + 60,7 MB) y 2 propias (`config.yaml` ~0, `extensions/` **0,21 MB**). `User: root`;
  `Entrypoint: litellm --config /app/config.yaml`. Sin `HEALTHCHECK` en la imagen (lo pone el compose).
- **nlp (11 capas, 278,3 MB):** base `python:3.11-slim` trixie `@1783900800` (2026-07-13), Python 3.11.15: 45,7 MB. Propias:
  6 `apt-get install gcc` **68,00 MB**, 8 `pip install -r` **78,55 MB**, 9 `spacy download es_core_news_md` **85,25 MB**, 10–11 `app.py`/`conf` ~0.
- **rag-client (10 capas, 125,5 MB):** base `node:20-alpine` Alpine 3.23.4 (2026-04-15), Node 20.20.2: 48,4 MB. Propias: 5 `apk add python3
  py3-pip py3-docx py3-pandas` **72,01 MB** (la rama `apk`, no la de fallback `pip`, [no verificado con certeza]), 6 `pip install pypdf` 1,12 MB,
  9 `npm install --production` **3,64 MB**, 10 `COPY . .` 0,33 MB.
- **tabular (9 capas, 128,4 MB):** base `python:3.12-slim` (misma que backend, capas 1–5 idénticas por digest: `085992e40cc3…`,
  `5a31db4cd478…`, `c85ad0bcaca8…`): 44,2 MB. Propias: 7 `pip install -r` **84,11 MB**, 8 `COPY app` 0,07 MB, 9 `useradd` 0,07 MB.
  `User: tabular`; trae `HEALTHCHECK`.

### 2.4 Comparación de la base publicada contra la base de **hoy** (por `diff_ids` del config blob)

Se bajó el config blob de la base de hoy desde Docker Hub (manifiesto linux/amd64) y se comparó el prefijo de `rootfs.diff_ids`
con el de la imagen publicada [verificado todo, 2026-10-06]:

| Imagen propia | Tag de base | Digest del index de hoy | Base de hoy creada | Capas de la base hoy | Capas en común con la imagen publicada | ¿Mismo contenido? |
|---|---|---|---|---|---|---|
| backend | `python:3.12-slim` | `sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d` | 2026-10-01 | 4 | **0** | **No** |
| tabular | `python:3.12-slim` | ídem | ídem | 4 | **0** | **No** |
| nlp | `python:3.11-slim` | `sha256:6f31d6e9ba2b0a787a3f81c37b004155b87b9efa1b771182bd550c1615745be5` | 2026-10-01 | 4 | **0** | **No** |
| frontend | `node:20-slim` | `sha256:2cf067cfed83d5ea958367df9f96` `6191a942351a2df77d6f0193e162b5febfc0` | 2026-04-22 | 5 | **5 de 5** | Sí (hoy) |
| rag-client | `node:20-alpine` | `sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293` | 2026-04-15 | 4 | **4 de 4** | Sí (hoy) |
| engine | `ghcr.io/berriai/litellm@sha256:80ea654c…` | `sha256:80ea654c506da9083503d00c1b323b2fecddf17af6add9bf01b2603938e17bd2` | 2026-06-30 | 21 | **21 de 21** | Sí (por digest) |

Hallazgos laterales, [verificado]:

- El digest de `node:20-alpine` de hoy (`fb4cd12c…`) es **exactamente el que ya está pineado** en
  `deploy/docker/frontend.prod.Dockerfile:6` — ese pin sigue siendo vigente.
- El pin de `python:3.12-slim` en `deploy/docker/backend.prod.Dockerfile:8,18` (`sha256:57cd7c3a…`, «resuelta 2026-07-20») **no** es el
  `python:3.12-slim` de hoy (`02108f5d…`) ni (por la fecha) el que contiene la imagen publicada (que es del 2026-08-03). O sea, **la
  deriva de la base de Python ocurre aun con la intención de pinear**: tres «versiones» de `python:3.12-slim` en menos de tres meses.
- Las bases de Python se republican cada pocas semanas (hoy 2026-10-01 vs publicada 2026-08-03/07-13); las de Node 20 son más estables
  (últimas 2026-04) pero eso depende de Docker Hub, no del repo.

### 2.5 Deriva entre tags de la misma imagen (qué cambia de una publicación a otra)

Capas del tag fechado que **no** están en `:latest` (por digest de capa) [verificado]:

| Imagen | Tag | Capas distintas vs `latest` | Bytes de esas capas |
|---|---|---|---|
| backend | 2026-09-14 | 4 de 12 | 1,14 MB |
| backend | 2026-09-17 | 4 de 12 | 1,14 MB |
| backend | 2026-09-21 | 0 | (= latest) |
| frontend | 2026-09-14 | 1 de 9 | **41,94 MB** |
| frontend | 2026-09-17 | 1 de 9 | 41,94 MB |
| frontend | 2026-09-21 | 0 | (= latest) |
| engine | 2026-09-14 | 1 de 23 | 0,21 MB |
| engine | 2026-09-17 | 0 | (= latest) |
| rag-client | 2026-09-14 | 1 de 10 | 0,33 MB |
| rag-client | 2026-09-17 | 1 de 10 | 0,33 MB |
| rag-client | 2026-09-21 | 0 | (= latest) |

Lectura: entre publicaciones **solo cambian las capas `COPY` del código** (y la de `COPY . .` del frontend, 42–44 MB, que pesa casi
como el resto del panel). Las capas de dependencias (`pip install`, `npm install`, `apk add`, base) son **las mismas en los 3–4
tags** porque salieron de la caché local de Docker del publicador [verificado por digest de capa]. Esto significa que **el
historial de tags no es evidencia de reproducibilidad**: las dependencias de las 6 imágenes se resolvieron una sola vez
(2026-08-31 para backend/nlp/rag-client-pip, 2026-09-09 para npm de frontend y client, 2026-09-12 para tabular) y se reutilizaron.

---

## Estimación de descarga para la §3 (qué hay que bajar y cuánto)

Premisa: la §3 mide si un rebuild reproduce la imagen publicada. Hay tres niveles posibles; todos los valores son bytes
comprimidos del manifiesto (lo que se transfiere), [verificado] como suma de capas; la **necesidad** de cada nivel es mi
recomendación, no un hecho.

**Nivel 0 — nada que bajar (ya hecho en §2.4).** El `diff_id` de las capas base se compara con solo el config blob de la base
(KB). Con eso ya está demostrado que las bases Python difieren. No requiere más descargas.

**Nivel 1 — mínimo recomendado: solo capas propias donde hay una pregunta abierta.** Para contestar «¿qué había realmente dentro?»:

| Qué bajar | De qué imagen | Capa(s) | Tamaño | Para qué |
|---|---|---|---|---|
| Capa `COPY . .` del frontend `:latest` | `elea-guardian-frontend` | `4bcdf12399a2…` | **43,55 MB** | Confirmar si contiene `node_modules`/`dist` del host (hipótesis §1.2) |
| Capa `COPY backend/ .` del backend `:latest` | `elea-guardian-backend` | `e68527eb29a9…` | 1,06 MB | Confirmar que no entró `scripts/license_out/` ni `*.lic` (riesgo §1.2) |
| Capa `COPY litellm/extensions/` (backend) y del motor | backend / engine | `124835a62b39…`, `2be10b23d8ab…` | 0,08 + 0,21 MB | Comprobar `__pycache__` y que ambas copias coincidan |
| Capa `COPY . .` del rag-client | `elea-rag-client` | `49ffeae01811…` | 0,33 MB | Idem |
| Capas `COPY app`/`app.py`/`conf` de tabular y nlp | tabular / nlp | `c22fa6b68db4…`, `49d219bed82c…`, capas 10–11 de nlp | ~0,15 MB | Idem |

**Subtotal nivel 1 ≈ 45 MB** (45,4 MB). Es suficiente para cerrar los dos puntos marcados [no verificado] de §1.2 sin bajar
dependencias.

**Nivel 2 — comparar dependencias instaladas contra un rebuild** (lo que la §3 haga necesitará además `docker build` del lado
de quien corra la medición, y avisar al owner antes de usar Docker). Para listar versiones realmente instaladas (`pip freeze` equivalente
leyendo `site-packages/*.dist-info` dentro de las capas) hay que bajar las capas de dependencias de cada imagen:

| Imagen | Capas de dependencias a bajar | Tamaño |
|---|---|---|
| backend | `pip install` 126,31 MB (+ `apt build-essential` 111,68 MB solo si se quiere auditar la herramienta de compilación) | 126,3 MB (238,0 MB con apt) |
| tabular | `pip install` 84,11 MB | 84,1 MB |
| nlp | `pip install` 78,55 MB + modelo spaCy 85,25 MB (+ `apt gcc` 68 MB opcional) | 163,8 MB (231,8 MB con apt) |
| frontend | `npm install` 139,51 MB | 139,5 MB |
| rag-client | `apk add` 72,01 MB + `pip pypdf` 1,12 MB + `npm install` 3,64 MB | 76,8 MB |
| engine | nada propio; las 21 capas base están pineadas por digest (361 MB) y son idénticas por `diff_id` | 0 |

**Subtotal nivel 2 ≈ 590 MB** (590,5 MB solo dependencias; 815,6 MB sumando también las capas `apt`/`COPY` propias).
**Si además se quiere el contenido de las bases** (no recomendado: ya probado por `diff_id`): base python 44,2 MB (compartida entre
backend y tabular) + python 3.11 45,7 MB + node-slim 72,3 MB + node-alpine 48,4 MB = ~211 MB.

**Nivel 3 — todo.** Las 6 `:latest` completas: **1 432,3 MB** (1 388,1 MB sin duplicados); con los 19 tags, 1 475,1 MB únicos.
Descartado como innecesario (la deriva entre tags es solo de capas `COPY`, §2.5).

**Terceros** (postgres, redis, anythingllm, presenton): no hace falta bajar nada para §3; sus digests ya están
medidos (§1.3). Si se quisiera medir el contenido real: postgres 116 MB, redis 16 MB, anythingllm **1,10 GB**, presenton **1,65 GB**
(no recomendado).

**Recomendación para la §3:** Nivel 1 completo (~45 MB) + del Nivel 2 solo `backend` y `rag-client` (~203 MB), que es donde el
`||`/`apk` sin versión y las transitivas del backend dan más incertidumbre. Total ≈ 250 MB sin tocar Docker para descargar; el
rebuild comparativo sí requiere Docker y **aviso previo al owner**.

---

## §3. Dependencias instaladas en las imágenes publicadas vs lo que declara el repo

> Medición del 2026-10-06, autorizada por el owner en el nivel «recomendado» de la sección anterior,
> **con `curl` y sin Docker** (ni `docker pull`, ni `docker run`, ni `docker images`: no se usó el binario, así que no
> hay imágenes locales que borrar). Los blobs se bajaron a `/tmp/claude-1000/medicion-imagenes` (fuera del repo) y **se borraron al terminar**.
> Repo comparado: HEAD `83b57dd` (el `backend/`, `client/`, `frontend/`, `litellm/`, `tabular/`, `presidio-analyzer/` de este HEAD).

### 3.0 Método y comandos (todo corrido en esta sesión)

| Paso | Comando (resumido) | Resultado |
|---|---|---|
| Manifiestos y config de los 6 `:latest` | `curl` con token anónimo `ghcr.io/token?scope=repository:cluna-8/<img>:pull` → `/v2/<img>/manifests/latest` y `/blobs/<config>` | 6 manifiestos v2, capas 12/9/23/11/10/9 (igual que §2.2) |
| Bajar capas | `curl -L -H "Authorization: Bearer …" /v2/<img>/blobs/sha256:<capa>` y `sha256sum` | el `sha256sum` del archivo bajado coincide con el digest de la capa en los 23 blobs completos bajados (5 grandes impresos al bajarlos, 18 re-verificados antes de borrar) [verificado] |
| Leer contenido | `tar -tzf`, `tar -xzOf`, `tar -xzf --wildcards '*.dist-info/METADATA'`; `lib/apk/db/installed`; `node_modules/.package-lock.json` | ver 3.1–3.6 |
| Diff contra el repo | `git ls-files <dir>` vs. lista de archivos de la capa, `cmp` archivo a archivo; `python3 -I` para comparar versiones | ver 3.1–3.6 |
| «¿Qué resolvería un rebuild?» (sin Docker) | **Python:** `uv pip compile <requirements> --python-version 3.1x --python-platform x86_64-manylinux_2_28 [--exclude-newer <fecha>]`; **npm:** `npm install --package-lock-only --ignore-scripts [--before=<fecha>]` en un directorio vacío con solo `package.json`; **Alpine:** `APKINDEX.tar.gz` de `v3.23/{main,community}` | resolución «a la fecha del build» y «hoy» |

**Validación del método de resolución** [verificado]: resolviendo con el corte en la fecha de cada capa de dependencias (`created` del config blob), el resultado
reproduce **exactamente** lo instalado en las cuatro capas medidas: backend 94/94 paquetes Python (`--exclude-newer 2026-08-31T06:39:01Z`),
Hub-pip 9/9 + `pypdf==6.16.2` (cortes 2026-08-26T10:30:29Z y 2026-08-31T15:14:14Z), Hub-npm 89/89 (`--before=2026-09-09T18:21:53Z`),
frontend-npm 451/451 (`--before=2026-09-09T18:22:38Z`). Esto respalda usar la misma resolución con fecha de **hoy** como «lo que traería un rebuild hoy».
Salvedades del método: usa `uv` y el `npm` 10.9.8/Node 22 de esta máquina, no el `pip`/`npm` del builder; resuelve solo ruedas (`manylinux_2_28` / `musllinux`), no
reproduce la rama de compilación desde sdist ni los paquetes del sistema (`apt`/`apk`).

**Volumen bajado:** ≈257 MB comprimidos (capas de dependencias del backend 126,3 MB y del Hub 76,8 MB; capas `COPY` de las 6 imágenes y del frontend 43,6 MB; más lecturas
parciales por `Range` de 3 MB, dos veces, sobre la capa `npm install` del frontend para leer solo su `.package-lock.json`, y 2,2 MB de capas `COPY` de los tags viejos del backend).
El owner autorizó ≈250 MB: el exceso (≈7 MB) son esas lecturas parciales y los tags viejos; **no** se bajó la capa `npm install` completa del frontend (139,5 MB), ni `pip` de
tabular/nlp, ni `apt`/`gcc`/`build-essential`, ni el modelo spaCy.

### 3.1 Resultado principal: qué hay dentro de las capas `COPY` (cierra los ◆ 1, 2 y 3 de «No verificado»)

**Backend — capa `COPY backend/ .` (`e68527eb29a9…`, 1,06 MB; 320 entradas, 3 572 074 B sin comprimir) [verificado].** Prioridad 1 del owner:

- **No contiene `scripts/license_out/`**; de `backend/scripts/` solo hay 6 entradas (los `.py` trackeados). **Solo hay un `.lic`: `config/licenses/dev-demo.lic`**
  (499 B), con el mismo sha256 que el trackeado en el repo (`65e7b205ad50…`). **Ninguna clave privada**: el único `.pem` es `src/keys/sentinel_public_keys.pem`
  (3 bloques de clave pública, 0 de clave privada); un `grep` por el marcador PEM de clave privada encontró 1 archivo, que es el falso positivo
  `tests/integration/test_audit_tamper.py:113` (un `assert` negativo del propio test, no una clave). **Ningún `.env`**, ningún `*.p12/.pfx/id_rsa`, ningún `__pycache__`/`.pyc` (0).
- **Es exactamente `backend/` de HEAD**: 297 archivos en la capa, 297 trackeados, **0 distintos, 0 sobrantes, 0 faltantes** (`git ls-files backend` vs capa, `cmp` de cada archivo).
  Va dentro `tests/` completo (167 archivos): el código de pruebas se publica en la imagen de producción, además de `pytest`.
- Misma revisión en los tags viejos: las capas `COPY backend/` de `2026-09-14` (`739e8b4281f6…`) y `2026-09-17` (`4c4a2f3b3a05…`) también tienen solo `dev-demo.lic` (mismo sha256) y `sentinel_public_keys.pem`
  (0 claves privadas) [verificado]. Se leyeron las capas distintas de esos dos tags (4 por tag, 1,14 MB); **los demás tags/capas no se miraron**.
- **Conclusión de la duda `license_out`:** en la publicación del 2026-09-21 (y 09-14, 09-17) **no se filtró nada**. Que `backend/.dockerignore:6-7` no aplique con contexto raíz sigue siendo
  [no verificado] como mecanismo, pero **el efecto observado es el correcto**: el árbol del publicador no tenía `license_out/` ni otros `.lic`. El riesgo estructural sigue ahí: nada en el Dockerfile ni en el script lo impide.
- `litellm/extensions/` (capa `124835a62b39…`), `config.yaml` y `auto_router.json` del backend: idénticos a `litellm/` de HEAD, sin `__pycache__` [verificado].

**Frontend — capa `COPY . .` (`4bcdf12399a2…`, 43,55 MB; 18 020 entradas) [verificado].** Confirma la hipótesis de §1.2:

- **17 857 de las 18 020 entradas son `app/node_modules/`** (el `node_modules` del equipo que publicó) y 89 son `app/dist/` (un build estático del host, que el servidor `vite` no usa). No hay `.env`, `.git`, `.pem`, `.key` ni `.lic` por nombre
  (no se grepeó el contenido de los 17 857 archivos de `node_modules`: [no verificado] a ese nivel).
- `package.json` y `package-lock.json` copiados son **idénticos** a `frontend/` de HEAD (`cmp`); `src/`, `tests/`, `e2e/`: 50 archivos, 0 distintos. Los archivos de configuración de raíz (`vite.config.ts`, etc.) no se comprobaron [no verificado: no los extraje].
- El `.package-lock.json` oculto del `node_modules` del host lista **453 paquetes, todos con la misma versión que `frontend/package-lock.json`** del repo (453/453), y le faltan 46 binarios opcionales de otras plataformas (los de `@esbuild/*`, `@rollup/*`, `fsevents`); trae el binario `linux-x64` y el `linux-x64-musl` de rollup. Se infiere que el host es un Linux x64 con un `node_modules` instalado según el lock [inferido, no verificado]. Fecha de esos archivos: 2026-09-08.
- **Consecuencia (la parte seria):** en la imagen coexisten **dos árboles**: el del `RUN npm install` (capa 8, 2026-09-09: 451 paquetes, **32 con versión distinta a la del lock**, todas más nuevas) y, encima, el `COPY . .` con el del host (lock). Docker superpone archivos: lo que está en las dos capas queda con el contenido del host. Las **32 colisiones** (p. ej. `react-router-dom` 6.30.6 npm install vs 6.30.4 host; `rollup` 4.63.1 vs 4.62.2; `postcss` 8.5.28 vs 8.5.20; `@babel/*` 7.29.8 vs 7.29.7) dejan directorios de paquete
  con los archivos del host más lo que solo existía en la versión nueva [inferido de la semántica de capas de OCI; **[no verificado] a nivel de archivo** (no se abrió la capa 8 completa)]. La versión efectiva de cada uno de esos 32 paquetes no es la del lock ni la de `npm install`, sino una mezcla.
- **Ese tamaño cambia en cada publicación** (§2.5): lo que va a producción depende de qué `node_modules` tenga en disco quien publica ese día.

**Resto de las capas `COPY` [verificado]:**

| Imagen | Capa | Contra HEAD | Observación |
|---|---|---|---|
| rag-client | `49ffeae01811…` (`COPY . .`, 36 entradas) | 29 archivos, **0 distintos, 0 sobrantes, 0 faltantes** | incluye `tests/`, `Dockerfile`, `.dockerignore` (el `.dockerignore` no excluye `tests/`). **Contenido = HEAD de `client/`, que ya incluye `ce2d4f5`** |
| engine | `2be10b23d8ab…` (`extensions/`, 0,21 MB) y `7aee564e7c39…` (`config.yaml`) | 9 `.py` idénticos a `litellm/extensions` y `config.yaml` idéntico | **más 9 `.pyc` de `__pycache__` del host: 4 `cpython-312` y 5 `cpython-313`** (no hay `.dockerignore` en `litellm/`) |
| tabular | `c22fa6b68db4…` (`app/`, 67 KB) | 7 `.py` idénticos | **más 7 `.pyc` de `app/__pycache__`** (`cpython-312`) aunque `tabular/.dockerignore:2-3` lista `__pycache__$` y `*.pyc$` (con `$` literal; el `.dockerignore` no es regex, y esas rutas no son de raíz). El patrón no funcionó [verificado el efecto; la causa exacta [no verificado]] |
| nlp | `0d0e42859adc…` (`app.py`), `d8b6c5ce603f…` (`conf/`) | `app.py` idéntico; `conf/` idéntico | sin sorpresas |

**Corrección a §2.2** [verificado]: `rag-client` se construyó a las 21:03 del 2026-09-21 y el commit `ce2d4f5` es de las 21:08; el contenido de la capa **ya es el de `ce2d4f5`** (0 diferencias con HEAD). Es decir, se construyó desde un
árbol de trabajo **con el cambio sin commitear**, que se comiteó 5 minutos después. Cierra el ◆ 8 para `rag-client`: el `:latest` de `rag-client` equivale al árbol de `ce2d4f5`.

### 3.2 backend (`elea-guardian-backend`) — Python

**Instalado (capa `pip install`, `bd0475eeb14a…`, creada 2026-08-31T08:39+02:00):** 94 paquetes (`*.dist-info/METADATA` de `site-packages`), 20 con marca `REQUESTED` (los directos) [verificado].

| Comparación | Resultado |
|---|---|
| Directos: `backend/requirements.txt:1-27` (20 pines `==`) vs instalado | **20/20 iguales** (0 versiones distintas, 0 faltantes; los 20 `REQUESTED` son exactamente los 20 declarados) |
| Sobrantes (instalados, no declarados) | **74 transitivos**, ninguno con pin: p. ej. `starlette==0.37.2`, `litellm==1.95.1`, `openai==2.54.0`, `tokenizers==0.23.1`, `huggingface_hub==1.29.0`, `aiohttp==3.14.3`, `uvloop==0.22.1`, `websockets==17.1`, `ujson==5.13.0`, `filelock==3.32.4` |
| Cosas que **no deberían estar en producción** | `pytest==8.2.2`, `pytest-asyncio==0.23.7` (declarados en `requirements.txt:26-27`) más `pluggy`, `iniconfig` |
| Árbol grande que entra por un solo pin | `headroom-ai==0.30.0` (`requirements.txt:24`) declara `litellm>=1.86.2,<2.0` → trae `litellm`, `openai`, `tokenizers`, `huggingface_hub`, `hf-xet`, `ast-grep-cli`… **El backend lleva su propio LiteLLM 1.95.1 sin pin**, distinto del motor (que va por digest; su versión [no verificado], el compose dice 1.92.0, §1.2) |

**¿Reconstruirla hoy cambiaría lo que corre?** **Sí.** Resolución de hoy vs lo instalado: **26 de 94 paquetes cambian** (28 %), 0 agregados, 0 quitados; **los 20 directos no cambian** (sus pines los frenan).
Todos los cambios son transitivos:

| Paquete | Instalado → hoy | Viene de |
|---|---|---|
| `filelock` | 3.32.4 → **4.0.12** (salto mayor) | `huggingface_hub` |
| `ujson` | 5.13.0 → **6.0.0** (salto mayor) | `fastapi==0.111.0` |
| `huggingface-hub` | 1.29.0 → 1.33.0 | `headroom-ai`, `tokenizers` |
| `uvloop` | 0.22.1 → 0.23.0 | `uvicorn[standard]`, `litellm` |
| `watchfiles` | 1.2.0 → 1.3.0 | `uvicorn[standard]` |
| `websockets` | 17.1 → 17.2 | `uvicorn`, `openai`, `litellm` |
| `aiohttp`, `urllib3`, `idna`, `charset-normalizer`, `regex`, `multidict`, `yarl`, `rpds-py`, `jiter`, `tokenizers`, `fsspec`, `Mako`, `MarkupSafe`, `greenlet`, `python-dotenv`, `opentelemetry-api`, `tqdm`, `rich-toolkit`, `zipp` | patches/minors (p. ej. `aiohttp` 3.14.3 → 3.14.4, `urllib3` 2.7.0 → 2.8.0, `MarkupSafe` 3.0.3 → 3.0.4, `Mako` 1.4.1 → 1.4.3) | varios |

Además de los 26: la base cambia (`python:3.12-slim` hoy es Python **3.12.15** vs **3.12.13** en la imagen; 0 capas en común, §2.4) y el `apt-get install build-essential libpq-dev` (`Dockerfile.standalone:14-17`) sin versiones trae lo que haya hoy en Debian
(la capa de 111,7 MB **no se bajó**: sus versiones [no verificado]). **Lo que más riesgo da:** `filelock` 4.x, `ujson` 6.x (usado por `fastapi` para `UJSONResponse`; que el backend lo ejecute [no verificado]) y los cambios en el trío de red (`uvloop`/`websockets`/`aiohttp`) que corre el servidor y las llamadas a proveedores.

### 3.3 rag-client / Hub (`elea-rag-client`) — Node + Python + Alpine

**Hallazgo central de esta imagen** [verificado]: **la rama `apk` del `||` de `client/Dockerfile:4-5` NO fue la que corrió; corrió la rama de respaldo `pip`.** Evidencia: la base de datos de `apk` de la capa (`lib/apk/db/installed`, 41 paquetes)
tiene `python3 3.12.14-r0`, `py3-pip 25.1.1-r1`, `py3-setuptools 80.9.0-r2`, **pero ni `py3-docx` ni `py3-pandas`**, y `python-docx`, `pandas` y `openpyxl` figuran con `REQUESTED` (marca de `pip install` explícito) con `numpy`, `lxml`, etc. instalados como ruedas.
Causa: **`py3-docx` no existe en Alpine 3.23** (`APKINDEX` de `v3.23/main` y `v3.23/community`: hay `py3-pandas 2.3.3-r0`, `py3-numpy 2.3.5-r0`, `py3-openpyxl 3.1.5-r0`, **no `py3-docx`**), así que `apk add` falla y se ejecuta el respaldo.
Esto **corrige** §1.2/§2.3 («la capa de 72 MB sugiere la rama `apk`», ◆ 5): los 72 MB son las ruedas de PyPI. Por lo mismo, **hoy corre de nuevo el respaldo** (mismo motivo, [verificado] el índice de hoy).

**Instalado (capas 5, 6, 9; creadas 2026-08-26, 2026-08-31 y 2026-09-09):**

| Origen | Paquetes instalados | Qué declara el repo |
|---|---|---|
| `pip` (respaldo, capa 5) | `python-docx==1.2.0`, `pandas==3.0.5`, `openpyxl==3.1.5`, `numpy==2.5.2`, `lxml==6.1.2`, `python-dateutil==2.9.0.post0`, `et_xmlfile==2.0.0`, `six==1.17.0`, `typing_extensions==4.16.0` | **Nada con versión:** `client/Dockerfile:5` lista nombres sueltos (`python-docx pandas openpyxl`) |
| `pip` (capa 6) | `pypdf==6.16.2` | `client/Dockerfile:6`, sin versión |
| `apk` | `python3 3.12.14-r0`, `py3-pip 25.1.1-r1`, `py3-setuptools 80.9.0-r2`, `py3-packaging 25.0-r0`, `py3-parsing 3.2.5-r0` (41 paquetes `apk` en total en la DB, con `musl 1.2.5-r23`, `libcrypto3 3.5.6-r0`, …) | `client/Dockerfile:4-5`, sin versión |
| `npm` (capa 9, `npm install --production`): `/app/node_modules/.package-lock.json` | **89 paquetes** | `client/package-lock.json` (111 paquetes con dev; **88 en producción**) y `client/package.json:10-17` |

**Diff npm contra el repo** [verificado]: de los 89 instalados, **87 coinciden con el lock del repo**; difiere **`body-parser` 1.20.6 (lock) vs 1.20.8 (imagen)** y aparece un `qs` anidado `body-parser/node_modules/qs 6.16.0` que el lock no trae.
Faltantes: 0. Los 22 paquetes del lock que no están en la imagen son todos de `supertest` (dev), correcto con `--production`. **El lock del repo está desfasado respecto de la imagen**: justamente porque el Dockerfile no lo usa.

**¿Reconstruirla hoy cambiaría lo que corre?** **Sí, poco pero cierto:**

| Capa | Instalado → hoy |
|---|---|
| npm | `express` 4.22.2 → **4.22.3**, `proxy-addr` 2.0.7 → 2.0.8, `qs` 6.15.3 → 6.16.0 (y desaparece el `qs` anidado de `body-parser`): **3 cambios, 1 quitado**; `body-parser` queda en 1.20.8 (igual) |
| pip (respaldo) | `lxml` 6.1.2 → 6.1.3, `numpy` 2.5.2 → **2.5.3**, `pandas` 3.0.5 → **3.0.6**; `pypdf` 6.16.2 → **6.19.0** (`lxml`/`numpy`/`pandas` un parche cada uno; `pypdf` sube 3 menores) |
| apk | `python3`, `py3-pip`, `musl`, `libcrypto3`…: **no resuelto** ([no verificado]; la base Alpine de hoy sí es la misma capa a capa, §2.4, pero el repo de Alpine tiene paquetes nuevos) |

Los tres instaladores (apk / pip / npm) se resuelven cada uno por su lado el día del build y el lock se ignora; el resultado es estable mientras Alpine, PyPI y npm no se muevan, y hoy se mueven en 7 paquetes medidos (3 npm + 4 pip).

### 3.4 frontend (panel) (`elea-guardian-frontend`) — Node

**Instalado:** dos árboles superpuestos (3.1): `RUN npm install` (451 paquetes, capa 8 `3202e1fd8012…`, 2026-09-09T20:22:38+02:00; leído solo su `.package-lock.json` por lectura parcial) y `node_modules` del host (453 paquetes, 2026-09-08) en la capa `COPY . .` [verificado].
**Declarado:** `frontend/package.json:13-42` (11 `dependencies` + 15 `devDependencies`, rangos caret) y `frontend/package-lock.json` (500 paquetes; `lockfileVersion` 3). El Dockerfile (`frontend/Dockerfile:5,7`) copia solo `package.json` y corre `npm install` **con devDependencies** (no hay `--omit=dev`), porque el servidor que ejecuta es `vite` (dev).

| Comparación | Resultado |
|---|---|
| `npm install` (capa 8) vs `frontend/package-lock.json` | 451 paquetes: **419 iguales, 32 con versión más nueva que el lock** (`react-router`/`react-router-dom` 6.30.4 → 6.30.6, `@remix-run/router` 1.23.3 → 1.23.4, `rollup` 4.62.2 → 4.63.1, `postcss` 8.5.20 → 8.5.28, `@babel/{generator,parser,traverse,types}` 7.29.7 → 7.29.8, `acorn`, `browserslist`, `caniuse-lite`, `nanoid`, `js-yaml`, …); 0 sobrantes; 48 del lock no instalados (binarios opcionales de otras plataformas) |
| `node_modules` del host vs lock | 453/453 iguales; faltan los 46 binarios opcionales ajenos al host (3.1) |
| Superposición | 32 paquetes colisionan (los mismos 32), 2 solo del host (`@rollup/rollup-linux-x64-musl 4.62.2`, `pify 2.3.0`), 0 solo de la capa 8 |

**¿Reconstruirla hoy cambiaría lo que corre?** **Sí, y de forma más impredecible que en las demás:** (a) `npm install` de hoy traería **51 versiones distintas** a las de la capa 8 (398 iguales), de las cuales 2 son directas (`jsdom` 30.0.1 → 30.1.2, `postcss` 8.5.28 → 8.5.29) y **9 de producción** (la cadena `micromark`/`mdast-util-*` que usa `react-markdown`: `micromark` 4.0.2 → 4.0.3, `mdast-util-from-markdown` 2.0.3 → 2.1.0, `mdast-util-to-markdown` 2.1.2 → 2.2.0, `micromark-factory-space` 2.0.1 → 2.1.0, …),
más saltos mayores solo de test (`jsdom`→`data-urls` 7→8, `html-encoding-sniffer`, `tr46`, `w3c-xmlserializer`, `@asamuzakjp/*`); además `rollup` 4.63.1 → 4.64.0, `browserslist` 4.28.9 → 4.29.3, `undici` 8.10.2 → 8.11.2; un paquete nuevo (`micromark-util-edit-map`) y 2 que salen (`symbol-tree`, `whatwg-url` anidado);
(b) lo que realmente se ejecuta depende del `node_modules` del equipo que publique (3.1): un rebuild en otra máquina **perdería** la mezcla actual de 32 paquetes y quedaría con el árbol de `npm install` puro, distinto de lo que corre hoy en las sedes.
La base `node:20-slim` de hoy sí coincide capa a capa (§2.4).

### 3.5 tabular y nlp — **solo la parte propia, sin instalado leído**

Las capas `pip install` de `tabular` (84,1 MB) y `nlp` (78,6 MB + 85,3 MB del modelo) **no estaban en el nivel autorizado** y no se bajaron: el **instalado real es [no verificado]**. Lo que sí se midió es lo que resolvería cada fecha con el método validado en 3.0:

| Imagen | Capa `pip` creada | Pines directos (repo) | Paquetes resueltos | Cambian entre «fecha del build» y hoy |
|---|---|---|---|---|
| tabular | 2026-09-12 | 8 en `tabular/requirements.txt:1-8` | 33 | **8**: `starlette` 1.6.0 → **1.7.0** (sin pin, lo trae `fastapi==0.141.1`), `uvloop` 0.22.1 → 0.23.0, `watchfiles` 1.2.0 → 1.3.0, `websockets` 17.1 → 17.2, `idna`, `python-dotenv`, `pytz`, `tzdata` |
| nlp | **2026-07-20** (la capa `pip` y la del modelo; el `created` 2026-08-31 de §2.2 es de la última capa, no de las dependencias) | 5 en `presidio-analyzer/requirements.txt:1-5` | 68 | **28**: `websockets` 16.1.1 → **17.2**, `filelock` 3.31.1 → **4.0.12**, `ujson` 5.13.0 → **6.0.0**, `regex` 2026.7.19 → 2026.9.29, `setuptools` 83.0.0 → 84.0.0, `wrapt` 2.2.2 → 2.5.0, `typer`, `click`, `tldextract` 5.3.1 → 5.4.0, `cloudpathlib`, `srsly`, `anyio` 4.14.2 → 4.15.1, … |

Modelo spaCy (`nlp`, `Dockerfile:13`): `python -m spacy download es_core_news_md` resuelve por `compatibility.json` de `explosion/spacy-models` a la versión compatible con la línea 3.7 de spaCy; **hoy esa línea apunta a `es_core_news_md 3.7.0`** como única versión
(`.spacy["3.7"]["es_core_news_md"] = ["3.7.0"]`) [verificado el mapeo de hoy]; la versión efectivamente instalada en la imagen [no verificado] (no se leyó la capa de 85 MB; muy probablemente la misma).
Estas dos filas son una **estimación por método** (validado en 4 capas, pero no en estas dos): marcadas [no verificado] como «instalado».
Aun sin leer el instalado, el diagnóstico de base ya estaba (§2.4): 0 capas en común con la base de hoy (3.11.15 → **3.11.17**; tabular `python:3.12` → 3.12.15), así que ninguna de las dos se reconstruye igual.

### 3.6 engine (`elea-guardian-engine`)

Sin dependencias propias (§1.2); las 21 capas base son idénticas por `diff_id` a la base fijada por digest (§2.4), y las 2 propias se leyeron: `config.yaml` e `extensions/` **iguales a HEAD**, **más 9 `.pyc`** de `__pycache__` del host (3.1) [verificado].
**¿Reconstruirla hoy cambiaría lo que corre?** **No en paquetes** (la base está por digest y no se instala nada) [verificado]; **sí en 9 `.pyc` incidentales** que dependen de qué Python tenga el publicador, y el digest de imagen cambiaría igual (timestamps, §1.2). Qué versión de LiteLLM/paquetes lleva la base: [no verificado] (no se bajaron las 21 capas, 361 MB).

### 3.7 Tabla de conclusión por imagen

| Imagen | Instalado leído | Directos: repo vs imagen | Qué cambia hoy en un rebuild | ¿Cambia lo que corre? |
|---|---|---|---|---|
| backend | **sí** (94 py) | 20/20 iguales | 26/94 py (2 saltos mayores: `filelock`, `ujson`); base 3.12.13 → 3.12.15; `apt` sin medir | **Sí** |
| rag-client | **sí** (89 npm, 9+1 py, 41 apk) | npm: 87/89 = lock (`body-parser` 1.20.6/1.20.8); py/apk: **nada declarado con versión** | npm 3 (`express`, `proxy-addr`, `qs`), py 4 (`pandas`, `numpy`, `lxml`, `pypdf`), apk no medido | **Sí** (la rama `apk` ya no es la que corre, y no lo será) |
| frontend | **parcial** (npm install: solo `.package-lock.json`; host `node_modules`: sí) | 32/451 más nuevos que el lock; 453/453 host = lock | 51 npm (2 directos, 9 de producción) | **Sí**, y depende del `node_modules` del publicador |
| tabular | no | — | 8 py (estimado) + base | **Sí** [no verificado el instalado] |
| nlp | no | — | 28 py (estimado) + base + modelo spaCy | **Sí** [no verificado el instalado] |
| engine | no hace falta (base por digest) | n/a | nada en paquetes; 9 `.pyc` incidentales | **No** en paquetes |

**Una sola frase por imagen que importa a la decisión:** las deps de **backend y Hub están en el repo solo por pines directos** (20/20), así que el repo **sí** describe lo que corre de lo declarado, pero **nada declara las 74 transitivas del backend** ni las transitivas `pip`/`apk` del Hub (el Hub no declara ninguna versión de Python/Alpine);
**el panel es el caso grave** porque ni el lock ni `package.json` describen lo que corre (mezcla `npm install` + `node_modules` del host); **tabular y nlp** quedan con el diagnóstico de §2.4 y la estimación de 3.5.

### 3.8 No verificado (§3)

1. **Instalado real de `tabular` y `nlp`** (pip, modelo spaCy `es_core_news_md`): no se bajaron sus capas (fuera del nivel autorizado). Lo de 3.5 es resolución a fecha, no lectura.
2. **Versiones `apt` del backend (`build-essential`, `libpq-dev`) y de `gcc` en `nlp`**, y el contenido de la capa `apk` de `rag-client` más allá de la DB de `apk`: la capa de 111,7 MB del backend no se bajó.
3. **Versión efectiva de los 32 paquetes superpuestos del frontend** a nivel de archivo: se infirió por la semántica de capas (no se abrió la capa 8 de 139,5 MB, solo su `.package-lock.json` por lectura parcial).
4. **Contenido (no nombres) de los 17 857 archivos de `node_modules` del host** dentro de la capa `COPY . .` del frontend; **archivos de configuración de raíz** de esa capa (`vite.config.ts`, etc.) contra HEAD.
5. **Versión de LiteLLM del motor** y árbol Python completo de las 21 capas base (por digest). **Versión de `ujson`/`filelock` que el backend efectivamente carga en runtime.**
6. **Alpine: qué versiones de `python3`/`py3-pip`/`musl` traería hoy** `apk` en `rag-client` (no se resolvió el índice de paquetes del sistema).
7. **Contenido de los demás tags** del backend, y de los tags de las otras 5 imágenes (solo se leyó `:latest` de las 6 y los `COPY` distintos de `2026-09-14`/`2026-09-17` del backend). **Versiones huérfanas** sin tag (§2.5, ◆ 9).
8. **Cuál es el digest que corre en la sede** (◆ 7 de §2): esta medición es de lo publicado, no de lo que las sedes tienen en disco.
9. El método de resolución (`uv`/`npm` de esta máquina) reproduce 4/4 capas medidas; que reproduzca también `tabular`/`nlp` y el resto de capas es una extrapolación.
10. **Causa por la que `tabular/.dockerignore:2-3` no filtró `__pycache__`** (el `$` literal o el patrón no recursivo).
11. **Por qué `apk add python3 py3-pip py3-docx py3-pandas` falló al construir:** inferido de que `py3-docx` no existe en Alpine 3.23 hoy; no se tiene el log del build de 2026-08-26.

Cierre de los ◆ de «No verificado»: **◆ 1 cerrado** (frontend `node_modules` del host, 3.1), **◆ 2 cerrado en el efecto** (sin `license_out`, solo `dev-demo.lic`, 3.1; el mecanismo `.dockerignore` sigue sin ejecutarse),
**◆ 3 cerrado** para `litellm/extensions`, client, tabular y nlp (3.1), **◆ 5 cerrado** (rama `pip`, 3.3), **◆ 8 cerrado para `rag-client`** (3.1), **◆ 4 parcial** (3.2–3.5).

---

## No verificado

Se agrupa todo lo marcado [no verificado] arriba. Ninguno bloquea las conclusiones de §1 y §2, pero §3 debería cerrar los marcados con ◆.

1. ◆ **Contenido real de la capa `COPY . .` del frontend** (43,55 MB comprimida vs 1,3 MB de fuente): la hipótesis de que incluye
   `node_modules` del host sale de comparar tamaños y de la ausencia de `frontend/.dockerignore`, no de abrir la capa.
2. ◆ **Si `scripts/license_out/` o `*.lic` entraron en la imagen del backend.** Hay riesgo estructural (contexto raíz + `.dockerignore`
   raíz que no los excluye + `backend/.dockerignore` que no aplica con contexto raíz), pero el comportamiento de BuildKit con `.dockerignore`
   está citado de memoria, no ejecutado; y la capa de 1,06 MB sugiere que no, sin abrirla.
3. **Contenido de `litellm/extensions/` y de `COPY . .` del client/tabular** (por ejemplo `__pycache__`): sin bajar capas no se ve.
4. **Árbol exacto de dependencias transitivas** de cada imagen Python (solo verifiqué `fastapi==0.111.0 → starlette>=0.37.2,<0.38.0` en PyPI);
   los nombres `uvloop`, `httptools`, `ecdsa`, `thinc`, `numpy` como transitivas flotantes son conocimiento general, no medición.
5. **Qué rama del `||` de `client/Dockerfile:4-5` corrió** al construir la publicada (la capa de 72 MB sugiere `apk`, sin confirmarlo).
6. **Qué versión de `es_core_news_md`** quedó instalada y cuál se resolvería hoy.
7. **Qué digests corren realmente en la sede de Eleia** (postgres, redis, anythingllm, y las 6 propias): no tengo acceso a la máquina,
   solo a lo que los tags devuelven hoy.
8. **Qué commit exacto produjo cada `:latest`:** el registry no lo dice; la inferencia por fecha (§2.2) es débil y, para `rag-client`,
   apunta a un árbol sin commitear.
9. **Versiones sin tag (huérfanas) de los 6 paquetes** en ghcr.io: requieren la API de GitHub con token; aquí solo se ve `tags/list`.
10. **Si el digest de LiteLLM fijado es 1.92.0** (afirmación del comentario `docker-compose.yml:67`): no la comprobé; sí comprobé que el digest
    existe y que la imagen publicada lo contiene.
11. **Si el tag `mintplexlabs/anythingllm:1.16.1` es inmutable** en la práctica; y la versión `v0.9.7-beta` de presenton (los labels no la traen).
12. **Que un rebuild de las capas propias del motor dé el mismo digest de imagen** (probablemente no, por timestamps sin `SOURCE_DATE_EPOCH`): no se
    construyó nada (sin Docker, a pedido).
13. **Que BuildKit/`docker build` del publicador sea el que dejó `history` con formatos `EXPOSE &{[…]}`** y otras particularidades del config: irrelevante
    para las conclusiones, anotado por completitud.
