# Roadmap — Install & Factory

**Jefe técnico**: Falime (@FalimeJ) · **Creado**: 2026-08-04 (la mudanza)
**Punto de desprendimiento**: tag **`checkpoint-camara-2026-08`** en `main` (`78637e6`) — el estado
instalado y probado en la sede de la Cámara + fixes post-install + los 4 PRs del gate (#53-#56).
Cuando este departamento migre a su repo propio (`guardian-factory`), este archivo viaja con `deploy/`.

Este roadmap vive **dentro de `deploy/`** a propósito: es el territorio de Install & Factory. El roadmap
del producto (Guardian App Ecosystem, JF) sigue en [`specs/ROADMAP-guardian.md`](../specs/ROADMAP-guardian.md).
Los dos se conectan por **contratos**, no por acceso: el dueño publica el artefacto versionado, el otro lo
consume pinneado.

## Contratos con Guardian App Ecosystem (lo que Factory consume, nunca lee del árbol)

| Contrato | Artefacto | Estado hoy |
|---|---|---|
| Imágenes de producto | digests pinneados (backend, frontend, nlp, docs) | `publish.sh` ya imprime PINNED |
| Lib licensing | `backend/src/licensing` versionada por tag (fuente única, regla 4 — SIN copias) | import in-tree; empaquetar al migrar |
| Engine-extensions | pack de `litellm/extensions/*.py` por release + `contract_checks.py` como gate | copia por ruta en `bundle.sh:96`; artefactualizar |
| Extensión navegador | runtime-pack neutro + campos de manifest que el render puede tocar | render sobre copia ya funciona |
| Docs | `openapi.json` + config-reference como assets de release | decidido en la 022; publicar |
| Perfiles de cliente | schema de `seed.yaml`/`client.env`/`brand.json`; `PROFILES_ROOT` soporta repo externo | precedente vivo: `sentinel-partner-camara` |
| Keyset de licencias | `sentinel_public_keys.pem` + procedimiento de rotación de `kid` (**gate Cristian**) | horneado en imagen; desacoplar vía `SENTINEL_LICENSE_PUBLIC_KEYS_FILE` |
| Runtime del compose | catálogo de envs por imagen (obligatoriedad + paridades, p.ej. `SENTINEL_AUDIT_FAIL`, `NLP_ANALYZER_URL`×2) | artesanal en `render_profile.sh` |

## Features

| Spec | Título | Prioridad | Estado |
|------|--------|-----------|--------|
| 020 | White-Label Packaging & Deploy (OpenTofu + k3s/Zarf) | P2 | **Implementada** (US1-US6, 2026-07-20, [PR #23](https://github.com/DrZuzzjen/sentinel-guardian/pull/23)); resta T040 (tofu apply e2e sandbox) |
| 025 | Partner Enablement (capacitación + certificación del partner) | P2 | **Implementada** (2026-07-22, [PR #36](https://github.com/DrZuzzjen/sentinel-guardian/pull/36)); doc oficial del ciclo de onboarding |
| 026 | CLI de operador `sentinel-admin` — firma de licencias e instalación guiada offline | **P1** | **Spec+plan completos, implementación EN CERO** — habilitador del partner instalando en septiembre |
| 032 | Ingress cert modes (`managed` \| `byo` \| `internal`) | **P1** | **Roadmap — sin spec** (research 2026-07-30, veredicto en [#51](https://github.com/DrZuzzjen/sentinel-guardian/issues/51)); primer ladrillo del plano de control del futuro Vendor Portal |
| — | Trust-kit TLS del certificado | **P1** | Mergeado ([PR #55](https://github.com/DrZuzzjen/sentinel-guardian/pull/55)); **pendiente: pasada en VM Windows real** (UAC, almacén de máquina, GPO, `IsInputRedirected` como SYSTEM) antes de entregarlo a la sede; instaladores sin firma → [#61](https://github.com/DrZuzzjen/sentinel-guardian/issues/61) |
| — | Camino de update v0 (bundle-parche + procedimiento) | **P1** | No existe — hoy solo reinstalación fresca. Prerrequisito del zero-day O(N) del partner |
| — | CI/CD y convención de releases | **P1** | No existe (`.github/` = solo CODEOWNERS); los 20 checks de `deploy/release/checks/` corren a mano |
| — | Vendor Portal | oct+ | Su lógica se entrega vía CLI 026; la cara web llega sobre la CLI probada en campo. 100% Factory |

## Operativa heredada de la sesión del 04-ago

- **Drop de imagen a la sede Cámara** con los fixes acumulados (la sede corre la imagen previa a `1151b1e`).
- **Acceso remoto a la sede** (VPN/túnel/Tailscale) con Rafa — hoy el soporte es a ciegas.
- **Licencias, operativa entera**: emisión/cupos/true-up (la lib es de Guardian; la operación es de acá).
- Los scripts de emisión (`issue_license.py`, `issue_dev_license.py`, `generate_trueup.py`) hoy viajan
  **horneados en la imagen prod** (`backend.prod.Dockerfile:38`) — su hogar definitivo es la CLI 026;
  purgarlos de la imagen es prerequisito de cualquier separación seria.

## Narrativas de specs (movidas de ROADMAP-guardian el 2026-08-04)

### 020 — White-Label Packaging & Deploy (P2)
Empaquetado para el modelo distribuidor marca-blanca: Dockerfiles de producción + imágenes / tarball air-gapped,
branding **config-as-data** (never fork), perfil por cliente, módulo IaC portable. Research build-vs-buy: **OpenTofu**
(no Terraform, por BSL + HashiCorp=IBM al entregar a terceros); v1 = VM + docker compose + Caddy + SOPS/age;
v2 = **k3s + Helm + Zarf** (ECS Anywhere **no** corre air-gapped). Secretos por instalación (D5). Runbook en
`docs/whitelabel-deployment.md`. **Addendum 2026-07-14**: tarball air-gap **validado por el mercado**
(Harbor/GitLab/Replicated hacen lo mismo); registry privado autenticado = watch-item v2 como canal de entrega
para clientes conectados, **nunca** como enforcement (post-pull un `docker save` lo anula — el gate de pago es
la licencia 021 en runtime). Segundo punto de contacto con la 021: el deploy provisiona el **volumen/secret de
la deployment key** (par del install que firma los true-up; FR-032/T042), sin lógica de licencias acá.

### 025 — Partner Enablement (P2, doc oficial)
Página GUÍA del programa de capacitación y certificación del partner en la documentación de producto:
etapas (formación → práctica → 2-3 installs acompañados → certificación), prerequisitos del ingeniero,
checklist de autonomía y tabla quién-hace-qué post-certificación. **Filtro editorial FR-007**: la doc se
vende → cero economía interna del fabricante (FTE/horas/costos); esa parte vive solo en el doc ejecutivo.

### 026 — CLI de operador `sentinel-admin` (P1, habilitador del partner)
Una **CLI local, offline y airgap-safe** que le da cara humana a las operaciones que hoy son
**scripts sueltos con foot-guns** (inventario 2026-07-22: 54 operaciones; ver
`specs/026-cli-operador-sentinel/inventario-scripts.md`). MVP acotado a **firma de licencias**
(el primer ladrillo — hoy `issue_dev_license.py` regenera el keyset y **invalida cajas ya
instaladas** en cada corrida) e **instalación guiada** de un cliente hasta stack corriendo y
verificado (perfil → secretos → bundle → up → seed → licencia → admin → verify), con
validación, dry-run y confirmaciones. **Absorbe #33** (firma prod, pre-portal) y **#34**
(password admin sin SQL crudo). No rompe airgap: produce/consume archivos, cero phone-home;
los comandos que necesitan red (build/publish/cloud) quedan separados y marcados, nunca en la
caja del cliente. Fase 2: `ops` día-2 (rotación, true-up, backup), `cloud`, docs brand.
Frontera con seguridad (custodia de claves, RBAC de firma) → **gate de Cristian**.

### 032 — Ingress cert modes (`INGRESS_CERT_MODE=managed|byo|internal`) (P1, sin spec)
La decisión que resuelve TLS y cert-en-Windows de un golpe. En `managed` el VPS de control emite por
DNS-01 un certificado público por cliente y el appliance lo baja autenticado con su licencia; el cliente
sólo agrega **un registro A** en su DNS interno y **no se instala nada en ningún puesto**. `byo`
(CSR / AD CS) es la única vía air-gap sostenible con la vida de los certs cayendo a 47 días en 2029;
`internal` es lo de hoy, productizado. Las tres convergen en el mismo cambio del `Caddyfile.ingress`.
**Es además el primer ladrillo real del portal de partners**: usa el mismo plano de control que el
«firmante central» de FR-030. Research completo en [#51](https://github.com/DrZuzzjen/sentinel-guardian/issues/51).

## Mantenimiento

Misma regla de la casa que el roadmap de producto: **el estado se actualiza en el mismo PR que mergea**.
