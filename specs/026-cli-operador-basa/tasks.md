# Tasks: CLI de operador (`basa-admin-signer` + `basa-admin`) — firma de licencias e instalación guiada offline

**Input**: Design documents from `/specs/026-cli-operador-basa/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-comandos.md, quickstart.md

**Tests**: incluidos (DoD del repo: lógica no trivial lleva tests; la firma y el
empaquetado llevan contract tests — Constitución, Development Workflow §3). La
separación física entre artefactos lleva, además, tests de **build gate**
(FR-020/FR-021) que no existían en el plan de un solo artefacto.

**Organization**: por user story, más una fase transversal de empaquetado que no
pertenece a ninguna user story individual. US1 (firma) vive **exclusivamente** en
`basa-admin-signer`; US2 (instalación) vive **exclusivamente** en `basa-admin`. Ningún
task de US1 toca `cli/basa_admin/` y ningún task de US2 toca `cli/basa_admin_signer/` —
esa exclusión es el requisito central de la spec (FR-016 a FR-020), no un detalle de
implementación. US3 (`ops` día-2) es **fase 2 — sin tareas acá** (contrato preliminar ya
escrito en contracts/; artefacto anfitrión aún no decidido, ver inventario-scripts.md).

## Phase 1: Setup

**Purpose**: esqueleto de **dos paquetes Python independientes** (sin dependencia
cruzada) + build reproducible en contenedor para cada uno

- [ ] T001 Crear el paquete `cli/basa_admin_signer/` (`pyproject.toml` con deps
      click+cryptography, entry point `basa-admin-signer`; `basa_admin_signer/__init__.py`;
      `__main__.py` con el grupo click raíz y `--version`) según el árbol del plan.md.
      `pyproject.toml` **no** declara dependencia hacia `basa_admin` (FR-016)
- [ ] T002 Crear el paquete `cli/basa_admin/` (`pyproject.toml` con deps
      click+cryptography, entry point `basa-admin`; `basa_admin/__init__.py`;
      `__main__.py` con el grupo click raíz y `--version`) según el árbol del plan.md.
      `pyproject.toml` **no** declara dependencia hacia `basa_admin_signer` (FR-016/FR-018)
- [ ] T003 [P] `cli/basa_admin_signer/Makefile`: targets `build` (shiv → single-arch
      `dist/basa-admin-signer.pyz` para la estación de firma de Basa, `SHIV_ROOT` fijado —
      research D3), `test`, `test-offline` (pytest con `--network none`), `test-contract`
- [ ] T004 [P] `cli/basa_admin/Makefile`: targets `build-x86_64` y `build-arm64` (shiv →
      `dist/basa-admin-x86_64.pyz` / `dist/basa-admin-arm64.pyz` por separado, wheels de
      `cryptography` embebidas por plataforma — FR-016/FR-022), `test`, `test-offline`,
      `test-artifact-boundary`, `test-bundle-contents`
- [ ] T005 [P] `cli/Makefile` raíz: orquesta `build-signer`, `build-admin` (ambas arch),
      `test-contract-signer`, `test-offline-signer`, `test-offline-admin`,
      `test-artifact-boundary-admin`, `test-bundle-contents-admin` (delegando a los
      targets `test-offline`/`test-contract`/`test-artifact-boundary`/
      `test-bundle-contents` de cada Makefile de paquete — T003/T004); integra
      `cli-build-signer`/`cli-build-admin`/`cli-check` al `deploy/Makefile` como gates de
      release — todos deben pasar en verde antes de publicar cualquier bundle
      (FR-019/FR-020/FR-021)
- [ ] T006 [P] `cli/basa_admin_signer/basa_admin_signer/ui.py`: helpers `confirm()` (con
      bypass `--yes`), prompt sin eco con detección de TTY + camino `--password-stdin`,
      formato de errores legibles y mapa de exit codes 0-4 del contrato (invariantes
      2/3/4/6). Implementación propia, sin importar nada de `basa_admin`
- [ ] T007 [P] `cli/basa_admin/basa_admin/ui.py`: los mismos helpers que T006
      (`confirm()`, prompt sin eco, exit codes 0-4), implementación **propia e
      independiente** — ningún import cruzado hacia `basa_admin_signer` (FR-019/FR-020)
- [ ] T008 [P] `cli/README.md`: documentar la frontera de import selectivo de
      `backend/src/licensing/` fijada en research.md D6 — `verifier.py`/`token.py`/
      `deployment_key.py`/`trueup_export.py` son elegibles para `basa_admin` (no tocan la
      privada del emisor); `keycustody.py`/`signing.py`/`ledger.py` de emisiones son
      código nuevo, exclusivo de `basa_admin_signer`, y **nunca** deben importarse desde
      `basa_admin`

## Phase 2: Foundational (bloquea US1 y US2)

**Purpose**: custodia de la privada del emisor, ledgers/audit-log de cada artefacto y la
garantía offline verificable de cada uno — por separado, sin código compartido entre
paquetes

- [ ] T009 [P] `cli/basa_admin_signer/basa_admin_signer/keycustody.py`: crear/importar/
      abrir la privada del **emisor** como PEM PKCS8 cifrado (`BestAvailableEncryption`),
      escritura `O_EXCL` + `0600` en dir `0700`, passphrase por `ui.py` (T006); `key
      import` valida pública↔kid del keyset y borra el PEM claro best-effort (research D2).
      Este módulo **nunca** existe fuera de `basa_admin_signer/` (FR-017)
- [ ] T010 [P] Tests unit de keycustody en
      `cli/basa_admin_signer/tests/test_keycustody.py`: no pisa clave existente (O_EXCL),
      permisos, round-trip cifrado→firma, import valida kid, passphrase equivocada → error
      legible exit 1
- [ ] T011 [P] `cli/basa_admin_signer/basa_admin_signer/ledger.py`: writer JSONL
      append-only hash-encadenado genérico, instanciado dos veces dentro del paquete: (a)
      ledger de emisiones de licencias y (b) audit-log local de `basa-admin-signer`
      (comando/args sanitizados/resultado, metadata-only), con verificación de cadena y
      export (research D5) + tests en
      `cli/basa_admin_signer/tests/test_ledger.py`
- [ ] T012 [P] `cli/basa_admin/basa_admin/auditlog.py`: writer JSONL append-only
      hash-encadenado **propio** (implementación independiente, no importa `ledger.py` del
      signer) para el audit-log local de `basa-admin` en el host del cliente —
      metadata-only, sin secretos ni payloads (data-model.md § Audit-log local) + tests en
      `cli/basa_admin/tests/test_auditlog.py`
- [ ] T013 [P] Gate offline en `cli/basa_admin_signer/tests/test_offline_gate.py`: check
      de imports prohibidos (requests/httpx/urllib.request/socket fuera de allowlist)
      sobre `basa_admin_signer/` + marker para correr la suite con red cortada
      (FR-011/SC-005)
- [ ] T014 [P] Gate offline en `cli/basa_admin/tests/test_offline_gate.py`: mismo check
      de imports prohibidos sobre `basa_admin/` + marker de red cortada (FR-011/SC-005)

**Checkpoint**: ambos paquetes tienen custodia/ledger/audit/gate offline propios — US1 y
US2 pueden arrancar en paralelo, sin tocarse entre sí

## Phase 3: User Story 1 — Firmar una licencia sin foot-guns (P1) 🎯 MVP mitad 1

**Artefacto**: exclusivamente `basa-admin-signer` (FR-017). Ningún task de esta fase
toca `cli/basa_admin/`.

**Goal**: emitir `.lic` por flags con keyset intacto por defecto y privada del emisor
cifrada, desde un artefacto que jamás se entrega a partners/clientes

**Independent Test**: quickstart pasos 1-3 — build de `basa-admin-signer`, contract test
verde, emitir con flags, keyset intacto (sha256 antes==después), el `.lic` valida en el
propio artefacto y en el backend del producto

- [ ] T015 [P] [US1] Tests primero en
      `cli/basa_admin_signer/tests/test_license_issue.py`: emisión por flags produce
      `.lic` que `verifier.py` valida; emisión NO toca el keyset (FR-002/SC-002); expiry
      pasada/seats negativos → exit 2; payload con floats/campos extraños → rechazo
      fail-closed (research D1)
- [ ] T016 [US1] `cli/basa_admin_signer/basa_admin_signer/signing.py`: emisor que
      importa `licensing.token.canonical_payload_bytes` (fuente única, research D6),
      validador pre-firma fail-closed, escritura del `.lic` (base64url con padding) y
      registro en el ledger de emisiones (T011)
- [ ] T017 [US1] `cli/basa_admin_signer/basa_admin_signer/cmd_license.py`: comandos
      `issue` / `issue-dev` (defaults dev + advertencia `BASA_ALLOW_DEV_LICENSE`) /
      `verify` según contrato (`basa-admin-signer license ...`); wiring a
      signing/keycustody/ledger
- [ ] T018 [US1] `cmd_license.py`: `keyset export` (formato `# key_id:` del verifier,
      jamás material privado — FR-017) y `keyset rotate` (AGREGA kid, muestra
      antes/después, confirmación; retiro de kid viejo = flag aparte con confirmación
      doble) + tests CliRunner en `cli/basa_admin_signer/tests/test_keyset.py`
- [ ] T019 [US1] Contract test del artefacto en
      `cli/basa_admin_signer/tests/test_contract_artifact.py` (FR-020, parte 1): el `.pyz`
      de `basa-admin-signer` buildeado emite un `.lic` → `docker compose run backend` lo
      valida con `verify_license_blob` (cubre el empaquetado, quickstart paso 1)

**Checkpoint**: US1 entregable sola — Basa ya puede firmar sin editar código, desde un
artefacto que físicamente nunca sale de su estación de firma

## Phase 4: User Story 2 — Instalar un cliente de cero a corriendo, guiado (P1) 🎯 MVP mitad 2

**Artefacto**: exclusivamente `basa-admin` (FR-018). Ningún task de esta fase importa ni
referencia código de `cli/basa_admin_signer/`.

**Goal**: secuencia perfil → secretos → bundle → up → seed → licencia → admin → verify
sin editar scripts ni SQL, resolviendo los 7 hallazgos de research D4, enteramente desde
el artefacto que viaja en el bundle air-gapped

**Independent Test**: quickstart paso 4 — con un `.lic` de US1 (recibido como archivo
fuera de banda, nunca ejecutando `basa-admin-signer` en este host), la secuencia completa
de `basa-admin` contra el stack dev termina con `install verify` en verde

### Entrypoints de dominio (backend — superficie compartida, review @cluna-8)

- [ ] T020 [P] [US2] `backend/src/cli_entrypoints/seed_apply.py` (`python -m`):
      reemplaza `apply_profile_seed.py` con flags, `--dry-run` (diff del rename de tenant
      incluido), confirmación mostrando la DB objetivo, keys emitidas a archivo `600`
      (hallazgo 5: soporta seed con sección `tools:`) + tests en
      `backend/tests/unit/test_cli_entrypoints_seed.py`
- [ ] T021 [P] [US2] `backend/src/cli_entrypoints/admin_bootstrap.py`: crea/rota el
      admin sin SQL (password por stdin), pensado para correr ANTES de exponer el ingress
      — mata el TOFU raceable (hallazgo 7, #34) + tests en
      `backend/tests/unit/test_cli_entrypoints_admin.py`
- [ ] T022 [P] [US2] `backend/src/cli_entrypoints/license_genesis.py`: registro de
      génesis post-instalación (orden correcto respecto a admin/health gated — hallazgo
      7b) + test unit

### Comandos de `basa-admin` (host del cliente)

- [ ] T023 [P] [US2] `cli/basa_admin/basa_admin/profile.py` + comandos `install profile
      new/render`: scaffold desde example CON `tools:` (hallazgo 5), render con
      validación de layout/vars y golden-test contra la salida de `render_profile.sh` en
      `cli/basa_admin/tests/test_profile.py`
- [ ] T024 [P] [US2] `cli/basa_admin/basa_admin/secrets.py` + `install secrets gen`:
      secretos del compose prod con `secrets`/`os.urandom` a archivo `600`; regenerar pide
      confirmación + tests
- [ ] T025 [US2] `cli/basa_admin/basa_admin/bundle.py` + `install bundle create/verify` +
      `install load`: lockfile en vez de 7 env vars; verify contra MANIFEST por `.Id`
      (hallazgo 3); load **re-taggea desde el MANIFEST** (hallazgo 2); `bundle create`
      empaqueta el **layout completo de FR-021** — `bin/{basa-admin-x86_64.pyz,
      basa-admin-arm64.pyz}` (sha256 + versión de release en el MANIFEST, FR-022),
      `images/`, `manifests/`, `profiles/` **y genera `install.sh`** (detecta arch, copia
      el `.pyz`, fija permisos ejecutables, imprime próximos pasos — nunca pip/apt/yum ni
      índice externo, FR-023) — **nunca** empaqueta nada de `basa-admin-signer` + tests en
      `cli/basa_admin/tests/test_bundle.py`
- [ ] T026 [US2] `cli/basa_admin/basa_admin/stack.py` + `install up`: puebla los
      volúmenes `licenses`/`litellm_config`/`branding` que el camino compose deja
      huérfanos (hallazgo 1), levanta compose prod y hace poll de readiness propio con
      diagnóstico de crash-loop de alembic (hallazgo 4) + tests
- [ ] T027 [US2] `cli/basa_admin/basa_admin/cmd_license.py`: `install license verify`
      (sanity offline standalone previo a instalar, FR-018) e `install license install`
      (valida offline; **`--dry-run` muestra el diff entre la licencia instalada y la
      entrante — tenant/seats/expiry/kid — sin escribir; la aplicación real pide
      confirmación mostrando a qué deployment/DB apunta, FR-006**; luego puebla el
      volumen de licencia, restart del backend + poll de `/health/license` — hallazgo 6,
      singleton en memoria) + tests CliRunner (incluye caso dry-run sin mutación). Importa
      solo `verifier.py`/`token.py` del backend (research D6) — jamás
      `keycustody`/`signing` del signer
- [ ] T028 [US2] `install seed apply` / `install admin bootstrap`: wrappers de
      `basa-admin` hacia los entrypoints T020/T021 vía `docker compose exec` con la UX del
      contrato (dry-run/confirm/--yes) + tests
- [ ] T029 [US2] `install verify <slug>` + `install status`: smoke e2e (contenedores,
      licencia activa, gateway responde, masking en vivo — reutiliza checks existentes de
      `deploy/release/checks/`) y estado por paso de la secuencia + tests
- [ ] T030 [US2] Test de flujo completo en `cli/basa_admin/tests/test_install_flow.py`
      (CliRunner + stack dev): la secuencia entera del quickstart paso 4 en verde, usando
      únicamente `basa-admin` (el host de prueba no tiene `basa-admin-signer` instalado)

**Checkpoint**: MVP completo — firma (`basa-admin-signer`) + instalación guiada
(`basa-admin`), cada uno funcional de forma independiente

## Phase 5: Empaquetado y frontera de confianza (transversal, MVP — FR-016 a FR-023)

**Purpose**: verificar en build time, con tests automatizados, que la separación física
entre artefactos es real — no una convención de documentación. Esta fase no pertenece a
ninguna user story individual (spec.md la agrupa aparte, "transversal, MVP"); depende de
que US1 y US2 ya tengan artefactos buildeables (Phases 3-4).

- [ ] T031 [P] Test de inspección de artefacto en
      `cli/basa_admin/tests/test_artifact_boundary.py` (FR-020, parte 2 — **release
      gate obligatorio**): abre el `.pyz` de `basa-admin` recién buildeado como zip
      (`zipfile.ZipFile.namelist()`) y **falla el build** si aparece cualquiera de: los
      módulos `keycustody`/`signing`/`ledger` del signer, cualquier símbolo que firme con
      la privada del emisor, o una dependencia declarada hacia `basa_admin_signer`;
      complementa con un import-graph check (`modulefinder` o equivalente) sobre el entry
      point para detectar imports indirectos (research D6). Se corre para AMBAS
      arquitecturas (x86_64 y arm64)
- [ ] T032 [P] Test de contenido del bundle en
      `cli/basa_admin/tests/test_bundle_contents.py` (FR-021/FR-023 — **release gate
      obligatorio**): construye un bundle con `install bundle create` (T025) y afirma
      DOS cosas por separado: (1) **layout completo** — el tarball contiene exactamente
      los cinco top-level esperados por FR-021: `bin/{basa-admin-x86_64.pyz,
      basa-admin-arm64.pyz}`, `images/`, `manifests/`, `profiles/`, `install.sh` (falla si
      falta cualquiera, incluido `install.sh`, o si falta cualquiera de las dos
      arquitecturas del `.pyz`); (2) **escaneo del tarball COMPLETO** (`tarfile.getnames()`
      sobre todas las rutas, no solo `bin/`) que **falla** si aparece cualquier archivo
      `basa-admin-signer*` en **cualquier** ubicación del tarball — cubre tanto el caso
      obvio (dentro de `bin/`) como un descuido en `images/`, `manifests/`, `profiles/` o
      la raíz del tarball
- [ ] T033 Wiring del MANIFEST del bundle (FR-022): sha256 + versión de release de cada
      `basa-admin-<arch>.pyz` junto a imágenes/migraciones/perfiles/manifests — misma
      versión en todos; test de aserción del MANIFEST en
      `cli/basa_admin/tests/test_bundle_contents.py` (mismo archivo que T032, casos
      adicionales); incluye verificar que `install.sh` es ejecutable (`chmod +x`) y que
      copia el `.pyz` de la arquitectura detectada sin invocar pip/apt/yum ni ningún
      índice de paquetes externo (FR-023)
- [ ] T034 Guarda de regresión anti-runtime-gating (FR-019): extiende
      `cli/basa_admin/tests/test_artifact_boundary.py` (T031) con un grep estático sobre
      el código fuente de `basa_admin/` y `basa_admin_signer/` que falla si aparece
      cualquier flag de rol (`--role`), variable de entorno de gate (`BASA_ROLE`,
      `BASA_SIGNER_MODE` o similar) o grupo Click oculto (`hidden=True`) — documenta el
      invariante "solo separación física" como guardia automática, no solo como decisión
      de diseño
- [ ] T035 [P] Whitelabel extendido: strings de `--help`/errores de **ambos** `.pyz`
      (`basa-admin-signer` y `basa-admin`, todas las arquitecturas) pasan
      `check-whitelabel` (`prohibited_names.txt`) — añadir ambos binarios al alcance del
      check

**Checkpoint**: separación física verificada por tests automatizados en el gate de
release — ningún build puede violar la frontera signer/admin sin fallar CI

## Phase 6: Polish & Cross-Cutting

- [ ] T036 [P] Deprecar los scripts viejos con puntero al artefacto correspondiente
      (FR-012): `issue_dev_license.py` → banner apuntando a `basa-admin-signer license
      issue`; `apply_profile_seed.py`/`generate_trueup.py` → banner apuntando a
      `basa-admin install seed apply` / al comando `ops trueup export` (fase 2) — doc de
      migración en `backend/scripts/README.md`
- [ ] T037 [P] Docs DoD: página/runbook de **ambos** artefactos en la doc de producto
      (install-deploy actualizado para distinguir `basa-admin-signer` de `basa-admin`,
      prerrequisito Python 3.11+ añadido al perfil del partner en
      `docs/docs/install-deploy/partner-enablement.md`), gate `make -C deploy check-docs`
      verde
- [ ] T038 Actualizar `specs/ROADMAP-guardian.md` (026 → Implementada + PR) y el registro
      de superficies si aplica — en el MISMO PR (regla de mantenimiento del roadmap)
- [ ] T039 Quickstart completo de punta a punta (pasos 0-7 de quickstart.md, ambos
      artefactos + gates de separación + `install.sh` en un host limpio) como validación
      final + STOP & VALIDATE con JF antes del merge

## Dependencies & Execution Order

- **Setup (T001-T008)** → **Foundational (T009-T014)** → todo lo demás
- **US1 (T015-T019)**: independiente tras Foundational; T015 (tests) antes de
  T016-T018; T019 requiere T003/T005 (build del signer). No depende de nada de US2
- **US2 (T020-T030)**: independiente tras Foundational; los entrypoints T020-T022 y los
  comandos T023-T024 son paralelos entre sí; T025→T026→T027 en orden
  (bundle→up→license); T028 requiere T020/T021; T029-T030 al final. T027 usa un `.lic`
  de US1 (o el dev existente) como **archivo de entrada** — US2 es testeable sola con la
  licencia dev, sin ejecutar `basa-admin-signer`
- **Empaquetado/frontera (T031-T035)**: requiere que US1 (T019, build del signer) y US2
  (T025, build+bundle del admin) ya existan — T031/T034 verifican el `.pyz` de
  `basa-admin`, T032/T033 verifican el bundle de T025
- **Polish (T036-T039)**: tras el MVP y la fase de frontera; T036-T037 paralelas

## Parallel Example

```text
# Tras Foundational, dos frentes en paralelo (NO comparten archivos ni módulos):
Frente A (US1, cli/basa_admin_signer/): T015 → T016 → T017 → T018 → T019
Frente B (US2, cli/basa_admin/ + backend/):
  T020 + T021 + T022 + T023 + T024 (todas [P]) → T025 → T026 → T027 → T028 → T029 → T030

# Tras cerrar A y B, la fase de frontera corre sobre lo que ambos frentes produjeron:
T031 + T032 + T035 (paralelas, distintos archivos) → T033 → T034
```

## Implementation Strategy

**MVP first**: US1 sola ya entrega valor (Basa firma sin editar código, desde un
artefacto que nunca sale de su estación — desbloquea el piloto aunque la instalación siga
semi-manual). US2 completa el camino humano del lado partner/cliente. La fase de
empaquetado/frontera (T031-T035) es **no negociable antes de distribuir nada** — es la
única garantía de que `basa-admin` no arrastra el signer, y debe estar en verde antes de
armar el primer bundle real. Cada checkpoint es demostrable a JF por separado; STOP &
VALIDATE antes del merge (T039).
