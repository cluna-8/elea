# Contrato: Perfil de Cliente + Interfaz del Módulo OpenTofu (T005)

Congela la interfaz entre el **perfil por cliente** (US3) y el **módulo OpenTofu** (US4).
Cambiarla = cambiar este doc primero (es un artefacto cross-party: lo rellena el distribuidor).

## Perfil de cliente (`deploy/clients/<slug>/`)

| Archivo | Contenido | ¿Secreto? |
|---|---|---|
| `client.env` | `TENANT_SLUG` (013 — deriva dominio/DNS/workspace), `PRODUCT_DOMAIN`, `REGION` (default `eu-central-1`), `IMAGE_SOURCE` (`registry`\|`tarball`), digests de imágenes (de `publish.sh`), `SENTINEL_DEPLOYMENT_TENANT_ID` | No |
| `branding.env` | Override del pack de marca (US2): `BRAND_NAME`, `BRAND_DOMAIN`, `BRAND_SUPPORT`, colores | No |
| `seed.yaml` | Onboarding-as-data → `seed_client` (013): tenant, clients, connections | No |
| `config.yaml.tmpl` | LiteLLM config TEMPLADO: `model_list`, proveedores, **región** — las keys de proveedor se referencian como `${VAR}` resueltas desde el store de secretos | Refs, no valores |
| `client.lic` | Token de licencia (021) emitido por Sentinel para el tenant | **Sí** (cifrado SOPS en tránsito) |

**Secretos** (US5): `POSTGRES_PASSWORD`, `LITELLM_MASTER_KEY`, `FERNET_SECRET_KEY`,
`JWT_SECRET_KEY`, keys de proveedores, `oauth_credential_ref` — **jamás en el perfil en
claro**: se generan por instalación (`random_password`) y viven cifrados (SOPS+age).

**Licencia (021 — implementada, NO placeholder)**: el perfil monta `client.lic` +
`deployment_key.pem` en el volumen `licenses` del compose prod; tras el primer arranque, el
onboarding registra la **génesis** (`/api/v1/health/license` autenticado → `chain.genesis_license_id`)
y la **pública** de la deployment key (true-up, FR-029 de la 021).

## Variables del módulo OpenTofu (entrada)

| Variable | Tipo | Default | Notas |
|---|---|---|---|
| `tenant_slug` | string | — (req.) | de 013; nombra workspace, DNS, recursos |
| `region` | string | `eu-central-1` | **validation: falla fuera de EU** salvo `allow_non_eu=true` (FR-021) |
| `allow_non_eu` | bool | `false` | override explícito y auditable |
| `product_domain` | string | — (req.) | FQDN del producto (Caddy auto-HTTPS) |
| `image_source` | string | `registry` | `registry` \| `tarball` (US6, FR-024) |
| `backend_image` / `frontend_image` / `litellm_image` | string | — (req.) | **pinneadas por digest** (publish.sh) |
| `profile_path` | string | — (req.) | ruta al perfil renderizado del cliente |
| `age_public_key` | string | — (req.) | destinatario SOPS de los secretos generados |
| `instance_type` | string | chico | dimensionamiento VM v1 |

## Outputs del módulo

| Output | Sensitive | Contenido |
|---|---|---|
| `product_url` | no | `https://<product_domain>` |
| `admin_bootstrap` | **sí** | credencial admin inicial, GENERADA y ROTADA por instalación, emitida una sola vez (FR-022/FR-027) |
| `postgres_endpoint` / `redis_endpoint` | no | endpoints gestionados (swap `POSTGRES_*`/`REDIS_*`) |

## Aislamiento (Principio III)

Un cliente = un workspace (`tofu workspace select <tenant_slug>`) + state remoto CIFRADO +
secretos propios. Nada se comparte entre clientes; el naming de todos los recursos deriva de
`tenant_slug`.
