# Variante `-ext` del motor publicado (spec 057 T091, research R27, R29). Deriva de la imagen que
# publica `deploy/release/publish-elea.sh` (`elea-guardian-engine`, construida con `litellm/Dockerfile`,
# que ya trae `/app/config.yaml` y `/app/extensions/`) y le suma lo de la extensión:
#   · `redirect_*.py` junto a las extensiones de la base (el guard `redirect-guard` y su autorización);
#   · el `config.yaml` con el fragmento de perfil fusionado AL FINAL (contrato S11, el mismo
#     `deploy/release/fragment_merge.py` que usan los perfiles de cliente): `redirect-guard` queda
#     después de `sentinel-guardian`;
#   · `pypdf` con versión exacta y hashes, para el camino de PDF del enmascarado forzado (S14).
# Contexto de build: la RAÍZ del repo (necesita `sentinel/engine` y `deploy/release/fragment_merge.py`).
#
#   docker build -f sentinel/docker/engine.Dockerfile \
#     --build-arg BASE_IMAGE=<registry>/elea-guardian-engine:<versión> -t <registry>/elea-guardian-engine:<versión>-ext .
#
# ENTRYPOINT, usuario y puerto son los de la base. Nada se activa por estar en la imagen: los `rdx-*`
# rechazan todo pedido sin autorización interna y el guard no actúa sin REDIRECT_INTERNAL_KEY.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}

COPY sentinel/engine/redirect_*.py /app/extensions/
COPY deploy/release/fragment_merge.py /tmp/ext/fragment_merge.py
COPY sentinel/engine/profile-fragment.yaml /tmp/ext/profile-fragment.yaml
COPY sentinel/docker/engine-requirements.txt /tmp/ext/engine-requirements.txt
# El Python de la base es un venv creado con `uv` y no trae pip: se arranca con `ensurepip` (viene con
# el intérprete, sin red) y se desinstala al terminar, para no dejar una herramienta que la base no tiene.
RUN python3 /tmp/ext/fragment_merge.py /app/config.yaml /tmp/ext/profile-fragment.yaml \
    && python3 -m ensurepip --default-pip \
    && python3 -m pip install --no-cache-dir --no-deps --require-hashes -r /tmp/ext/engine-requirements.txt \
    && python3 -c "import pypdf; from pypdf import Configuration" \
    && python3 -m pip uninstall -y pip \
    && rm -rf /tmp/ext
