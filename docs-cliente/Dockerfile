# Sirve el sitio de documentación del CLIENTE final (admin de la organización +
# usuarios) en el contenedor `docs` del stack, en lugar del sitio de producto
# (distribuidores/operadores). Hereda nginx y su config del sitio de producto:
# solo cambia el contenido servido.
#
# El contexto de build debe contener `site/` (salida de
# `mkdocs build -f mkdocs.yml -f mkdocs.<cliente>.yml`).
#
# Build:  docker build --build-arg BASE_IMAGE=sentinel-docs:prod \
#           -t sentinel-docs-cliente:<cliente> -f Dockerfile <contexto-con-site/>
# Pinneo: DOCS_IMAGE=sentinel-docs-cliente:<cliente> en deploy/clients/<cliente>/client.env
# (el compose toma DOCS_IMAGE de env: es dato del cliente, no código).
# Institucionalización del pipeline completo: issue #47.
ARG BASE_IMAGE=sentinel-docs:prod
FROM ${BASE_IMAGE}
# La base corre como nginx (unprivileged, :8080); el html root es de root.
USER root
RUN rm -rf /usr/share/nginx/html/*
COPY site/ /usr/share/nginx/html/
USER nginx
