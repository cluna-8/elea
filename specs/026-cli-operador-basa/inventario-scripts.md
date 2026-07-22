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

### `basa-admin license` — basa-firma

- 🟢 MVP — `basa-admin license issue-dev --tenant <id> --seats 50 --expiry 2099-01-01 --out ./license_out [--rotate-keys]`
  - Emitir licencia dev/demo (par Ed25519 + firma + escribir keyset)
- 🟢 MVP — `basa-admin license issue --tenant <id> --seats N --expiry <fecha> --out <slug>.lic`
  - Emitir licencia de produccion firmada (tenant/seats/expiry)
- 🟢 MVP — `basa-admin license keyset export --kid <kid> --out basa_public_keys.pem`
  - Exportar/publicar el keyset publico del emisor (kid + clave)
- 🔵 fase 2 — `basa-admin license deployment-key register --tenant <id> --pubkey <file.pem>`
  - Registrar la deployment key publica que envia el operador (out-of-band)
- 🔵 fase 2 — `basa-admin license trueup verify <trueup.json> --genesis <genesis_license_id>`
  - Verificar el TrueUpExport firmado del cliente contra su genesis

### `basa-admin install` — partner-instala

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

## Preguntas abiertas (para /speckit-plan y /speckit-clarify)

- Lenguaje/runtime de la CLI: Go (binario estatico unico, ideal airgap, cross-compile, sin runtime que instalar en la caja) vs Python (reusa canonical_payload_bytes, src/licensing/verifier.py y services/onboarding.py del backend pero arrastra interprete). Si es Go, la firma Ed25519 se reimplementa o se llama a la lib del backend?
- Donde vive el ledger del cupo/seats y de la genesis en Basa mientras no hay portal (#33): la CLI de firma mantiene un registro local (archivo/SQLite firmado) de que licencias emitio por tenant, o es stateless y el estado autoritativo vive en el true-up + genesis de cada caja? Esto condiciona `trueup verify` y la renovacion.
- Custodia de la clave privada de firma prod: DIY Ed25519 en archivo cifrado para el MVP y KMS/HSM en Fase 2, o KMS desde el dia 1? El research dijo DIY Ed25519; hay que decidir el envelope (age/SOPS?) y quien puede correr `license issue`.
- Empaquetado y distribucion de la propia CLI: un unico binario con subcomandos gateados por rol/clave (basa-firma vs partner vs operador) o binarios separados? Se distribuye dentro del bundle airgap o se instala aparte en cada maquina (firma de Basa / build del partner / host del cliente)?
- Punto de ejecucion: la CLI corre en el host FUERA del contenedor hablando a Postgres y a los volumenes, o sigue envolviendo docker exec? Hoy los scripts corren dentro del container con cwd=/app; una 'tool local' necesita definir esto para seed/license install/admin bootstrap.
- Rotacion de keyset con multiples kid en paralelo en airgap: como valida `keyset update` que TODAS las licencias vivas verifican antes de retirar el kid viejo si la CLI no conoce todas las cajas desplegadas? Se valida solo contra las licencias instaladas en ESA caja?
- Auditoria sin red: donde se registran los eventos de la CLI (issue, rotate, install, seed) si no hay egress? Un audit-log local firmado por caja/por maquina de firma, exportable como archivo?
- Los 3 fixes out-of-repo (API_BASE en api.ts, vite.config/tsconfig, frontend.prod + SPA fallback): se cierran en el repo como parte del producto (recomendado) en vez de exponerse como comandos CLI? Confirmar que la ruta 020 los supersede y cerrar la deuda del onboarding VPS.
- Estrategia de migracion de los scripts sueltos: la CLI reemplaza issue_dev_license.py / apply_profile_seed.py / generate_trueup.py o los envuelve durante una transicion? Que pasa con el tenant DEFAULT hardcodeado y el modelo 'una instancia = un tenant' al pasar a comandos con --tenant explicito?
- Recordatorio de renovacion sin red: como se avisa que el true-up esta por vencer (grace/expired) si no hay canal del producto hacia Basa? Un check local en `verify`/`license status` que alerte por dias restantes?
