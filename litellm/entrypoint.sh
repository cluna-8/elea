#!/bin/sh
# Arranque del motor: deriva el modelo de `router-embeddings` y lanza litellm con los args recibidos.
#
# Por qué existe: el NOMBRE DE DESPLIEGUE de Azure lo elige quien crea el recurso (en Elea es
# `text-embedding-3-large-azure-openai`). LiteLLM solo resuelve `os.environ/X` como valor COMPLETO de una
# clave de `litellm_params` —no interpola dentro de `azure/…`— y, si X no existe, deja `model` en None y
# el motor no arranca. Entonces `config.yaml` lee ROUTER_EMBEDDINGS_MODEL y acá se la arma a partir de
# ROUTER_EMBEDDINGS_DEPLOYMENT (la que el operador define en .env), con el default de siempre:
# sin la variable, o vacía, nada cambia respecto de las instalaciones anteriores.
: "${ROUTER_EMBEDDINGS_DEPLOYMENT:=text-embedding-3-large}"
ROUTER_EMBEDDINGS_MODEL="azure/${ROUTER_EMBEDDINGS_DEPLOYMENT}"
export ROUTER_EMBEDDINGS_MODEL
exec litellm "$@"
