# Implementation Plan: CLI de operador (`basa-admin`) — firma de licencias e instalación guiada offline

**Branch**: `026-cli-operador-basa` | **Date**: 2026-07-22 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/026-cli-operador-basa/spec.md`

## Summary

Construir `basa-admin`: una **CLI en Go, local, offline y airgap-safe** que reemplaza los
scripts sueltos con foot-guns por comandos guiados. MVP en dos mitades: **firma de
licencias** (emisión `.lic` por flags con keyset intacto por defecto, privada cifrada con
age, ledger local de emisiones) e **instalación guiada** de un cliente hasta stack
corriendo y verificado (perfil → secretos → bundle → up → seed → licencia+génesis → admin
→ verify). El riesgo técnico central — que la firma Go valide en el `verifier.py` Python
desplegado — quedó **resuelto empíricamente en research** (bytes canónicos idénticos con
Go ≥ 1.22 + `SetEscapeHTML(false)` + validador fail-closed; firma Ed25519 byte-idéntica
verificada contra la imagen real del backend) y se blinda con **golden vectors
cross-lenguaje** en el gate. Patrón de integración: **"Go orquesta, Python ejecuta
dominio"** — Go nativo para archivos/docker, entrypoints Python endurecidos (con flags,
dry-run y confirmación) para todo lo que toca SQLAlchemy. Absorbe #33 (pre-portal) y #34.
Detalle y evidencia: [research.md](research.md).

## Technical Context

**Language/Version**: Go ≥ 1.22 (fijado en `go.mod`; por debajo, `\b`/`\f` divergen de
Python y las firmas no verifican — research D1). Entrypoints de dominio: Python 3.11 del
contenedor backend existente.

**Primary Dependencies**: spf13/cobra + pflag (árbol de comandos), filippo.io/age
(custodia de la privada, scrypt), golang.org/x/term (prompts sin eco), crypto/ed25519 +
encoding/json + crypto/x509 de la stdlib (firma y canonicalización). Todo **vendored**
(`vendor/` commiteado, `GOFLAGS=-mod=vendor`, `GOTOOLCHAIN=local`) — el build jamás
resuelve nada por red.

**Storage**: archivos locales únicamente — `.lic`, keyset PEM (formato `# key_id:` del
verifier), privada `.age` (0600, O_EXCL), ledger de emisiones y audit-log de la CLI como
JSONL append-only hash-encadenado. **Cero esquema nuevo** en la DB del producto.

**Testing**: `go test` table-driven + **testscript (txtar)** para flujos de comandos;
**golden vectors cross-lenguaje** generados por Python (referencia normativa) y
asertados desde pytest Y go test; e2e del gate: la CLI emite un `.lic` real →
`verify_license_blob` Python lo valida. Suite del núcleo corre **con la red cortada**.
Todo en contenedor (imagen golang para build/test — no exige Go en el host).

**Target Platform**: binario estático (CGO_ENABLED=0) cross-compilado linux/amd64,
linux/arm64 y darwin/arm64. Los binarios linux viajan **dentro del bundle air-gapped**
con sha256 en el MANIFEST (mismo contrato que las imágenes).

**Project Type**: CLI (módulo Go nuevo en `cli/`) + endurecimiento de entrypoints Python
existentes en `backend/scripts/` → `backend/src/cli_entrypoints/` (módulos `python -m`).

**Performance Goals**: N/A relevante (herramienta humana); único límite: descifrado
scrypt de la privada ≤ ~15s con work factor 22 (default explícito).

**Constraints**: núcleo 100% offline (cero imports de red — verificado por el gate);
sin secretos en stdout/logs/args; toda mutación con dry-run + confirmación; los strings
del binario pasan los checks white-label (`prohibited_names.txt`); `.dockerignore`
excluye `cli/` del build context de las imágenes.

**Scale/Scope**: MVP = subárboles `license` (issue/issue-dev/keyset export/rotate/verify)
+ `install` (profile/secrets/bundle/load/up/seed/license/admin/verify) ≈ 14 comandos;
`ops` día-2 y [CLOUD] quedan en fase 2 con contrato preliminar escrito.

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
| VII. White-Label | ✅ **gate clave** | Binario en el bundle → strings marca-neutros bajo los checks existentes; perfil por cliente = config, nunca fork |
| VIII. Transparencia | ✅ refuerza | Cada operación de la CLI deja traza auditable local exportable |

**Violaciones**: ninguna. **Re-check post-diseño (Phase 1)**: sin cambios — el diseño no
introduce esquema, superficies de red ni parches al motor. Punto de atención mantenido:
los entrypoints Python nuevos viven en `backend/` (superficie compartida) y la custodia de
claves/quién-firma es frontera con la 017 → review de @cluna-8 en el PR de implementación.

## Project Structure

### Documentation (this feature)

```text
specs/026-cli-operador-basa/
├── plan.md                   # Este archivo
├── spec.md                   # Especificación (PR #38)
├── inventario-scripts.md     # Grounding: 54 operaciones relevadas, árbol de comandos
├── research.md               # D1-D5 con evidencia empírica (firma Go↔Python verificada)
├── data-model.md             # Artefactos existentes + ledger/audit-log nuevos
├── quickstart.md             # Validación viva del MVP
├── contracts/
│   └── cli-comandos.md       # Contrato por comando + 6 invariantes globales
└── tasks.md                  # (/speckit-tasks — no lo crea este comando)
```

### Source Code (repository root)

```text
cli/                                  # Módulo Go nuevo (raíz, hermano de backend/)
├── go.mod                            # go 1.22; deps vendored
├── vendor/                           # commiteado (build sin red)
├── cmd/basa-admin/main.go
├── internal/
│   ├── cmdtree/                      # cobra: license/, install/ (ops/ fase 2)
│   ├── license/                      # canonical.go (D1), sign.go, keyset.go, ledger.go
│   ├── keycustody/                   # age scrypt (D2): create/import/unlock
│   ├── install/                      # profile.go, secrets.go, bundle.go, up.go, verify.go
│   └── version/
├── testdata/script/*.txtar           # testscript de flujos
└── Makefile                          # build en contenedor golang; cross-compile; test-offline

backend/
├── src/cli_entrypoints/              # NUEVOS módulos python -m endurecidos (dominio SQLAlchemy)
│   ├── seed_apply.py                 # reemplaza apply_profile_seed.py (flags, dry-run, confirm)
│   ├── admin_bootstrap.py            # reemplaza el TOFU raceable + SQL crudo (#34)
│   └── license_genesis.py            # registro de génesis post-install
├── scripts/                          # los scripts viejos quedan deprecados con puntero
└── tests/licensing/golden/           # vectors.json + clave SOLO-test (generados por Python)

deploy/
├── release/                          # bundle.sh/render_profile.sh: la CLI absorbe su contrato
└── Makefile                          # targets cli-build/cli-check integrados al gate

.dockerignore                         # + cli/ (no engordar el build context de las imágenes)
```

**Structure Decision**: un módulo Go nuevo autocontenido en `cli/` + entrypoints Python
endurecidos en el backend existente (patrón D4: "Go orquesta, Python ejecuta dominio").
Sin proyectos web nuevos, sin cambios de esquema, sin tocar `litellm/`. Los golden
vectors viven del lado Python (referencia normativa del wire de la 021).

## Complexity Tracking

Sin violaciones constitucionales que justificar. La única "complejidad" añadida — un
segundo lenguaje en el repo — está justificada por el requisito de binario único sin
runtime en la caja del cliente (decisión de JF, 22-jul) y acotada por: dominio SQLAlchemy
sigue en Python (cero duplicación de modelos), contrato de firma blindado por golden
vectors, y build/test 100% en contenedor (no exige Go a nadie del equipo).
