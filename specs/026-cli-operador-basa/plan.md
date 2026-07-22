# Implementation Plan: CLI de operador (`basa-admin`) — firma de licencias e instalación guiada offline

**Branch**: `026-cli-operador-basa` | **Date**: 2026-07-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/026-cli-operador-basa/spec.md`

## Summary

Construir `basa-admin`: una **CLI en Python, local, offline y airgap-safe** que reemplaza
los scripts sueltos con foot-guns por comandos guiados. MVP en dos mitades: **firma de
licencias** (emisión `.lic` por flags con keyset intacto por defecto, privada como PKCS8
cifrado, ledger local de emisiones) e **instalación guiada** de un cliente hasta stack
corriendo y verificado (perfil → secretos → bundle → up → seed → licencia+génesis → admin
→ verify). Decisión de lenguaje (JF): **Python** — el emisor **importa la lib de
licensing existente** (`canonical_payload_bytes`, `verifier.py`), así que el riesgo de
divergencia emisor↔verificador desaparece **por construcción** (la alternativa Go quedó
evaluada, verificada y archivada en research). Distribución: **zipapp `.pyz` single-file**
dentro del bundle air-gapped. Patrón de integración: **"la CLI orquesta, los entrypoints
ejecutan dominio"** — la CLI del host hace archivos/docker; los entrypoints `python -m`
endurecidos (flags, dry-run, confirmación) corren dentro del contenedor backend para todo
lo que toca SQLAlchemy. Absorbe #33 (pre-portal) y #34. Detalle: [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11+ (el mismo del backend; prerrequisito documentado del
host de instalación — se añade al perfil del partner en la doc 025).

**Primary Dependencies**: **click** (árbol de comandos, prompts/confirm, CliRunner para
tests) + **cryptography** (firma/custodia — ya es dependencia del producto) +
`backend/src/licensing/` **como fuente única** (la CLI la importa, no la reimplementa).
Cero dependencias de red en el núcleo.

**Storage**: archivos locales únicamente — `.lic`, keyset PEM (formato `# key_id:` del
verifier), privada como **PEM PKCS8 cifrado** (`BestAvailableEncryption`, 0600, O_EXCL),
ledger de emisiones y audit-log de la CLI como JSONL append-only hash-encadenado.
**Cero esquema nuevo** en la DB del producto.

**Testing**: pytest end-to-end — unit del emisor/custodia/render, `CliRunner` para flujos
de comandos, **contract test del artefacto** (`basa-admin.pyz` firma → el backend del
stack valida: cubre el empaquetado, no solo el código), suite del núcleo corrida **con la
red cortada** (garantía offline verificable) + check de imports prohibidos en el gate.
Todo corre en contenedor (imagen backend — sin exigir nada nuevo al equipo).

**Target Platform**: `basa-admin.pyz` (zipapp via shiv) por plataforma linux
x86_64/arm64 (wheels de cryptography embebidas); los `.pyz` viajan **dentro del bundle
air-gapped** con sha256 en el MANIFEST (mismo contrato que las imágenes). Host: Python
3.11+ + Docker (ya prerrequisito del producto).

**Project Type**: CLI (paquete Python nuevo en `cli/`) + endurecimiento de entrypoints
de dominio en `backend/src/cli_entrypoints/` (módulos `python -m` que reemplazan los
scripts sueltos).

**Performance Goals**: N/A relevante (herramienta humana); arranque del `.pyz` < 2s.

**Constraints**: núcleo 100% offline (cero imports de red — verificado por el gate); sin
secretos en stdout/logs/args (prompt sin eco + `--password-stdin` para automatización);
toda mutación con dry-run + confirmación; strings del `.pyz` pasan los checks white-label
(`prohibited_names.txt`); el `.pyz` y su build no engordan las imágenes del producto.

**Scale/Scope**: MVP = subárboles `license` (issue/issue-dev/keyset export/rotate/verify)
+ `install` (profile/secrets/bundle/load/up/seed/license/admin/verify) ≈ 14 comandos;
`ops` día-2 y [CLOUD] en fase 2 con contrato preliminar escrito.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Veredicto | Nota |
|---|---|---|
| I. Privacy & Masking-First | ✅ n/a | No toca el pipeline de masking; `install verify` lo ejercita como smoke |
| II. Compliance FIRST | ✅ refuerza | Audit-log local metadata-only de emisiones/instalaciones; cero contenido sensible |
| III. Multi-Tenant | ✅ | La CLI opera el modelo tenant-por-deployment existente (013/021); no lo altera |
| IV. Onboarding as Data | ✅ refuerza | `profile new`/`seed apply` materializan "cliente = config + seed, nunca código" con validación |
| V. Cost Governance | ✅ n/a | Sin cambios |
| VI. LiteLLM-Native, No Patching | ✅ | El motor no se toca; la CLI orquesta compose y entrypoints del backend |
| VII. White-Label | ✅ **gate clave** | `.pyz` en el bundle → strings marca-neutros bajo los checks existentes; perfil por cliente = config, nunca fork |
| VIII. Transparencia | ✅ refuerza | Cada operación de la CLI deja traza auditable local exportable |

**Violaciones**: ninguna. **Re-check post-diseño (Phase 1)**: sin cambios — el diseño no
introduce esquema, superficies de red, lenguajes nuevos ni parches al motor. Punto de
atención mantenido: los entrypoints de dominio viven en `backend/` (superficie
compartida) y la custodia de claves/quién-firma es frontera con la 017 → review de
@cluna-8 en el PR de implementación.

## Project Structure

### Documentation (this feature)

```text
specs/026-cli-operador-basa/
├── plan.md                   # Este archivo
├── spec.md                   # Especificación (PR #38)
├── inventario-scripts.md     # Grounding: 54 operaciones relevadas, árbol de comandos
├── research.md               # D1-D5 (+ alternativa Go evaluada y archivada)
├── data-model.md             # Artefactos existentes + ledger/audit-log nuevos
├── quickstart.md             # Validación viva del MVP
├── contracts/
│   └── cli-comandos.md       # Contrato por comando + 6 invariantes globales
└── tasks.md                  # (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
cli/                                  # Paquete Python nuevo (raíz, hermano de backend/)
├── pyproject.toml                    # deps: click + cryptography; entry point basa-admin
├── basa_admin/
│   ├── __main__.py                   # python -m basa_admin
│   ├── cmd_license.py                # issue / issue-dev / keyset export|rotate / verify
│   ├── cmd_install.py                # profile / secrets / bundle / load / up / seed / license / admin / verify
│   ├── signing.py                    # emisor (importa licensing.token; validador fail-closed D1)
│   ├── keycustody.py                 # PKCS8 cifrado (D2): create / import / unlock
│   ├── ledger.py                     # emisiones + audit-log JSONL hash-encadenado (D5)
│   ├── profile.py / bundle.py / stack.py   # render, MANIFEST, compose up + readiness (D4)
│   └── ui.py                         # confirm/--yes, prompts sin eco, errores legibles
├── tests/                            # pytest: unit + CliRunner + offline-gate
└── Makefile                          # build .pyz (shiv) por arch; test en contenedor

backend/
├── src/cli_entrypoints/              # NUEVOS módulos python -m endurecidos (dominio SQLAlchemy)
│   ├── seed_apply.py                 # reemplaza apply_profile_seed.py (flags, dry-run, confirm)
│   ├── admin_bootstrap.py            # reemplaza el TOFU raceable + SQL crudo (#34)
│   └── license_genesis.py            # registro de génesis post-install
├── src/licensing/                    # SIN cambios de wire — la CLI lo importa (fuente única)
└── scripts/                          # los scripts viejos quedan deprecados con puntero

deploy/
├── release/                          # bundle.sh/render_profile.sh: la CLI absorbe su contrato
└── Makefile                          # targets cli-build/cli-check integrados al gate
```

**Structure Decision**: un paquete Python autocontenido en `cli/` que importa la lib de
licensing del backend como fuente única + entrypoints de dominio endurecidos en el
backend existente (patrón D4). Sin proyectos web nuevos, sin cambios de esquema, sin
tocar `litellm/`, sin segundo lenguaje.

## Complexity Tracking

Sin violaciones constitucionales que justificar. La complejidad neta **baja** respecto a
las alternativas: un solo lenguaje, la firma reusa la lib desplegada (cero contrato
cross-lenguaje que mantener), y el único costo real — Python 3.11+ como prerrequisito del
host — se documenta en el perfil del partner (025) y es estándar en los Linux objetivo.
