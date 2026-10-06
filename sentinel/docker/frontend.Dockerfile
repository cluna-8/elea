# Variante `-ext` del panel publicado (spec 057 T091, research R27; costura S3, `@plugin-pages`).
# Deriva de la imagen que publica `deploy/release/publish-elea.sh` (`elea-guardian-frontend`,
# construida con `frontend/Dockerfile`): esa base SIRVE el panel con el servidor de desarrollo de Vite
# desde /app, así que acá no hay un `dist` que reemplazar. Se suman las páginas de la extensión dentro
# de /app (el servidor de Vite no sirve archivos fuera de su raíz) y `VITE_PLUGIN_PAGES_DIR`, que ya
# leen `vite.config.ts` y `tailwind.config.js`. CMD, puerto y proxy quedan los de la base.
# Contexto de build: la RAÍZ del repo (necesita `sentinel/frontend`).
#
#   docker build -f sentinel/docker/frontend.Dockerfile \
#     --build-arg BASE_IMAGE=<registry>/elea-guardian-frontend:<versión> -t <registry>/elea-guardian-frontend:<versión>-ext .
#
# Las páginas no activan nada: sin la extensión encendida en el servidor, la pantalla avisa que la
# redirección no está activada (la API responde 404). Los tests no entran.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY sentinel/frontend/pages /app/sentinel/frontend/pages
COPY sentinel/frontend/redirect /app/sentinel/frontend/redirect
COPY sentinel/frontend/catalog /app/sentinel/frontend/catalog
COPY sentinel/frontend/models /app/sentinel/frontend/models
COPY sentinel/frontend/routing /app/sentinel/frontend/routing
# Las páginas importan `../../../frontend/src/...` (de /app/sentinel/frontend/<carpeta> a /app/frontend/src):
# un ENLACE a /app/src, no una copia, para que sea el MISMO módulo (sesión, componentes) que usa la consola.
RUN rm -rf /app/sentinel/frontend/redirect/__tests__ /app/sentinel/frontend/catalog/__tests__ \
    /app/sentinel/frontend/models/__tests__ /app/sentinel/frontend/routing/__tests__ \
    && mkdir -p /app/frontend && ln -s /app/src /app/frontend/src
ENV VITE_PLUGIN_PAGES_DIR=/app/sentinel/frontend/pages
# Build de verificación (se descarta): si las páginas no entran a la consola, la imagen no se construye.
RUN cd /app && npx vite build --outDir /tmp/ext-verify --emptyOutDir \
    && grep -q "Dar de alta modelos" /tmp/ext-verify/assets/*.js \
    && grep -q "Más barato primero" /tmp/ext-verify/assets/*.js \
    && rm -rf /tmp/ext-verify
