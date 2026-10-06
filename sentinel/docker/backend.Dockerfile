# Imagen del backend CON la capa 2 (research D21): deriva de la imagen de producción de la base
# (deploy/docker/backend.prod.Dockerfile, que no se toca) y le suma el paquete `sentinel/`.
# Contexto de build: la RAÍZ del repo.
#
#   docker build -f sentinel/docker/backend.Dockerfile \
#     --build-arg BASE_IMAGE=<registry>/sentinel-backend:<version> -t <mismo tag> .
#
# Solo se hornea código: nada se ACTIVA por estar en la imagen. La extensión se enciende por
# entorno (archivo extra de S12): GATEWAY_PLUGINS, PLUGIN_PACKAGES,
# ALEMBIC_EXTRA_VERSION_LOCATIONS y REDIRECT_INTERNAL_KEY. Sin ellas la imagen se comporta
# igual que la base. Los tests de la extensión no entran.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

USER root
COPY sentinel/__init__.py /opt/sentinel-ext/sentinel/__init__.py
COPY sentinel/redirect /opt/sentinel-ext/sentinel/redirect
COPY sentinel/catalog /opt/sentinel-ext/sentinel/catalog
COPY sentinel/common /opt/sentinel-ext/sentinel/common
COPY sentinel/access /opt/sentinel-ext/sentinel/access
COPY sentinel/onboarding /opt/sentinel-ext/sentinel/onboarding
COPY sentinel/engine /opt/sentinel-ext/sentinel/engine
COPY sentinel/migrations /opt/sentinel-ext/sentinel/migrations
# `sentinel` importable desde el backend (que corre con /app como cwd y paquete `src`).
ENV PYTHONPATH=/opt/sentinel-ext
RUN find /opt/sentinel-ext -name '__pycache__' -prune -exec rm -rf {} + \
    && chown -R sentinel:sentinel /opt/sentinel-ext
USER sentinel
