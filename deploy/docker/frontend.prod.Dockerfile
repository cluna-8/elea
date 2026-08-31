# Imagen de PRODUCCIÓN del frontend (spec 020 US1 — FR-002/FR-003).
# vite build en la etapa builder (node NO llega a la final); estáticos servidos
# por Caddy como non-root en :8080. Contexto de build: la RAÍZ del repo.
# La marca es CONFIG en runtime (US2): /branding se monta, no se hornea.

FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS builder

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
# `npm run build` (tsc && vite build) está roto en el árbol dev: nunca existió
# tsconfig.json (deuda dev-mode, ver spec 020 "estado actual"). vite build
# transpila el TS igual (esbuild); el typecheck se restituye cuando el frontend
# gane su tsconfig — sin bloquear el empaquetado ni tocar código de producto.
RUN npx vite build

FROM caddy:2-alpine@sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648

# Non-root: puerto >1024 y dirs de estado de Caddy escribibles por el usuario.
RUN addgroup -S sentinel && adduser -S -G sentinel -u 10001 sentinel \
    && mkdir -p /srv /data /config \
    && chown -R sentinel:sentinel /srv /data /config

COPY --from=builder /build/dist /srv
COPY deploy/docker/Caddyfile.frontend /etc/caddy/Caddyfile
RUN chown sentinel:sentinel /etc/caddy/Caddyfile

USER sentinel
EXPOSE 8080
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile"]
