# `sentinel/` — capa 2 (extensiones propias)

Código que la base (`guardian-secure`) no conoce: se engancha solo por costuras genéricas
(`docs/sentinel/05-ARQUITECTURA-DE-CAPAS.md`). Coste de merge: cero. Hoy contiene la política
de redireccionamiento de modelos (spec 068).

| Carpeta | Qué | Dónde corre |
|---|---|---|
| `redirect/` | resolver, residencia, caras, plugin de pasarela (`plugin.py`), API admin (`api/`), modelos y caché | backend |
| `engine/` | guard `redirect-guard`, autorización interna, credenciales por proveedor, fragmento de perfil y `fragment_merge.py` | motor (copiado plano a `extensions/`) |
| `migrations/` | rama Alembic propia `sentinel_redirect` (ids hash, RLS) | backend (arranque) |
| `docker/backend.Dockerfile` | imagen del backend de la base + este paquete | release |
| `tests/` | unit, contract, integration | local, sin Docker |

## Activación (apagada por defecto)

Estar desplegado no activa nada: sin estas variables el backend y el motor se comportan como
la base. Con ellas y **sin filas** en `sentinel_redirect_*`, tampoco cambia el tráfico (solo se
ocultan las entradas `rdx-*` de `/gw/v1/models`).

Archivo de entorno **solo en el servidor** (en nix: `~/bundle-nix/profile/extensions.env`,
modo 600, fuera del repo). `deploy.sh`/`rollback.sh` lo pasan a compose como `EXTRA_ENV_FILE`
(costura S12: `env_file` extra de backend y motor):

```dotenv
# backend
GATEWAY_PLUGINS=sentinel.redirect.plugin          # costura S2
PLUGIN_PACKAGES=sentinel.redirect.api             # costura S1 (/api/v1/redirect/*)
ALEMBIC_EXTRA_VERSION_LOCATIONS=/opt/sentinel-ext/sentinel/migrations   # costura S4
# backend y motor: autorización interna pasarela→motor (≥32 caracteres, dedicada)
REDIRECT_INTERNAL_KEY=<generar: openssl rand -base64 48>
# motor: credenciales de destinos de NIVEL INSTALACIÓN cargadas como `env:REDIRECT_CRED_<X>`
REDIRECT_CRED_<NOMBRE>=<secreto del proveedor>
# opcional: TTL de la caché de política (s, default 5)
REDIRECT_CACHE_TTL_S=5
# opcional: presupuesto propio de cada prueba de fidelidad (USD, default 0.50) y dirección pública
# de la pasarela que llevan los kits de cliente (default: la de la petición)
REDIRECT_FIDELITY_BUDGET_USD=0.50
REDIRECT_GATEWAY_URL=https://<host>/api/v1/gw
# opcional (backend): cabeceras `anthropic-beta` que se reenvían a un destino NATIVO (separadas por coma, leídas en
# cada pedido; sin definir o en blanco = el default acotado de `redirect/betas.py`; `none` = ninguna). Hacia un destino
# traducido nunca se reenvía ninguna (FR-040). Las betas que suben el costo, guardan archivos en el proveedor o
# ejecutan código no están en el default: se habilitan a propósito.
REDIRECT_BETA_ALLOWLIST=
```

- **Backend**: la imagen del release ya trae el paquete en `/opt/sentinel-ext` con
  `PYTHONPATH=/opt/sentinel-ext` (`docker/backend.Dockerfile`, paso del `release.yml`). En dev
  sin imagen derivada: montar `./sentinel` en `/opt/sentinel-ext/sentinel` y exportar
  `PYTHONPATH=/opt/sentinel-ext`.
- **Motor**: `deploy.sh` copia `engine/redirect_*.py` al volumen de config junto a
  `litellm/extensions/` y fusiona `engine/profile-fragment.yaml` en el `config.yaml`
  renderizado — **solo** si `GATEWAY_PLUGINS` del archivo de extensiones nombra este plugin.
- Las credenciales de destinos de tenant (BYOK) se cargan por la API y quedan cifradas con la
  clave de cifrado del backend; nunca se devuelven.

### Catálogo de modelos (spec 069)

Se suma a lo anterior con **una** línea (los routers del catálogo y de la redirección se montan juntos):

```dotenv
PLUGIN_PACKAGES=sentinel.redirect.api,sentinel.catalog.api
# opcional, apagado por defecto: el motor sirve del catálogo a los clientes que le hablan directo
# (Hub, tabular, presentaciones). Sin esto el motor sigue usando su archivo de configuración.
CATALOG_DIRECT_ENABLED=1
# opcional: rotación de la clave de cifrado de las credenciales (la vieja SOLO descifra)
FERNET_PREVIOUS_KEYS=<clave anterior>
```

`deploy.sh` migra los destinos de la 068 al catálogo y siembra el perfil
(`deploy/clients/nix/profile/catalog-seed.yaml`) **solo** si `PLUGIN_PACKAGES` nombra `sentinel.catalog.api`.
Runbook completo: `docs/sentinel/runbooks/activar-catalogo.md`.

## Tests

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python pytest pytest-asyncio cryptography pyyaml \
  "litellm[proxy]==1.92.0" fastapi httpx sqlalchemy alembic
cd sentinel/tests && ../../.venv/bin/python -m pytest -q          # núcleo, guard, migraciones
# pasarela real y API admin (necesitan el venv del backend):
../../backend/.venv/bin/python -m pytest -q integration/test_redirect_gateway_e2e.py \
  contract/test_redirect_admin_api.py
```
