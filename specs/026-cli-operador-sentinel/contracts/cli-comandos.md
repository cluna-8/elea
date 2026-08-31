# Contrato de comandos — `sentinel-admin-signer` + `sentinel-admin` (026)

Contrato de la interfaz pública de **dos artefactos físicamente separados** (spec.md §
Clarifications — Session 2026-08-05; FR-016 a FR-023): lo que un humano puede invocar en
cada uno y qué garantiza cada comando. El detalle de flags puede evolucionar en
implementación; **los invariantes numerados no**. Árbol completo con fase en
[inventario-scripts.md](../inventario-scripts.md).

## Invariantes globales

1. **Offline por defecto**: ningún comando del núcleo de ninguno de los dos artefactos
   (`license` en `sentinel-admin-signer`; `install`/`ops` en `sentinel-admin`) abre sockets de red
   salientes. Los comandos con red viven bajo un subárbol separado (`release`, `cloud`) de
   `sentinel-admin`, se declaran como tales en su help, y **rehúsan correr** si detectan que
   están en una caja instalada (marker del deployment) salvo `--i-know`.
2. **Sin secretos en stdout/logs/args**: passwords y passphrases SOLO por prompt o stdin;
   material sensible generado va a archivo con permisos `600`. Los args se auditan
   sanitizados.
3. **Mutación = dry-run + confirmación**: todo comando que mute estado productivo (DB,
   keyset, licencia instalada) soporta `--dry-run` (muestra el cambio, no lo aplica) y
   pide confirmación interactiva; `--yes` la saltea para automatización consciente.
4. **Errores legibles**: precondición incumplida → mensaje que dice QUÉ falta y CÓMO
   resolverlo + exit code ≠ 0. Nunca un traceback crudo como salida esperada.
5. **Audit local**: todo comando que produce/muta registra una entrada en el audit-log
   local de SU artefacto (data-model.md), sin contenido sensible. No hay audit-log
   compartido entre `sentinel-admin-signer` y `sentinel-admin`.
6. **Exit codes**: `0` ok · `1` error de operación · `2` uso inválido/precondición ·
   `3` cancelado por el usuario · `4` verificación fallida (verify/bundle verify).
7. **Separación física, no runtime** (FR-016/FR-019/FR-020): `sentinel-admin-signer` y
   `sentinel-admin` son artefactos de build distintos, sin subcomandos ocultos, flags de rol
   ni gates por variable de entorno como sustituto. `sentinel-admin` no contiene físicamente
   los comandos de emisión/custodia de este contrato — están fuera de su binario, no solo
   fuera de su `--help`.

## `sentinel-admin-signer license` (interno Sentinel — estación de firma aislada)

> Nunca se entrega a partners/clientes ni viaja en el bundle air-gapped (FR-017/FR-021).

### `license issue`
- **Comando**: `sentinel-admin-signer license issue --tenant <id> --seats N --expiry <fecha> --out <slug>.lic`
- **Entrada**: `--tenant`, `--seats`, `--expiry` (obligatorios); `--distributor`, `--pool`,
  `--flags`, `--grace`, `--not-before`, `--out` (defaults sanos y documentados).
- **Garantías**: (a) produce un `.lic` cuya firma valida contra `verifier.py` del producto
  — el emisor importa `canonical_payload_bytes` como fuente única (contract test del
  artefacto en el gate, research.md D1/D6);
  (b) **JAMÁS toca el keyset público** (invariante anti-foot-gun; la rotación es otro
  comando); (c) registra la emisión en el ledger local de `sentinel-admin-signer` (supersede
  visible si ya había una para ese tenant); (d) pide la passphrase de la privada por
  prompt.
- **Errores**: sin privada → exit 2 con instrucción de `keyset rotate --init`; expiry en
  pasado o seats < 0 → exit 2.

### `license issue-dev`
- **Comando**: `sentinel-admin-signer license issue-dev --tenant <id> --seats 50 --expiry 2099-01-01 --out ./license_out`
- Igual que `issue` con defaults dev (kid `sentinel-dev-*`, expiry lejana) y advertencia de
  que solo sirve con `SENTINEL_ALLOW_DEV_LICENSE=true`. Mismas garantías (b)-(d).

### `license keyset export`
- **Comando**: `sentinel-admin-signer license keyset export --kid <kid> --out sentinel_public_keys.pem`
- Emite el keyset público (kid + PEM, formato `# key_id:` de `verifier.py`) a un archivo.
  **Nunca** material privado. Es el archivo que después consume `sentinel-admin` para
  `license verify` — nunca se regenera del lado `sentinel-admin` (research.md D6).

### `license keyset rotate`
- **Comando**: `sentinel-admin-signer license keyset rotate [--retire-kid <kid> --force]`
- **Único** comando que genera un par nuevo. Garantías: (a) **agrega** el kid nuevo al
  keyset, nunca reemplaza el archivo; (b) muestra qué kids existen antes y después y pide
  confirmación; (c) la privada nueva nace cifrada; (d) retirar un kid viejo es un flag
  aparte con confirmación doble y advertencia de cajas vivas (la validación cross-fleet
  sigue ABIERTA — ver inventario-scripts.md).

### `license verify <archivo.lic>`
- **Comando**: `sentinel-admin-signer license verify <archivo.lic> --keyset <keyset.pem>`
- Verificación offline de un `.lic` contra un keyset dado (sanity pre-envío, lado Sentinel).
  Exit 4 si no valida. Usa solo `verifier.py` (público) — la misma función que expone
  `sentinel-admin install license verify` del lado partner/cliente (research.md D6).

## `sentinel-admin install` (lado partner/cliente — host de instalación, distribuido en el bundle)

Secuencia guiada; cada comando valida sus precondiciones y es re-ejecutable
(idempotente por paso). `install status <slug>` muestra en qué paso está la instalación.
Ninguno de estos comandos importa código de `sentinel-admin-signer` (research.md D6, test de
inspección de artefacto FR-020).

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
  todas las imágenes existan localmente ANTES del `docker save`; empaqueta el layout
  completo de FR-021 — `bin/{sentinel-admin-x86_64.pyz, sentinel-admin-arm64.pyz}` (sha256 en el
  MANIFEST), `images/`, `manifests/`, `profiles/` **y genera `install.sh`** (el único
  mecanismo sancionado para colocar `sentinel-admin` en el host destino: detecta la
  arquitectura, copia el `.pyz` correspondiente, fija permisos ejecutables e imprime los
  próximos pasos — nunca invoca pip/apt/yum ni un índice externo, FR-023). `sentinel-admin-signer`
  **nunca** entra a este tarball, en ninguna ruta.
- `verify`: contra el MANIFEST — presencia y digest de cada imagen **y del layout
  completo del bundle** (`bin/`, `images/`, `manifests/`, `profiles/`, `install.sh`).
  Exit 4 con lista exacta de faltantes/mismatches, incluyendo cualquier archivo
  `sentinel-admin-signer*` encontrado en el tarball (nunca debería aparecer — FR-021).
  **Correr `verify` antes de transferir es el contrato** que evita el pull-en-runtime en
  la caja airgap.

### `install load <bundle>` / `install up <slug>`
- `load`: `docker load` + re-verificación contra MANIFEST en el host destino.
- `up`: levanta el compose de producción del perfil, espera readiness (migraciones
  incluidas) y reporta el estado por servicio.

### `install seed apply`
- Aplica el seed del perfil vía el entrypoint del backend. Garantías: (a) `--dry-run`
  muestra el diff (incluido cualquier rename de tenant) sin commitear; (b) la aplicación
  real pide confirmación mostrando **a qué DB/deployment** apunta; (c) keys emitidas van
  a archivo `600`, jamás a stdout.

### `install license verify <archivo.lic>`
- Verificación offline standalone de un `.lic` contra el keyset ya presente en el host
  (FR-018), sin instalarlo — sanity previo al paso real. Misma función de `verifier.py`
  que usa `sentinel-admin-signer license verify` (research.md D6); exit 4 si no valida.

### `install license install <archivo.lic>`
- Valida el `.lic` offline ANTES de instalarlo. **Mutación de estado productivo → dry-run
  + confirmación (FR-006)**: (a) `--dry-run` muestra el diff entre la licencia actualmente
  instalada (si hay una) y la entrante (tenant, seats, expiry, kid) sin escribirla; (b) la
  aplicación real pide confirmación mostrando **a qué deployment/DB** apunta, igual que
  `install seed apply`; `--yes` la saltea para automatización consciente (invariante
  global 3). Luego la coloca donde el deployment lo lee (`SENTINEL_LICENSE_TOKEN_FILE`);
  registra la génesis de la cadena de audit; muestra el estado resultante
  (`active`/`grace`/…) y explica cualquier estado ≠ active.

### `install admin bootstrap`
- Crea/actualiza el primer admin vía entrypoint del backend (cero SQL): username por flag,
  password por prompt/stdin. Sustituye el paso 8 manual del runbook (#34).

### `install verify <slug>`
- Smoke end-to-end post-instalación: contenedores arriba, licencia activa, gateway
  responde, masking/bloqueo en vivo (reutiliza los checks existentes del repo). Exit 4
  con el detalle del check que falló. Es el comando que cierra la instalación.

## `sentinel-admin ops` (día-2 — fase 2, contrato preliminar)

- `ops rotate-password` — rotación de admin vía entrypoint backend (cero SQL, prompt).
- `ops trueup export` — export firmado **a archivo nombrado** (nunca stdout).
- `ops license status` — diagnóstico offline del estado de licencia.
- `ops keyset update <keyset.pem>` — actualización del keyset en la caja con `--dry-run`
  y validación de que las licencias instaladas siguen verificando.
- `ops backup create/restore` — respaldo lógico incluyendo el `.lic`.

Los contratos finos de `ops` se fijan cuando entre la fase 2; los invariantes globales
1-7 ya les aplican. Qué artefacto aloja `ops` (¿`sentinel-admin`? ¿un tercer artefacto?) no
está decidido — ver inventario-scripts.md.
