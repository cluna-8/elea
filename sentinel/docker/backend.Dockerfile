# Variante `-ext` del backend publicado (spec 057 T091, research R27): deriva de la imagen que
# publica `deploy/release/publish-elea.sh` (`elea-guardian-backend`, construida con
# `backend/Dockerfile.standalone`) y le suma el paquete `sentinel/`. La imagen base no se toca.
# Contexto de build: la RAÍZ del repo (necesita `sentinel/` y `deploy/redirect-seeds/`).
#
#   docker build -f sentinel/docker/backend.Dockerfile \
#     --build-arg BASE_IMAGE=<registry>/elea-guardian-backend:<versión> -t <registry>/elea-guardian-backend:<versión>-ext .
#
# Solo se hornea código y datos: nada se ACTIVA por estar en la imagen. La extensión se enciende por
# entorno (archivo extra de S12): GATEWAY_PLUGINS, PLUGIN_PACKAGES, ALEMBIC_EXTRA_VERSION_LOCATIONS,
# REDIRECT_INTERNAL_KEY y REDIRECT_SEED_FILES. Sin ellas la imagen se comporta igual que la base.
# Sin `sentinel/onboarding` (asistente de instalación de Sentinel) ni los tests.
#
# Usuario: la imagen base de Eleia (backend/Dockerfile.standalone) no declara USER, así que esta
# tampoco lo cambia ni hace chown: los archivos quedan legibles para cualquier usuario.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY sentinel/__init__.py /opt/sentinel-ext/sentinel/__init__.py
COPY sentinel/redirect /opt/sentinel-ext/sentinel/redirect
COPY sentinel/catalog /opt/sentinel-ext/sentinel/catalog
COPY sentinel/common /opt/sentinel-ext/sentinel/common
COPY sentinel/access /opt/sentinel-ext/sentinel/access
# `sentinel.redirect.authz` importa de aquí; el motor recibe los `redirect_*.py` por su propia imagen -ext.
COPY sentinel/engine /opt/sentinel-ext/sentinel/engine
COPY sentinel/migrations /opt/sentinel-ext/sentinel/migrations
# Seeds de la instalación (regiones, habilitación): los carga el arranque de la extensión con
# REDIRECT_SEED_FILES=/opt/sentinel-ext/seeds/<archivo>.
COPY deploy/redirect-seeds /opt/sentinel-ext/seeds
# `sentinel` importable desde el backend (que corre con /app como cwd y paquete `src`).
ENV PYTHONPATH=/opt/sentinel-ext
# Vocabulario cl100k_base de tiktoken HORNEADO: sin él, con la red cerrada del servidor, el conteo de
# tokens de la extensión caería en silencio a caracteres/4 (QA re-análisis L9).
ENV TIKTOKEN_CACHE_DIR=/opt/sentinel-ext/tiktoken
RUN find /opt/sentinel-ext -name '__pycache__' -prune -exec rm -rf {} + \
    && mkdir -p "$TIKTOKEN_CACHE_DIR" \
    && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
    && test -n "$(ls -A "$TIKTOKEN_CACHE_DIR")" \
    && chmod -R a+rX /opt/sentinel-ext
