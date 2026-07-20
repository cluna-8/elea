# Quickstart — 020 White-Label Packaging & Deploy

Validación end-to-end: perfil → apply EU → HTTPS → checks. Detalle de interfaces
en [contracts/client-profile.md](contracts/client-profile.md).

## 1. Buildear y validar los artefactos (sin cloud)

```bash
make -C deploy build      # imágenes prod (backend multistage + frontend estático)
make -C deploy check      # TODOS los checks: imágenes, marca blanca, secretos, tofu
```

## 2. Perfil de un cliente nuevo

```bash
cp -R deploy/clients/example deploy/clients/<slug>   # editar client.env/branding.env/seed.yaml
deploy/release/render_profile.sh <slug>              # config templado + brand.json + instance.env
```

## 3. Desplegar (cloud EU, OpenTofu)

Ver `deploy/terraform/README.md`: `tofu init` (backend s3 cifrado del
distribuidor) → `workspace new <slug>` → `apply -var-file=envs/<slug>/…`.
Región default EU; fuera de EU el apply FALLA sin `allow_non_eu=true`.
Outputs: `product_url` + `admin_bootstrap` (una vez, rotable con `-replace`).

El seed del perfil corre en la VM: `docker compose exec backend python
scripts/apply_profile_seed.py <slug> /profile/seed.yaml` (idempotente, 013).
La licencia (021) va montada por el perfil; registrar la génesis del onboarding
(`/api/v1/health/license` → `chain.genesis_license_id`).

## 4. Air-gapped (caso Elea)

`deploy/README.md` §on-prem: `bundle.sh` → mover → `docker load` → compose
`--profile selfhosted`. Sin registry en runtime; egress solo a proveedores (o
cero con modelo local).

## Validación e2e en sandbox (T040 — manual con credenciales)

Con credenciales AWS sandbox: `tofu apply` del workspace example en
`eu-central-1` debe dejar `https://<product_domain>` sirviendo la SPA con la
marca del perfil, `/api/v1/…` respondiendo, y `tofu output -raw
admin_bootstrap` como única emisión de la credencial. Checks post-apply:
`test_no_default_secrets.sh` + `test_secrets_not_in_state.sh` + región de
todos los recursos = EU.
