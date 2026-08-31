# Implementation Plan: CLI de operador (`sentinel-admin` + `sentinel-admin-signer`) — firma de licencias e instalación guiada offline

**Branch**: `026-cli-operador-sentinel` | **Date**: 2026-07-22 | **Last revised**: 2026-08-05 (re-plan tras Clarifications) | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/026-cli-operador-sentinel/spec.md`

## Summary

Construir **dos artefactos Python físicamente separados** que reemplazan los scripts
sueltos con foot-guns por comandos guiados (decisión definitiva, spec.md § Clarifications
— Session 2026-08-05, FR-016 a FR-023):

- **`sentinel-admin-signer`** — herramienta interna de Sentinel. Corre únicamente en la estación
  de firma aislada. Emisión `.lic` por flags con keyset intacto por defecto, privada como
  PKCS8 cifrado, ledger local de emisiones, export/rotación del keyset. **Nunca** se
  entrega a partners/clientes ni viaja en el bundle air-gapped.
- **`sentinel-admin`** — herramienta de partner/cliente. Instalación guiada de un cliente
  hasta stack corriendo y verificado (perfil → secretos → bundle → up → seed →
  licencia+génesis → admin → verify). **No contiene físicamente** código de emisión,
  custodia de la privada de Sentinel, ni comandos exclusivos de firma — ni como módulo
  transitivamente importable.

Decisión de lenguaje (JF): **Python** para ambos artefactos — el emisor (`sentinel-admin-signer`)
**importa la lib de licensing existente** (`canonical_payload_bytes`, `verifier.py`), así
que el riesgo de divergencia emisor↔verificador desaparece **por construcción** (la
alternativa Go quedó evaluada, verificada y archivada en research). Distribución: **dos
zipapps `.pyz` single-file independientes** — solo el `.pyz` de `sentinel-admin` (por
arquitectura x86_64/arm64) viaja dentro del bundle air-gapped; `sentinel-admin-signer` se
construye y se queda en la máquina de firma de Sentinel, jamás en el bundle. La separación se
aplica en **build time** (dos paquetes Python, dos targets de build) y se verifica con
tests: un contract test para `sentinel-admin-signer` y un test de inspección de artefacto que
falla el build si `sentinel-admin` arrastra módulos/símbolos del signer (FR-020). Patrón de
integración compartido por ambos: **"la CLI orquesta, los entrypoints ejecutan dominio"**
— cada CLI hace archivos/docker en su propio proceso; los entrypoints `python -m`
endurecidos (flags, dry-run, confirmación) corren dentro del contenedor backend para todo
lo que toca SQLAlchemy. Absorbe #33 (pre-portal) y #34. Detalle: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11+ para ambos artefactos (el mismo del backend;
prerrequisito documentado del host de instalación — se añade al perfil del partner en la
doc 025). `sentinel-admin-signer` corre en la estación de firma de Sentinel (mismo prerrequisito,
sin restricción de arquitectura salvo la del puesto de trabajo real).

**Primary Dependencies**: **click** (árbol de comandos, prompts/confirm, `CliRunner` para
tests) en ambos artefactos + **cryptography** (firma/custodia/verificación — ya es
dependencia del producto) en ambos. `backend/src/licensing/` **como fuente única**, pero
con **import selectivo por artefacto** (research.md D6): `verifier.py`, `token.py`
(`canonical_payload_bytes`, `LicenseToken`), `deployment_key.py` y `trueup_export.py` no
tocan la privada del emisor de Sentinel → elegibles para `sentinel-admin`. La custodia/firma con
la privada del emisor (`keycustody.py`, `signing.py`, ledger de emisiones) es código
**nuevo, exclusivo de `sentinel-admin-signer`**, nunca importado por `sentinel-admin`. Cero
dependencias de red en el núcleo de ninguno de los dos.

**Storage**: archivos locales únicamente — `.lic`, keyset PEM (formato `# key_id:` del
verifier), privada del emisor como **PEM PKCS8 cifrado** (`BestAvailableEncryption`, 0600,
O_EXCL) **solo dentro de `sentinel-admin-signer`**, ledger de emisiones (lado Sentinel,
`sentinel-admin-signer`) y audit-log local por máquina (ambos artefactos, cada uno el suyo)
como JSONL append-only hash-encadenado. **Cero esquema nuevo** en la DB del producto.

**Testing**: pytest end-to-end por paquete — unit del emisor/custodia/render, `CliRunner`
para flujos de comandos, **contract test del artefacto `sentinel-admin-signer`** (firma → el
backend del stack valida: cubre el empaquetado, no solo el código — FR-020), **test de
inspección de artefacto de `sentinel-admin`** (build time: falla si el `.pyz` contiene
módulos/símbolos/dependencias exclusivos del signer, o cualquier flag/env-var de
role-gating — FR-019/FR-020), **test de contenido del bundle** (build time: falla si el
tarball no tiene la capa completa `bin/{sentinel-admin-x86_64.pyz, sentinel-admin-arm64.pyz}` +
`images/` + `manifests/` + `profiles/` + `install.sh`, o si aparece `sentinel-admin-signer*`
en **cualquier** ruta del tarball, no solo `bin/` — FR-021/FR-023), suite del núcleo de
ambos corrida **con la red cortada** (garantía offline verificable) + check de imports
prohibidos en el gate — con targets de Makefile propios (`test-offline-signer`/
`test-offline-admin`) para que la validación offline de SC-005 sea invocable de punta a
punta. Todo corre en contenedor (imagen backend — sin exigir nada nuevo al equipo).

**Target Platform**: `sentinel-admin-<arch>.pyz` (zipapp via shiv) por plataforma linux
x86_64/arm64 (wheels de cryptography embebidas) — **estos son los únicos `.pyz` que viajan
dentro del bundle air-gapped**, con sha256 en el MANIFEST (mismo contrato que las
imágenes; FR-021/FR-022). El bundle también incluye un **`install.sh`** generado por
`bundle create` (FR-021) — el único mecanismo sancionado para colocar `sentinel-admin` en el
host destino (copia el `.pyz` de la arquitectura detectada, fija permisos ejecutables,
imprime los próximos pasos); es lo que hace cumplible FR-023 (nunca pip/apt/yum/
repositorios externos dentro del air-gap). `sentinel-admin-signer.pyz` se construye para la
arquitectura de la estación de firma de Sentinel (single-arch, no viaja en ningún bundle —
FR-017/FR-021). Host del cliente: Python 3.11+ + Docker (ya prerrequisito del producto),
sin pip/apt/yum/repositorios externos (FR-023).

**Project Type**: dos paquetes Python nuevos en `cli/` (`sentinel_admin_signer/` y
`sentinel_admin/`) + endurecimiento de entrypoints de dominio en
`backend/src/cli_entrypoints/` (módulos `python -m` que reemplazan los scripts sueltos,
usados por `sentinel-admin` para lo que toca SQLAlchemy).

**Performance Goals**: N/A relevante (herramienta humana); arranque de cada `.pyz` < 2s.

**Constraints**: núcleo 100% offline en ambos artefactos (cero imports de red —
verificado por el gate de cada paquete); sin secretos en stdout/logs/args (prompt sin eco
+ `--password-stdin` para automatización); toda mutación con dry-run + confirmación;
strings de ambos `.pyz` pasan los checks white-label (`prohibited_names.txt`); ningún
`.pyz` engorda las imágenes del producto; **separación física build-time no negociable**
— sin subcomandos ocultos, flags de rol ni gates por env var como sustituto (FR-019).

**Scale/Scope**: MVP se reparte en dos artefactos — `sentinel-admin-signer` (~5 comandos:
`license issue`/`issue-dev`/`keyset export`/`keyset rotate`/`license verify`) y
`sentinel-admin` (~11 comandos: `install profile new`/`render`, `secrets gen`,
`bundle create`/`verify`, `load`, `up`, `seed apply`, `license install`/`verify`,
`admin bootstrap`, `verify`); `ops` día-2 y [CLOUD] en fase 2 con contrato preliminar
escrito (artefacto anfitrión de `ops` aún no decidido — ver inventario-scripts.md,
pregunta ABIERTA de rotación de keyset cross-fleet).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Veredicto | Nota |
|---|---|---|
| I. Privacy & Masking-First | ✅ n/a | No toca el pipeline de masking; `sentinel-admin install verify` lo ejercita como smoke |
| II. Compliance FIRST | ✅ refuerza | Audit-log local metadata-only de emisiones (signer) e instalaciones (admin); cero contenido sensible |
| III. Multi-Tenant | ✅ | Ambos artefactos operan el modelo tenant-por-deployment existente (013/021); no lo alteran |
| IV. Onboarding as Data | ✅ refuerza | `sentinel-admin install profile new`/`seed apply` materializan "cliente = config + seed, nunca código" con validación |
| V. Cost Governance | ✅ n/a | Sin cambios |
| VI. LiteLLM-Native, No Patching | ✅ | El motor no se toca; `sentinel-admin` orquesta compose y entrypoints del backend |
| VII. White-Label | ✅ **gate clave** | Ambos `.pyz` en su distribución respectiva → strings marca-neutros bajo los checks existentes; perfil por cliente = config, nunca fork |
| VIII. Transparencia | ✅ refuerza | Cada operación de cada artefacto deja traza auditable local exportable |

**Violaciones**: ninguna. **Re-check post-diseño (Phase 1)**: sin cambios — el diseño no
introduce esquema, superficies de red, lenguajes nuevos ni parches al motor. La separación
física en dos paquetes **añade** superficie de build (dos targets, dos suites) pero es un
requisito explícito de la spec (FR-016/FR-019/FR-020), no una complejidad incidental —
ver Complexity Tracking. Punto de atención mantenido: los entrypoints de dominio viven en
`backend/` (superficie compartida) y la custodia de claves/quién-firma es frontera con la
017 → review de @cluna-8 en el PR de implementación.

## Project Structure

### Documentation (this feature)

```text
specs/026-cli-operador-sentinel/
├── plan.md                   # Este archivo
├── spec.md                   # Especificación + Clarifications (Session 2026-08-05)
├── inventario-scripts.md     # Grounding: 54 operaciones relevadas, árbol de comandos, estado de resolución
├── research.md               # D1-D6 (+ alternativa Go evaluada y archivada)
├── data-model.md             # Artefactos existentes + ledger/audit-log nuevos
├── quickstart.md             # Validación viva del MVP (ambos artefactos)
├── contracts/
│   └── cli-comandos.md       # Contrato por comando (sentinel-admin-signer + sentinel-admin) + invariantes globales
└── tasks.md                  # 39 tasks (T001-T039), regenerado por /speckit-tasks tras este re-plan
```

### Source Code (repository root)

```text
cli/                                        # Paquetes Python nuevos (raíz, hermanos de backend/)
├── sentinel_admin_signer/                      # Artefacto 1 — SOLO estación de firma Sentinel (FR-016/FR-017)
│   ├── pyproject.toml                      # deps: click + cryptography; entry point sentinel-admin-signer
│   ├── sentinel_admin_signer/
│   │   ├── __main__.py                     # python -m sentinel_admin_signer
│   │   ├── cmd_license.py                  # issue / issue-dev / keyset export|rotate / verify
│   │   ├── signing.py                      # emisor: importa licensing.token; validador fail-closed (D1)
│   │   ├── keycustody.py                   # PKCS8 cifrado de la privada del EMISOR (D2): create/import/unlock/rotate
│   │   ├── ledger.py                       # ledger de emisiones + audit-log propio, JSONL hash-encadenado (D5) — solo signer
│   │   └── ui.py                           # confirm/--yes, prompts sin eco, errores legibles, exit codes 0-4
│   │                                        #   (implementación propia — sin import cruzado hacia sentinel_admin)
│   ├── tests/
│   │   └── test_contract_artifact.py       # FR-020: .pyz firma → backend valida (mismo empaquetado)
│   └── Makefile                            # build .pyz (shiv), single-arch; test; test-offline; test-contract
│
├── sentinel_admin/                              # Artefacto 2 — partner/cliente (FR-018), distribuido en el bundle
│   ├── pyproject.toml                      # deps: click + cryptography; entry point sentinel-admin
│   │                                        # SIN dependencia de sentinel_admin_signer (verificado por test)
│   ├── sentinel_admin/
│   │   ├── __main__.py                     # python -m sentinel_admin
│   │   ├── cmd_install.py                  # profile / bundle / load / up / seed / admin / verify
│   │   ├── cmd_license.py                  # license install / license verify (solo verificación pública)
│   │   ├── profile.py / secrets.py / bundle.py / stack.py   # render, secretos, MANIFEST + install.sh (FR-021),
│   │   │                                    #   compose up + readiness (D4)
│   │   ├── ui.py                           # confirm/--yes, prompts sin eco, errores legibles, exit codes 0-4
│   │   │                                    #   (implementación propia — sin import cruzado hacia sentinel_admin_signer)
│   │   └── auditlog.py                     # audit-log local propio de sentinel-admin, JSONL hash-encadenado
│   │                                        #   (implementación independiente de ledger.py del signer)
│   ├── tests/
│   │   ├── test_offline_gate.py            # imports prohibidos (requests/httpx/socket) + red cortada
│   │   ├── test_artifact_boundary.py       # FR-020: inspección del .pyz — falla si aparecen
│   │   │                                    #   keycustody/signing/ledger o símbolos exclusivos del signer;
│   │   │                                    #   FR-019: grep estático anti-runtime-role-gating
│   │   └── test_bundle_contents.py         # FR-021/FR-023: bundle contiene EXACTAMENTE bin/{sentinel-admin-x86_64.pyz,
│   │                                        #   sentinel-admin-arm64.pyz} + images/ + manifests/ + profiles/ + install.sh;
│   │                                        #   escaneo del tarball COMPLETO (no solo bin/) para sentinel-admin-signer*
│   └── Makefile                            # build-x86_64/build-arm64 (shiv); test; test-offline;
│                                            #   test-artifact-boundary; test-bundle-contents
│
└── Makefile                                # orquesta ambos: build-signer, build-admin, test-contract-signer,
                                             # test-offline-signer, test-offline-admin, test-artifact-boundary-admin,
                                             # test-bundle-contents-admin (todos deben pasar antes de release)

backend/
├── src/cli_entrypoints/              # NUEVOS módulos python -m endurecidos (dominio SQLAlchemy) — usados por sentinel-admin
│   ├── seed_apply.py                 # reemplaza apply_profile_seed.py (flags, dry-run, confirm)
│   ├── admin_bootstrap.py            # reemplaza el TOFU raceable + SQL crudo (#34)
│   └── license_genesis.py            # registro de génesis post-install
├── src/licensing/                    # SIN cambios de wire — import selectivo por artefacto (research.md D6):
│                                      #   verifier.py/token.py/deployment_key.py/trueup_export.py → sentinel-admin OK
│                                      #   (no tocan la privada del emisor); custodia/firma del emisor es código
│                                      #   nuevo exclusivo de sentinel_admin_signer/ (no vive acá)
└── scripts/                          # los scripts viejos quedan deprecados con puntero al artefacto correspondiente

deploy/
├── release/                          # bundle.sh/render_profile.sh: sentinel-admin absorbe su contrato, incluyendo
│                                      # la generación de install.sh dentro del tarball (FR-021)
│                                      # (el bundle SOLO empaqueta el .pyz de sentinel-admin — nunca sentinel-admin-signer)
└── Makefile                          # targets cli-build-signer/cli-build-admin/cli-check integrados al gate
```

**Structure Decision**: **dos paquetes Python autocontenidos** en `cli/` — `sentinel_admin_signer/`
y `sentinel_admin/` — sin dependencia cruzada entre ellos (verificado por test de inspección
de artefacto, FR-020). `sentinel_admin` importa de `backend/src/licensing/` únicamente los
módulos que no tocan la privada del emisor de Sentinel (research.md D6); la custodia/firma de
esa privada es código nuevo que vive exclusivamente en `sentinel_admin_signer/`. Entrypoints
de dominio endurecidos en el backend existente (patrón D4), usados solo por `sentinel_admin`.
Sin proyectos web nuevos, sin cambios de esquema, sin tocar `litellm/`, sin segundo
lenguaje.

## Complexity Tracking

Sin violaciones constitucionales que justificar. La complejidad neta de fondo sigue
**baja** respecto a las alternativas: un solo lenguaje, la firma reusa la lib desplegada
(cero contrato cross-lenguaje que mantener). La única complejidad **añadida** respecto al
plan original (dos paquetes/builds/suites en vez de uno) es un requisito explícito y no
negociable de la spec (FR-016/FR-019/FR-020: la separación física es la única frontera de
seguridad válida entre firma Sentinel e instalación partner/cliente — ningún gate en runtime
la sustituye), no una decisión de diseño discrecional. El costo real — Python 3.11+ como
prerrequisito del host — se documenta en el perfil del partner (025) y es estándar en los
Linux objetivo.
