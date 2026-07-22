# Tasks: CLI de operador (`basa-admin`) — firma de licencias e instalación guiada offline

**Input**: Design documents from `/specs/026-cli-operador-basa/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-comandos.md, quickstart.md

**Tests**: incluidos (DoD del repo: lógica no trivial lleva tests; la firma y el
empaquetado llevan contract tests — Constitución, Development Workflow §3).

**Organization**: por user story. US1 (firma) y US2 (instalación) son los dos medios del
MVP y se entregan en ese orden; US3 (`ops` día-2) es **fase 2 — sin tareas acá** (contrato
preliminar ya escrito en contracts/).

## Phase 1: Setup

**Purpose**: esqueleto del paquete `cli/` + build reproducible en contenedor

- [ ] T001 Crear el paquete `cli/` (pyproject.toml con deps click+cryptography, `basa_admin/__init__.py`, `__main__.py` con el grupo click raíz y `--version`) según el árbol del plan.md
- [ ] T002 [P] Makefile de `cli/`: targets `build` (shiv → `dist/basa-admin-<arch>.pyz` en contenedor backend, `SHIV_ROOT` fijado), `test`, `test-offline` (pytest con `--network none`) y `test-contract`; integrar `cli-build`/`cli-check` al `deploy/Makefile`
- [ ] T003 [P] `basa_admin/ui.py`: helpers `confirm()` (con bypass `--yes`), prompt sin eco con detección de TTY + camino `--password-stdin`, formato de errores legibles y mapa de exit codes 0-4 del contrato (invariantes 2/3/4/6)
- [ ] T004 [P] Resolver el import de la lib de licensing como **fuente única** (el build del `.pyz` incluye `backend/src/licensing/{token,verifier}.py` sin fork — mecanismo: package-data o path dep en pyproject) y documentarlo en `cli/README.md`

## Phase 2: Foundational (bloquea todas las user stories)

**Purpose**: custodia de clave, ledger/audit y la garantía offline verificable

- [ ] T005 `basa_admin/keycustody.py`: crear/importar/abrir la privada como PEM PKCS8 cifrado (`BestAvailableEncryption`), escritura `O_EXCL` + `0600` en dir `0700`, passphrase por `ui.py`; `key import` valida pública↔kid del keyset y borra el PEM claro best-effort (research D2)
- [ ] T006 [P] Tests unit de keycustody en `cli/tests/test_keycustody.py`: no pisa clave existente (O_EXCL), permisos, round-trip cifrado→firma, import valida kid, passphrase equivocada → error legible exit 1
- [ ] T007 [P] `basa_admin/ledger.py`: JSONL append-only hash-encadenado para (a) ledger de emisiones y (b) audit-log de la CLI (args sanitizados, metadata-only), con verificación de cadena y export (research D5) + tests en `cli/tests/test_ledger.py`
- [ ] T008 [P] Gate offline en `cli/tests/test_offline_gate.py`: check de imports prohibidos (requests/httpx/urllib.request/socket fuera de allowlist) sobre `basa_admin/` + marker para correr la suite con red cortada (FR-011, SC-005)

**Checkpoint**: custodia + ledger + gate listos — US1 y US2 pueden arrancar

## Phase 3: User Story 1 — Firmar una licencia sin foot-guns (P1) 🎯 MVP mitad 1

**Goal**: emitir `.lic` por flags con keyset intacto por defecto y privada cifrada

**Independent Test**: quickstart pasos 1-3 — emitir con flags, keyset intacto
(sha256 antes==después), el `.lic` valida en la CLI y en el backend del producto

- [ ] T009 [P] [US1] Tests primero en `cli/tests/test_license_issue.py`: emisión por flags produce `.lic` que `verifier.py` valida; emisión NO toca el keyset (FR-002/SC-002); expiry pasada/seats negativos → exit 2; payload con floats/campos extraños → rechazo fail-closed (research D1)
- [ ] T010 [US1] `basa_admin/signing.py`: emisor que importa `licensing.token.canonical_payload_bytes` (fuente única), validador pre-firma fail-closed, escritura del `.lic` (base64url con padding) y registro en el ledger
- [ ] T011 [US1] `basa_admin/cmd_license.py`: comandos `issue` / `issue-dev` (defaults dev + advertencia BASA_ALLOW_DEV_LICENSE) / `verify` según contrato; wiring a signing/keycustody/ledger
- [ ] T012 [US1] `cmd_license.py`: `keyset export` (formato `# key_id:` del verifier, jamás material privado) y `keyset rotate` (AGREGA kid, muestra antes/después, confirmación; retiro de kid viejo = flag aparte con confirmación doble) + tests CliRunner en `cli/tests/test_keyset.py`
- [ ] T013 [US1] Contract test del artefacto en `cli/tests/test_artifact_contract.py`: el `.pyz` buildeado emite un `.lic` → `docker compose run backend` lo valida con `verify_license_blob` (cubre el empaquetado, quickstart paso 1)

**Checkpoint**: US1 entregable sola — Basa ya puede firmar sin editar código

## Phase 4: User Story 2 — Instalar un cliente de cero a corriendo, guiado (P1) 🎯 MVP mitad 2

**Goal**: secuencia perfil → secretos → bundle → up → seed → licencia → admin → verify
sin editar scripts ni SQL, resolviendo los 7 hallazgos de research D4

**Independent Test**: quickstart paso 4 — con un `.lic` de US1, la secuencia completa
contra el stack dev termina con `install verify` en verde

### Entrypoints de dominio (backend — superficie compartida, review @cluna-8)

- [ ] T014 [P] [US2] `backend/src/cli_entrypoints/seed_apply.py` (`python -m`): reemplaza `apply_profile_seed.py` con flags, `--dry-run` (diff del rename de tenant incluido), confirmación mostrando la DB objetivo, keys emitidas a archivo `600` (hallazgo 5: soporta seed con sección `tools:`) + tests en `backend/tests/unit/test_cli_entrypoints_seed.py`
- [ ] T015 [P] [US2] `backend/src/cli_entrypoints/admin_bootstrap.py`: crea/rota el admin sin SQL (password por stdin), pensado para correr ANTES de exponer el ingress — mata el TOFU raceable (hallazgo 7, #34) + tests en `backend/tests/unit/test_cli_entrypoints_admin.py`
- [ ] T016 [P] [US2] `backend/src/cli_entrypoints/license_genesis.py`: registro de génesis post-instalación (orden correcto respecto a admin/health gated — hallazgo 7b) + test unit

### Comandos de la CLI (host)

- [ ] T017 [P] [US2] `basa_admin/profile.py` + comandos `install profile new/render`: scaffold desde example CON `tools:` (hallazgo 5), render con validación de layout/vars y golden-test contra la salida de `render_profile.sh` en `cli/tests/test_profile.py`
- [ ] T018 [P] [US2] `basa_admin/secrets.py` + `install secrets gen`: secretos del compose prod con `secrets`/`os.urandom` a archivo `600`; regenerar pide confirmación + tests
- [ ] T019 [US2] `basa_admin/bundle.py` + `install bundle create/verify` + `install load`: lockfile en vez de 7 env vars; verify contra MANIFEST por `.Id` (hallazgo 3); load **re-taggea desde el MANIFEST** (hallazgo 2); el/los `.pyz` entran al bundle con sha256 (research D3) + tests en `cli/tests/test_bundle.py`
- [ ] T020 [US2] `basa_admin/stack.py` + `install up`: puebla los volúmenes `licenses`/`litellm_config`/`branding` que el camino compose deja huérfanos (hallazgo 1), levanta compose prod y hace poll de readiness propio con diagnóstico de crash-loop de alembic (hallazgo 4) + tests
- [ ] T021 [US2] `install license install`: valida offline, puebla el volumen de licencia, restart del backend + poll de `/health/license` (hallazgo 6, singleton en memoria) + test CliRunner
- [ ] T022 [US2] `install seed apply` / `install admin bootstrap`: wrappers de la CLI hacia los entrypoints T014/T015 vía `docker compose exec` con la UX del contrato (dry-run/confirm/--yes) + tests
- [ ] T023 [US2] `install verify <slug>` + `install status`: smoke e2e (contenedores, licencia activa, gateway responde, masking en vivo — reutiliza checks existentes de `deploy/release/checks/`) y estado por paso de la secuencia + tests
- [ ] T024 [US2] Test de flujo completo en `cli/tests/test_install_flow.py` (CliRunner + stack dev): la secuencia entera del quickstart paso 4 en verde

**Checkpoint**: MVP completo — firma + instalación guiada

## Phase 5: Polish & Cross-Cutting

- [ ] T025 [P] Deprecar los scripts viejos con puntero a la CLI (FR-012): `issue_dev_license.py`, `apply_profile_seed.py`, `generate_trueup.py` → banner de deprecación + doc de migración en `backend/scripts/README.md`
- [ ] T026 [P] Docs DoD: página/runbook de la CLI en la doc de producto (install-deploy actualizado para usar `basa-admin`, prerrequisito Python 3.11+ añadido al perfil del partner en `docs/docs/install-deploy/partner-enablement.md`), gate `make -C deploy check-docs` verde
- [ ] T027 [P] Whitelabel: strings de `--help`/errores del `.pyz` pasan `check-whitelabel` (`prohibited_names.txt`) — añadir el binario al alcance del check
- [ ] T028 Actualizar `specs/ROADMAP-guardian.md` (026 → Implementada + PR) y el registro de superficies si aplica — en el MISMO PR (regla de mantenimiento del roadmap)
- [ ] T029 Quickstart completo de punta a punta (pasos 0-5) como validación final + STOP & VALIDATE con JF antes del merge

## Dependencies & Execution Order

- **Setup (T001-T004)** → **Foundational (T005-T008)** → todo lo demás
- **US1 (T009-T013)**: independiente tras Foundational; T009 (tests) antes de T010-T012; T013 requiere T002 (build)
- **US2 (T014-T024)**: los entrypoints T014-T016 y los comandos T017-T018 son paralelos entre sí; T019→T020→T021 en orden (bundle→up→license); T022 requiere T014/T015; T023-T024 al final. T021 usa un `.lic` de US1 (o el dev existente) — US2 es testeable sola con la licencia dev
- **Polish (T025-T029)**: tras el MVP; T025-T027 paralelas

## Parallel Example

```text
# Tras Foundational, dos frentes en paralelo:
Frente A (US1): T009 → T010 → T011 → T012 → T013
Frente B (US2): T014 + T015 + T016 + T017 + T018 (todas [P]) → T019 → T020 → T021 → T022 → T023 → T024
```

## Implementation Strategy

**MVP first**: US1 sola ya entrega valor (Basa firma sin editar código — desbloquea el
piloto aunque la instalación siga semi-manual). US2 completa el camino humano. Cada
checkpoint es demostrable a JF por separado; STOP & VALIDATE antes del merge (T029).
