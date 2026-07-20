# Módulo OpenTofu (spec 020 US4)

Se ejecuta con **tofu** (OpenTofu, MPL 2.0) — no con terraform (BSL). El dir se
llama `terraform/` por convención: los `.tf` son drop-in.

## Un cliente nuevo (workspaces por cliente, FR-023)

```bash
cd deploy/terraform
tofu init -backend-config="bucket=<state-bucket-cifrado>" \
          -backend-config="key=basa/terraform.tfstate" \
          -backend-config="region=eu-central-1" \
          -backend-config="encrypt=true"
tofu workspace new <tenant-slug>          # state AISLADO por cliente (III)
../release/render_profile.sh <tenant-slug>
tofu apply -var-file=envs/<tenant-slug>/<tenant-slug>.tfvars
tofu output product_url
tofu output -raw admin_bootstrap          # UNA vez; rotar con -replace (FR-027)
```

- **Región**: default EU; fuera de EU el apply FALLA salvo `allow_non_eu=true`.
- **Secretos**: generados por instalación (módulo `secrets`), sensitive en un
  state REMOTO CIFRADO; el `.lic` y las keys de proveedor viajan en el perfil
  cifrados con SOPS+age. Cero defaults (checks en `../release/checks/`).
- **Bump de imágenes**: correr `publish.sh`, pegar los digests en el tfvars,
  `tofu apply` (la VM recrea el compose con las imágenes nuevas).
- **v2 roadmap**: el módulo `compute` (VM+cloud-init) se reemplaza por
  k3s+Helm+Zarf sin tocar network/database/cache/secrets/ingress.
