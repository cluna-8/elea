# Imagen del frontend CON las páginas de consola de la capa 2 (spec 068; costura S3,
# `@plugin-pages`). Deriva de la imagen de producción de la base
# (deploy/docker/frontend.prod.Dockerfile, que no se toca): re-hace el `vite build` de la MISMA
# consola con VITE_PLUGIN_PAGES_DIR apuntando a sentinel/frontend/pages y reemplaza /srv.
# Caddy, su config, el usuario non-root y el puerto quedan los de la base.
# Contexto de build: la RAÍZ del repo.
#
#   docker build -f sentinel/docker/frontend.Dockerfile \
#     --build-arg BASE_IMAGE=<registry>/sentinel-frontend:<version> -t <mismo tag> .
#
# Las páginas no activan nada: sin la extensión encendida en el servidor, la pantalla avisa
# que la redirección no está activada (la API responde 404). Los tests no entran.
ARG BASE_IMAGE

FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
COPY sentinel/frontend/pages /build/sentinel/frontend/pages
COPY sentinel/frontend/redirect /build/sentinel/frontend/redirect
COPY sentinel/frontend/catalog /build/sentinel/frontend/catalog
COPY sentinel/frontend/models /build/sentinel/frontend/models
COPY sentinel/frontend/routing /build/sentinel/frontend/routing
RUN rm -rf /build/sentinel/frontend/redirect/__tests__ /build/sentinel/frontend/catalog/__tests__ \
    /build/sentinel/frontend/models/__tests__ /build/sentinel/frontend/routing/__tests__
# Relativo a frontend/ (vite.config.ts y tailwind.config.js lo resuelven desde ahí).
ENV VITE_PLUGIN_PAGES_DIR=../sentinel/frontend/pages
RUN npx vite build && grep -q "Dar de alta modelos" dist/assets/*.js && grep -q "Más barato primero" dist/assets/*.js

FROM ${BASE_IMAGE}
USER root
RUN rm -rf /srv/*
COPY --from=builder --chown=sentinel:sentinel /build/frontend/dist /srv
USER sentinel
