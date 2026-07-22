# Contrato de comandos — `basa-admin` (026)

Contrato de la interfaz pública de la CLI (lo que un humano puede invocar y qué garantiza
cada comando). El detalle de flags puede evolucionar en implementación; **los invariantes
numerados no**. Árbol completo con fase en [inventario-scripts.md](../inventario-scripts.md).

## Invariantes globales

1. **Offline por defecto**: ningún comando del núcleo (`license`, `install`, `ops`) abre
   sockets de red salientes. Los comandos con red viven bajo un subárbol separado
   (`release`, `cloud`), se declaran como tales en su help, y **rehúsan correr** si
   detectan que están en una caja instalada (marker del deployment) salvo `--i-know`.
2. **Sin secretos en stdout/logs/args**: passwords y passphrases SOLO por prompt o stdin;
   material sensible generado va a archivo con permisos `600`. Los args se auditan
   sanitizados.
3. **Mutación = dry-run + confirmación**: todo comando que mute estado productivo (DB,
   keyset, licencia instalada) soporta `--dry-run` (muestra el cambio, no lo aplica) y
   pide confirmación interactiva; `--yes` la saltea para automatización consciente.
4. **Errores legibles**: precondición incumplida → mensaje que dice QUÉ falta y CÓMO
   resolverlo + exit code ≠ 0. Nunca un traceback crudo como salida esperada.
5. **Audit local**: todo comando que produce/muta registra una entrada en el audit-log
   local (data-model.md), sin contenido sensible.
6. **Exit codes**: `0` ok · `1` error de operación · `2` uso inválido/precondición ·
   `3` cancelado por el usuario · `4` verificación fallida (verify/bundle verify).

## `basa-admin license` (lado Basa — máquina de firma)

### `license issue`
- **Entrada**: `--tenant`, `--seats`, `--expiry` (obligatorios); `--distributor`, `--pool`,
  `--flags`, `--grace`, `--not-before`, `--out` (defaults sanos y documentados).
- **Garantías**: (a) produce un `.lic` cuya firma valida contra `verifier.py` del producto
  — el emisor importa `canonical_payload_bytes` como fuente única (contract test del
  artefacto en el gate);
  (b) **JAMÁS toca el keyset público** (invariante anti-foot-gun; la rotación es otro
  comando); (c) registra la emisión en el ledger local (supersede visible si ya había una
  para ese tenant); (d) pide la passphrase de la privada por prompt.
- **Errores**: sin privada → exit 2 con instrucción de `keyset rotate --init`; expiry en
  pasado o seats < 0 → exit 2.

### `license issue-dev`
- Igual que `issue` con defaults dev (kid `basa-dev-*`, expiry lejana) y advertencia de
  que solo sirve con `BASA_ALLOW_DEV_LICENSE=true`. Mismas garantías (b)-(d).

### `license keyset export`
- Emite el keyset público (kid + PEM, formato `# key_id:` de `verifier.py`) a un archivo.
  **Nunca** material privado.

### `license keyset rotate`
- **Único** comando que genera un par nuevo. Garantías: (a) **agrega** el kid nuevo al
  keyset, nunca reemplaza el archivo; (b) muestra qué kids existen antes y después y pide
  confirmación; (c) la privada nueva nace cifrada; (d) retirar un kid viejo es un flag
  aparte con confirmación doble y advertencia de cajas vivas.

### `license verify <archivo.lic>`
- Verificación offline de un `.lic` contra un keyset dado (sanity pre-envío). Exit 4 si
  no valida.

## `basa-admin install` (lado partner/operador — host de instalación)

Secuencia guiada; cada comando valida sus precondiciones y es re-ejecutable
(idempotente por paso). `install status <slug>` muestra en qué paso está la instalación.

### `install profile new <slug>` / `install profile render <slug>`
- `new`: scaffold desde `deploy/clients/example` con los datos pedidos por prompt/flags;
  garantiza `TENANT_SLUG` == slug del directorio.
- `render`: valida layout completo y variables del template ANTES de renderizar; una
  variable sin declarar → exit 2 nombrándola (no un `${VAR}` silencioso en el output).

### `install secrets gen`
- Genera los secretos de la instalación a archivo `600`. Nunca a stdout. Re-ejecución
  sobre secretos existentes pide confirmación (regenerar ≠ inocuo).

### `install bundle create <slug>` / `install bundle verify <tarball>`
- `create`: toma las refs+digests de un lockfile de release (no 7 env vars); verifica que
  todas las imágenes existan localmente ANTES del `docker save`.
- `verify`: contra el MANIFEST — presencia y digest de cada imagen. Exit 4 con lista
  exacta de faltantes/mismatches. **Correr `verify` antes de transferir es el contrato**
  que evita el pull-en-runtime en la caja airgap.

### `install load <bundle>` / `install up <slug>`
- `load`: `docker load` + re-verificación contra MANIFEST en el host destino.
- `up`: levanta el compose de producción del perfil, espera readiness (migraciones
  incluidas) y reporta el estado por servicio.

### `install seed apply`
- Aplica el seed del perfil vía el entrypoint del backend. Garantías: (a) `--dry-run`
  muestra el diff (incluido cualquier rename de tenant) sin commitear; (b) la aplicación
  real pide confirmación mostrando **a qué DB/deployment** apunta; (c) keys emitidas van
  a archivo `600`, jamás a stdout.

### `install license install <archivo.lic>`
- Valida el `.lic` offline ANTES de instalarlo; lo coloca donde el deployment lo lee
  (`BASA_LICENSE_TOKEN_FILE`); registra la génesis de la cadena de audit; muestra el
  estado resultante (`active`/`grace`/…) y explica cualquier estado ≠ active.

### `install admin bootstrap`
- Crea/actualiza el primer admin vía entrypoint del backend (cero SQL): username por flag,
  password por prompt/stdin. Sustituye el paso 8 manual del runbook (#34).

### `install verify <slug>`
- Smoke end-to-end post-instalación: contenedores arriba, licencia activa, gateway
  responde, masking/bloqueo en vivo (reutiliza los checks existentes del repo). Exit 4
  con el detalle del check que falló. Es el comando que cierra la instalación.

## `basa-admin ops` (día-2 — fase 2, contrato preliminar)

- `ops rotate-password` — rotación de admin vía entrypoint backend (cero SQL, prompt).
- `ops trueup export` — export firmado **a archivo nombrado** (nunca stdout).
- `ops license status` — diagnóstico offline del estado de licencia.
- `ops keyset update <keyset.pem>` — actualización del keyset en la caja con `--dry-run`
  y validación de que las licencias instaladas siguen verificando.
- `ops backup create/restore` — respaldo lógico incluyendo el `.lic`.

Los contratos finos de `ops` se fijan cuando entre la fase 2; los invariantes globales
1-6 ya les aplican.
