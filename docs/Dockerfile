# Imagen de PRODUCCIÓN del sitio de docs (spec 022 US1, FR-001) — multi-stage:
# build MkDocs+Material (con red: el plugin `privacy` EMBEBE los assets externos)
# → nginx estático non-root SIN toolchain. En runtime: 0 egress (SC-001).
# Mismo builder pinneado que el backend prod (020).
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS build

WORKDIR /src
COPY requirements-docs.txt ./
RUN pip install --no-cache-dir -r requirements-docs.txt

# Config base + overlays de marca (mkdocs.<brand>.yml, US3) + brand-packs generados
# (docs/brand/<slug>/, derivados del brand-pack de la 020 por render_docs_brand.sh).
# ARG BRAND elige la marca en build — una imagen POR MARCA (never fork, FR-012):
# copia el css/logo de la marca SOBRE los assets neutros y compila con su overlay.
COPY mkdocs*.yml ./
COPY brand ./brand
COPY docs ./docs
ARG BRAND=""
RUN if [ -n "$BRAND" ]; then \
        cp brand/"$BRAND"/* docs/assets/brand/ && CONFIG="mkdocs.$BRAND.yml"; \
    else CONFIG=mkdocs.yml; fi \
    && mkdocs build --strict -f "$CONFIG" -d /out/site

# ── runtime: nginx estático, non-root, sin ACME (el TLS lo termina el ingress, FR-023) ──
FROM nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de

COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /out/site /usr/share/nginx/html

USER nginx
EXPOSE 8080
