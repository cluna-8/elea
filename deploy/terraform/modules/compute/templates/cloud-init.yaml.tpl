#cloud-config
# Arranque de la instalación (spec 020 US4 v1). Deja el producto corriendo por
# HTTPS: compose prod (imágenes pinneadas) + Caddy terminando TLS en 443.
# secrets.env queda 0600 root; nada de secretos en logs de cloud-init.
package_update: true
packages: [docker.io, docker-compose-v2, curl]

write_files:
  - path: /opt/basa/compose.prod.yml
    permissions: "0644"
    content: |
      ${indent(6, compose_prod)}
  - path: /opt/basa/instance.env
    permissions: "0644"
    content: |
      ${indent(6, instance_env)}
  - path: /opt/basa/secrets.env
    permissions: "0600"
    content: |
      POSTGRES_HOST=${postgres_host}
      POSTGRES_DB=${postgres_db}
      POSTGRES_USER=${postgres_user}
      POSTGRES_PASSWORD=${postgres_password}
      REDIS_HOST=${redis_host}
      LITELLM_MASTER_KEY=${litellm_master_key}
      FERNET_SECRET_KEY=${fernet_secret_key}
      JWT_SECRET_KEY=${jwt_secret_key}
      BACKEND_IMAGE=${backend_image}
      FRONTEND_IMAGE=${frontend_image}
      LITELLM_IMAGE=${litellm_image}
      NLP_ANALYZER_IMAGE=${nlp_analyzer_image}
  - path: /opt/basa/branding/brand.json
    permissions: "0644"
    content: |
      ${indent(6, brand_json)}
  - path: /opt/basa/litellm/config.yaml
    permissions: "0644"
    content: |
      ${indent(6, litellm_config)}
  - path: /opt/basa/Caddyfile
    permissions: "0644"
    content: |
      ${product_domain} {
        handle /api/* {
          reverse_proxy backend:8000
        }
        handle /gw/* {
          reverse_proxy backend:8000
        }
        handle {
          reverse_proxy frontend:8080
        }
      }
  - path: /opt/basa/compose.ingress.yml
    permissions: "0644"
    content: |
      services:
        caddy:
          image: caddy:2-alpine
          restart: unless-stopped
          ports: ["443:443", "80:80"]
          volumes:
            - /opt/basa/Caddyfile:/etc/caddy/Caddyfile:ro
            - caddy_data:/data
      volumes:
        caddy_data:

runcmd:
  - systemctl enable --now docker
  # tarball (US6/FR-024): las imágenes llegan por bundle, no por registry.
  - |
    if [ "${image_source}" = "tarball" ] && [ -f /opt/basa/images.tar ]; then
      docker load -i /opt/basa/images.tar
    fi
  - mkdir -p /opt/basa
  - cp /opt/basa/branding/brand.json /opt/basa/brand.json || true
  - cd /opt/basa && docker compose -f compose.prod.yml -f compose.ingress.yml \
      --env-file instance.env --env-file secrets.env up -d
