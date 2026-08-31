# deploy/ — Empaquetado + IaC de marca blanca (spec 020)

**Modelo de negocio** (por qué este dir existe): Sentinel **vende INSTALL + X licencias y NO
instala ni opera servidores**. El comprador es un **distribuidor** que revende el producto
con SU marca y lo levanta donde quiera. El entregable es: imágenes de producción + branding
pack + perfil por cliente + **módulo OpenTofu** portable (MPL 2.0 — no Terraform-BSL) +
camino air-gapped. El enforcement de licencias es la **spec 021** (ya implementada): el
perfil cablea su bloque de env (ver `specs/021-licensing-seat-enforcement/quickstart.md`).

**Un codebase, dos perfiles** (edge case nº1 del spec — jamás dos codebases):

| Perfil | Artefacto | Uso |
|---|---|---|
| dev | `docker-compose.yml` (raíz) — bind-mounts, `--reload`, vite dev, secretos de juguete | SOLO desarrollo local |
| prod | `deploy/docker/*.prod.Dockerfile` — código horneado, non-root, sin toolchain ni `--reload` | lo ÚNICO que sale a un cliente |

Mapa del dir:

- `docker/` — Dockerfiles de producción + entrypoints (US1). Mismo árbol de código que dev.
- `branding/` — branding-as-config en runtime: env + assets montados (US2). Never fork.
- `clients/<slug>/` — perfil por cliente: env + seed (013) + branding + `config.yaml.tmpl`
  (US3). **Los secretos NO viven acá** (US5: generados por instalación, cifrados SOPS+age).
- `terraform/` — módulo **OpenTofu** portable (US4): network/database/cache/compute/secrets/
  ingress; región default **EU**; remote state + workspace por cliente. (El dir conserva el
  nombre `terraform/`: OpenTofu es drop-in sobre los mismos `.tf`.)
- `release/` — `publish.sh` (push pinneado tag+digest), `bundle.sh` (tarball air-gapped,
  US6) y `checks/` (validación de artefactos: la "suite de tests" de esta spec).

Validación: `make -C deploy check` corre todos los checks; cada uno también corre solo.

## Modo on-prem / air-gapped (US6, T038)

1. `publish.sh` en una máquina CON red → `bundle.sh <slug>` → `bundle-<slug>.tar.gz`.
2. Mover el tarball al host (USB/SFTP). `tar xzf` + `docker load -i images.tar`.
3. `docker compose -f compose.prod.yml --profile selfhosted --env-file profile/instance.env \
   --env-file secrets.env up -d` (Postgres/Redis en contenedor con volumen durable).

**Red**: el único egress necesario es hacia los proveedores LLM (via NAT/proxy);
con un modelo local (Ollama/vLLM en el `config.yaml` del perfil, 013) el egress
es **cero**. La verificación de licencia (021) es 100% offline — jamás llama a
casa. Camino k8s v2: **Zarf** (bundle con SBOM + firma cosign).

**Sitio de documentación (spec 022)**: viaja como una imagen más del release —
`sentinel-docs:<brand>-<version>` (build en `docs/`, una por marca) — dentro de
`images.tar` del bundle y, en el camino v2, del paquete Zarf igual que el resto
de imágenes pinneadas. Es 100% estático y 0-egress: funciona en air-gap sin
ninguna pieza extra (checks: `make -C deploy check-docs`).

**Analizador NLP (spec 016)**: viaja como imagen propia del release —
`sentinel-nlp-analyzer:<version>` (build en `presidio-analyzer/`, la publica
`publish.sh`) — y el compose prod la exige por `NLP_ANALYZER_IMAGE`. NO es
opcional: sin el servicio levantado y sin `NLP_ANALYZER_URL`, el motor detecta
PII con las regex de dev/demo en vez del modelo real, y el cliente no se entera
(Constraint SC-2 de la 016). Por eso la variable es `${…:?}`: preferimos que la
instalación falle a que enmascare de mentira. Con la URL puesta y el servicio
caído, el guardrail es fail-closed y rechaza la petición.
