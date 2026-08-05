# Inventario de operaciones manuales -> CLI (grounding de la spec 026)

**Fecha**: 2026-07-22 · **Método**: barrido de 4 ángulos (scripts, SQL/DB, docs, flujo install) + síntesis. **54 operaciones** relevadas sobre el código real; este doc es la evidencia que funda el árbol de comandos y el recorte MVP de la [spec](./spec.md).

## Foot-guns críticos hallados (por qué la CLI, no solo azúcar)

- **`issue_dev_license.py` regenera el par Ed25519 y sobrescribe el keyset público en CADA corrida** -> invalida en silencio toda caja ya instalada. Payload hardcodeado (sin flags). Privada escrita sin cifrar. -> FR-001/FR-002/FR-003.
- **`apply_profile_seed.py` renombra el tenant productivo y commitea sin confirmación ni dry-run** (2 args posicionales, cero validación). -> FR-006/FR-007.
- **`generate_trueup.py` vuelca el JSON firmado a stdout** (si falta el redirect se pierde); envío a Basa fuera de banda sin tracking. -> FR-009/FR-013.
- **Bootstrap/rotación de admin = SQL crudo** (issue #34). -> FR-008.
- **`bundle.sh`/`publish.sh`: 7 imágenes por env var, digests copiados a mano** -> un typo apunta el deploy a otra imagen; una imagen faltante dispara pull en runtime en la caja airgap. -> FR-005 (verify pre-transferencia).

## Árbol de comandos propuesto

**MVP** = firma de licencias + instalación mínima a stack corriendo/verificado.

### `basa-admin-signer license` — firma interna Basa

> Artefacto separado (`basa-admin-signer`), corre únicamente en la estación de firma
> aislada de Basa; nunca se entrega a partners/clientes ni viaja en el bundle air-gapped
> (spec.md Clarifications — Session 2026-08-05; FR-016/FR-017).

- 🟢 MVP — `basa-admin-signer license issue-dev --tenant <id> --seats 50 --expiry 2099-01-01 --out ./license_out [--rotate-keys]`
  - Emitir licencia dev/demo (par Ed25519 + firma + escribir keyset)
- 🟢 MVP — `basa-admin-signer license issue --tenant <id> --seats N --expiry <fecha> --out <slug>.lic`
  - Emitir licencia de produccion firmada (tenant/seats/expiry)
- 🟢 MVP — `basa-admin-signer license keyset export --kid <kid> --out basa_public_keys.pem`
  - Exportar/publicar el keyset publico del emisor (kid + clave)
- 🔵 fase 2 — `basa-admin-signer license deployment-key register --tenant <id> --pubkey <file.pem>`
  - Registrar la deployment key publica que envia el operador (out-of-band)
- 🔵 fase 2 — `basa-admin-signer license trueup verify <trueup.json> --genesis <genesis_license_id>`
  - Verificar el TrueUpExport firmado del cliente contra su genesis

### `basa-admin install` — partner/cliente

- 🟢 MVP — `basa-admin install profile new <slug> --domain <base> --region eu-central-1 --model <deployment> --from example`
  - Crear el perfil del cliente (scaffold desde example)
- 🟢 MVP — `basa-admin install profile render <slug>`
  - Renderizar el perfil (config.yaml + brand.json + instance.env)
- 🟢 MVP — `basa-admin install secrets gen --out secrets.env`
  - Generar los secretos de la instalacion (on-prem/compose)
- 🟢 MVP — `basa-admin install bundle create <slug> --from-lockfile release.lock [--out DIR] && basa-admin install bundle verify <tarball>`
  - Generar y verificar el bundle air-gapped (docker save de las 7 imagenes + perfil + MANIFEST)
- 🟢 MVP — `basa-admin install load <bundle.tar.gz> --verify`
  - Transferir tarball, docker load y verificar contra MANIFEST en el host
- 🟢 MVP — `basa-admin install up <slug> --profile selfhosted`
  - Levantar el stack (compose --profile selfhosted, incluye alembic + readiness)
- 🟢 MVP — `basa-admin install seed apply --tenant <slug> --file seed.yaml [--emit-keys-to keys.txt] [--dry-run]`
  - Sembrar tenant (slug) + clients + connections/keys + budgets desde el perfil
- 🟢 MVP — `basa-admin install license install <archivo.lic> --record-genesis`
  - Instalar la licencia firmada + registrar la genesis de la cadena
- 🟢 MVP — `basa-admin install admin bootstrap --username admin --password-stdin`
  - Bootstrap del primer admin (reemplaza el TOFU por primer login)
- 🟢 MVP — `basa-admin install verify <slug> --containers --license --gateway`
  - Smoke test / verificacion end-to-end post-deploy
- 🔵 fase 2 — `basa-admin install docs brand render <slug> --brand <brand.json> [--build]`
  - Renderizar el brand-pack del sitio de docs (overlay mkdocs + CSS + logo)
- 🔵 fase 2 — `basa-admin install seed verify --profile <slug>`
  - Verificar idempotencia del seed en DB desechable aislada
- 🔵 fase 2 — `basa-admin install release build --all --check` · ⚠️ requiere red (máquina de build, no la caja)
  - [CLOUD] Build + validar artefactos de release (make build/check)
- 🔵 fase 2 — `basa-admin install release publish --registry <reg> --version <semver> --into <slug>` · ⚠️ requiere red (máquina de build, no la caja)
  - [CLOUD] Publicar imagenes al registry y escribir digests a release.lock
- 🔵 fase 2 — `basa-admin install cloud apply <slug> --region eu --state-bucket <bucket>` · ⚠️ requiere red (máquina de build, no la caja)
  - [CLOUD] Provisionar infra con OpenTofu (init/workspace/tfvars/apply/outputs)

### `basa-admin ops` — operador-dia2

- 🔵 fase 2 — `basa-admin ops rotate-password --username admin`
  - Rotar la password del admin (hoy por SQL crudo)
- 🔵 fase 2 — `basa-admin ops set-email --username admin --email <email>`
  - Corregir el email del admin bootstrap heredado (.local)
- 🔵 fase 2 — `basa-admin ops backup create [--out dir] && basa-admin ops backup restore <archivo>`
  - Backup y restore logico de Postgres (+ incluir el .lic)
- 🔵 fase 2 — `basa-admin ops trueup export [-o trueup-YYYY-MM-DD.json]`
  - Exportar el true-up firmado (renovacion)
- 🔵 fase 2 — `basa-admin ops deployment-key rotate --reregister`
  - Rotar la deployment key (firma de true-ups)
- 🔵 fase 2 — `basa-admin ops keyset update <keyset.pem> [--dry-run]`
  - Actualizar/rotar el keyset publico del emisor en la caja
- 🔵 fase 2 — `basa-admin ops engine bump <digest> --run-contract-tests` · ⚠️ requiere red (máquina de build, no la caja)
  - Actualizar la imagen del motor (bump digest + contract tests)
- 🔵 fase 2 — `basa-admin ops license status`
  - Estado de la licencia (diagnostico offline)
- 🔵 fase 2 — `basa-admin ops fix frontend-prod  (mejor: cerrarlos como PR en el repo, no como comando CLI)`
  - Materializar en el repo los 3 fixes de deploy out-of-repo (frontend prod)

## Notas airgap

La CLI es una herramienta LOCAL que le da la mano a un humano: corre en el host (o en la maquina de firma de Basa) y nunca hace phone-home. Todos los comandos del MVP son airgap_safe=true y operan solo sobre entradas y salidas en disco: `license issue`/`issue-dev` firman con la clave privada local y producen un .lic + keyset.pem; `bundle create` empaqueta imagenes por docker save contra un release.lock ya presente localmente (verifica presencia antes del save, cero pull en runtime); `load`/`up`/`seed`/`license install`/`verify` hablan con Docker, Postgres y el filesystem del propio host, sin salir a internet. La verificacion de licencia y de true-up es 100% offline (Ed25519 contra el keyset embebido, sin llamar al emisor). El true-up y el registro de la deployment-key publica se entregan como ARCHIVOS que el operador transporta fuera de banda (USB/SFTP/mail), no como trafico de red del producto hacia el fabricante. Las virtual keys en claro se escriben a un archivo con permisos 600 en vez de a stdout. Los unicos comandos que NO son airgap-safe estan explicitamente marcados (airgap_safe=false) y son de fabricacion/cloud (`release build`, `release publish`, `cloud apply`, `engine bump`): requieren red o registry y viven en la maquina de build del partner, nunca en la caja airgapped del cliente. Regla de diseno: si un comando necesitara egress, se marca y se separa; el nucleo de firmar+instalar+operar no toca la red.

## Preguntas de diseño y estado de resolución

Este documento sigue siendo el grounding histórico (barrido del 2026-07-22) que fundó el
árbol de comandos y el recorte MVP. Las preguntas que quedaron abiertas en esa fecha se
revisan acá contra el estado actual de spec.md/research.md/data-model.md/tasks.md,
incluida la sesión de clarificación del 2026-08-05. No se inventan decisiones nuevas:
donde el artefacto actual no fija una respuesta final, la pregunta queda ABIERTA.

- **[RESUELTA] Lenguaje/runtime de la CLI**: ¿Go vs Python?
  - **Resolución**: Python 3.11+, `click` + `cryptography`, distribuido como zipapp
    `.pyz` (vía `shiv`) por arquitectura. La alternativa Go se investigó a fondo y quedó
    descartada (registrada por trazabilidad, no por descarte apresurado).
  - **Fuente**: research.md D1–D3 (incluye "Alternativa Go — evaluada, viable,
    descartada"); plan.md.

- **[RESUELTA] Dónde vive el ledger del cupo/seats/génesis mientras no hay portal**
  - **Resolución**: ledger local **JSONL append-only con hash-encadenado** (lado Basa),
    da visibilidad humana del cupo consumido por pool; **no** hace enforcement duro (eso
    vive en el portal, fase posterior de #33). El estado autoritativo de seats sigue
    siendo el true-up + génesis de cada caja.
  - **Fuente**: research.md D5; data-model.md § "Ledger local de emisiones (lado Basa)".

- **[RESUELTA] Custodia de la clave privada de firma prod**
  - **Resolución**: PEM **PKCS8 cifrado** con `BestAvailableEncryption` (lib
    `cryptography`, cero deps nuevas), escritura `O_EXCL`+`0600` en dir `0700`,
    passphrase siempre por prompt sin eco (sin fallback por env en el MVP). KMS/HSM
    queda diferido a fase 2. Nota: el RBAC de "quién puede correr `license issue`" sigue
    coordinándose con la spec 017 (Cristian) — ese punto puntual no está cerrado acá,
    pero el mecanismo de custodia sí.
  - **Fuente**: research.md D2; spec.md FR-003 y § Assumptions ("Custodia de la privada"
    y "Frontera con seguridad").

- **[RESUELTA] Empaquetado y distribución de la propia CLI**
  - **Resolución**: **dos artefactos físicamente separados** — `basa-admin-signer`
    (interno Basa, estación de firma aislada, nunca se entrega a partners/clientes ni
    viaja en el bundle) y `basa-admin` (partner/cliente, único artefacto dentro del
    bundle air-gapped). Un binario único gateado por rol/flag/env var queda
    explícitamente rechazado como alternativa válida; la separación se verifica en build
    time con contract test + test de inspección de artefacto.
  - **Fuente**: spec.md § Clarifications — Session 2026-08-05; FR-016 a FR-023.

- **[RESUELTA] Punto de ejecución**
  - **Resolución**: la CLI en el host orquesta archivos/Docker de forma nativa (profile
    scaffold/render, secrets gen, bundle create/verify/load, up + readiness, license
    verify/issue) y **shellea a entrypoints `python -m` endurecidos** dentro del
    contenedor backend para lo que toca modelos SQLAlchemy con la DB del deployment
    (seed, admin bootstrap/rotate, génesis) — el host no arrastra SQLAlchemy/psycopg ni
    credenciales de DB.
  - **Fuente**: research.md D4 ("la CLI orquesta, los entrypoints ejecutan dominio");
    plan.md.

- **[ABIERTA] Rotación de keyset con múltiples kid en paralelo en airgap**
  - **Estado**: data-model.md fija que ninguna transición puede ELIMINAR un kid con
    licencias vivas **conocidas por esa caja** (bloqueo salvo `--force` con confirmación
    doble), pero eso no resuelve el problema de fondo: cómo se valida que TODAS las
    cajas desplegadas (que la CLI no conoce) siguen verificando antes de retirar un kid
    viejo. Ningún artefacto define ese mecanismo cross-fleet todavía.
  - **Fuente parcial**: data-model.md § "Estados y transiciones relevantes" (Keyset).

- **[RESUELTA] Auditoría sin red**
  - **Resolución**: audit-log local **JSONL append-only por máquina**, metadata-only
    (`ts, comando, args_sanitizados, resultado, operador`, sin secretos ni payloads),
    exportable como archivo junto al true-up.
  - **Fuente**: research.md D5; data-model.md § "Audit-log local de la CLI (ambos
    lados)"; FR-013.

- **[RESUELTA] Los 3 fixes out-of-repo (#35)**
  - **Resolución**: se cierran como **PR en el repo** (parte del producto, no comando de
    la CLI); la ruta 020 los supersede. Confirmado explícitamente, no como comando
    `ops fix frontend-prod` (que queda documentado más abajo solo por trazabilidad
    histórica del inventario).
  - **Fuente**: research.md § "Fuera de alcance (confirmado)"; spec.md § Assumptions
    ("Los 3 fixes out-of-repo").

- **[RESUELTA] Estrategia de migración de los scripts sueltos**
  - **Resolución**: la CLI **reemplaza** (no envuelve indefinidamente)
    `issue_dev_license.py`, `apply_profile_seed.py`, `generate_trueup.py` y los
    `.sh` sueltos; los scripts quedan deprecados con banner + puntero de migración. El
    detalle del tenant `DEFAULT` hardcodeado se resuelve en la práctica vía el flag
    `--tenant` explícito ya presente en el árbol de comandos (`install seed apply
    --tenant <slug>`), pero ningún artefacto documenta aparte una migración formal del
    modelo "una instancia = un tenant".
  - **Fuente**: spec.md FR-012; tasks.md T025.

- **[ABIERTA] Recordatorio de renovación sin red**
  - **Estado**: ningún artefacto (spec/research/data-model/tasks) define un check local
    en `verify`/`license status` que alerte por días restantes antes de que venza el
    true-up (grace/expired). Sigue sin definirse.
  - **Fuente**: no hay fuente — confirmado ausente en spec.md, research.md,
    data-model.md y tasks.md.
