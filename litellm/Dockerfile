# Imagen del motor con la config y las extensiones YA HORNEADAS adentro — para
# distribuir el Guardian como imagen, sin exponer `litellm/extensions/*.py` (la
# política real: PII, AI-Act, secretos) como código fuente legible fuera de la imagen.
# Pin por digest heredado del docker-compose de desarrollo (Principio VI): al
# actualizar, correr la suite de contract tests antes de commitear el digest nuevo acá.
FROM ghcr.io/berriai/litellm:main-latest@sha256:80ea654c506da9083503d00c1b323b2fecddf17af6add9bf01b2603938e17bd2

COPY config.yaml /app/config.yaml
COPY extensions/ /app/extensions/

ENTRYPOINT ["litellm", "--config", "/app/config.yaml"]
