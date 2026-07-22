# Research — 026 CLI de operador (`basa-admin`)

**Fecha**: 2026-07-22 · **Método**: 4 investigaciones en paralelo (firma cross-lenguaje,
custodia de clave, arquitectura Go, mapa de integración con el stack), con la de firma
**verificada empíricamente en Docker** (golang 1.21/1.22/1.24 + la imagen real del backend
corriendo `verifier.py` del repo — no de memoria). Decisión de lenguaje: **Go** (JF,
22-jul). No quedan NEEDS CLARIFICATION.

## D1 — Canonicalización y firma: Go produce bytes idénticos a Python (verificado)

**Decisión**: el emisor Go construye el payload como `map[string]any` con valores tipados
(string, int, []string — **nunca** float ni structs) y canonicaliza con `json.Encoder`
sobre `bytes.Buffer` + `SetEscapeHTML(false)` + `TrimSuffix` del `\n` final. Con **Go ≥
1.22 fijado en `go.mod`** eso produce bytes **idénticos** a
`json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode("utf-8")`
dentro de un dominio validado **fail-closed**: el validador pre-firma rechaza floats,
U+2028/U+2029 y literales numéricos no decimales. Firma: `crypto/ed25519` stdlib (detached,
determinista RFC 8032, interop total con PyCA); PEM vía `encoding/pem` + `crypto/x509`
(PKCS8 privada / PKIX pública); `sig` con `base64.URLEncoding` (**con** padding — el
`urlsafe_b64decode` de Python revienta sin él). Al escribir una pública al keyset, emitir
la línea `# key_id: <kid>` antes del bloque PEM (formato que exige
`BasaPublicKeySet.from_pem_file`, verifier.py:57-72).

**Evidencia empírica** (corrida en contenedores): payload realista de 12 campos → hex Go
== hex Python; firma Go con clave PKCS8 de `cryptography` → `verify_license_blob` del repo
la acepta (incluido el chequeo de tenant); PEMs nacidos en Go cargan en `cryptography` y
viceversa; la firma es **byte-idéntica** entre PyCA y Go (habilita golden vectors con
comparación exacta).

**Gotchas que fundan el validador fail-closed** (cada uno probado):

- `json.Marshal` escapa HTML (`<>&`) por default; el único off es `Encoder.SetEscapeHTML(false)`.
- `Encoder.Encode` agrega `\n` final (Python no) → sin `TrimSuffix`, **ninguna** licencia
  verificaría jamás.
- U+2028/U+2029: Go los escapa SIEMPRE (todas las versiones), Python los emite crudos →
  **prohibirlos** pre-firma (sin workaround en stdlib).
- `\b`/`\f` divergen en Go < 1.22 → `go 1.22` mínimo en `go.mod`.
- Structs Go serializan en orden de declaración, no alfabético → solo `map[string]any`.
- Floats divergen de formato (1e20, -0.0) y `Unmarshal` a `map[string]any` pierde
  precisión > 2^53 → los números del payload son ints y el validador rechaza floats;
  entradas JSON se leen con `Decoder.UseNumber()` + regex `^-?(0|[1-9][0-9]*)$`.
- Bytes UTF-8 inválidos se reemplazan silenciosamente por � en Go → `utf8.Valid` pre-firma.

**Golden vectors** (el contrato anti-deriva): `backend/tests/licensing/golden/vectors.json`
**generado por Python** (`canonical_payload_bytes` es la referencia normativa: es lo
desplegado en las cajas), con clave Ed25519 SOLO-test commiteada. Cada vector =
`{name, payload, canonical_b64, sig_b64url}`. pytest asserta canónico+firma con
`verifier.py`; `go test` asserta canónico byte-a-byte Y firma exacta (válido por
determinismo Ed25519). Vectores adversariales (unicode, `<>&"'\`, `\n\t`, seats 0/grande,
flags vacía, sin issued_at) y negativos (float, U+2028, `1e21` → la CLI DEBE rechazar).
El gate suma un e2e: la CLI Go emite un `.lic` real → `verify_license_blob` Python lo valida.

**Alternativas rechazadas**: serializer canónico a mano (~100 líneas críticas innecesarias
— el dominio del payload cae completo en la zona byte-idéntica); JCS/RFC 8785 (cambiaría
`canonical_payload_bytes` YA desplegado en cajas — rompe el wire de la 021); firmar
base64 del payload estilo JWS (mismo problema); empaquetar el emisor Python con
PyInstaller (contradice el binario único distribuible).

## D2 — Custodia de la privada: archivo age cifrado con passphrase (scrypt)

**Decisión**: la privada Ed25519 vive ÚNICAMENTE como archivo **age armored** cifrado con
passphrase (`filippo.io/age` como librería: `ScryptRecipient`/`ScryptIdentity`), escrito
con `O_EXCL` + `0600` en dir `0700`. Passphrase SIEMPRE por prompt TTY
(`golang.org/x/term.ReadPassword`); **sin fallback por env en el MVP** (cosign tiene
`COSIGN_PASSWORD` para CI; nosotros explícitamente no). Para firmar: descifrar en memoria,
firmar, descartar. Migración: `key import` lee el PEM dev en claro, valida que su pública
coincide con el kid del keyset, escribe el `.age` y borra el PEM (best-effort, documentando
que en APFS/SSD el borrado no es forense — la dev ya fue rotada el 20-jul, riesgo bajo;
la clave PROD jamás pasa por un PEM en claro).

**Gotchas**: `O_EXCL` obligatorio (WriteFile trunca sin avisar — rima con FR-002);
`ScryptIdentity` con work factor default 22 explícito (header manipulado no cuelga la CLI);
TTY-only detectado con `IsTerminal` y error claro en pipes; Go no zeroiza strings →
passphrase como `[]byte` con overwrite best-effort (riesgo aceptado en máquina de firma
dedicada, anotado sin venderlo como mitigado); recovery-key = segundo archivo age aparte
(la API rechaza mezclar scrypt con X25519).

**Alternativas**: nacl/secretbox+argon2 a mano (reinventa lo que age resuelve auditado);
SOPS (orientado a YAML/env de deploy, no a una clave de firma de humano); keyring del OS
(no portable a la máquina de firma dedicada); go-securesystemslib/encrypted de cosign
(pre-1.0 aún en abr-2026). Patrón de referencia: cosign/minisign/age-keygen.

## D3 — Arquitectura del módulo Go

**Decisión**: módulo en **`cli/`** en la raíz (hermano de `backend/`, `frontend/`), con
`go.mod` propio y **`vendor/` commiteado**. Layout: `cli/cmd/basa-admin/main.go` +
`cli/internal/{cmdtree,license,install,profile,version}` + `cli/testdata/script/*.txtar`.
Framework: **spf13/cobra + pflag** (vendored, ~1-2 MB — no importar `cobra/doc`).
Prompts: `x/term.ReadPassword` + helper propio `confirm()` con bypass `--yes`; todo prompt
con camino stdin no-TTY (`--password-stdin` estilo docker login) para testscript/CI.
Testing: table-driven + **testscript (txtar)** para los flujos de comandos. Build **en
contenedor golang** (no exige Go en el host): `CGO_ENABLED=0`, `GOTOOLCHAIN=local` (evita
descarga de toolchain — ¡red! — en máquina airgap), `GOFLAGS=-mod=vendor`, cross-compile
linux/amd64 + linux/arm64 + darwin/arm64, versión embebida por ldflags; target integrado
al make de `deploy/`. **MVP = cero código de red por construcción** (sin imports de
net/http fuera de tests); el gate del repo lo verifica (grep de imports) — los comandos
[CLOUD] llegan en fase 2 como subárbol separado.

**Gotchas**: `.dockerignore` debe excluir `cli/` (el build context de backend/frontend usa
la raíz y engordaría con `vendor/`); los strings de `--help`/errores del binario viajan en
el bundle → aplican los checks **white-label** (`prohibited_names.txt`); el binario (ambas
arch linux) va DENTRO del tarball air-gapped con sha256 en el MANIFEST — mismo edge case
que las imágenes: artefacto fuera del tarball = install roto sin egress.

## D4 — Integración con el stack: "Go orquesta, Python ejecuta dominio"

**Decisión**: la CLI implementa **nativo en Go** todo lo que es archivos/docker/HTTP
(profile scaffold/render con golden-test contra la salida del bash actual, secrets gen con
`crypto/rand`, bundle create/verify/load, up + readiness poll, license verify) y **shellea
a entrypoints Python endurecidos** (`docker compose exec backend python -m ...`) para todo
lo que toca modelos SQLAlchemy (seed, admin bootstrap/rotate, génesis). Reimplementar el
dominio en Go = drift garantizado con los modelos; la CLI no habla libpq directo (además
mantendría CGO_ENABLED=0). Los entrypoints Python nuevos nacen con flags, `--dry-run` y
confirmación — el endurecimiento es parte de esta spec, no un wrapper sobre los scripts
horribles actuales (FR-012).

**Hallazgos que la implementación DEBE resolver** (todos con evidencia archivo:línea):

1. **Los 3 volúmenes nombrados de `compose.prod.yml` nadie los puebla en el camino
   compose** (`licenses`, `litellm_config`, `branding` — solo cloud-init los escribe en el
   camino tofu): `install up`/`license install` deben poblarlos o el stack prod arranca
   sin licencia/config/marca.
2. **`docker save` por referencia `@sha256` produce imágenes sin RepoTags** tras `docker
   load` → compose no resuelve y dispara pull (= install roto en airgap): `install load`
   debe **re-taggear desde el MANIFEST**.
3. El MANIFEST guarda el `.Id` local, no el RepoDigest → `bundle verify` compara contra
   `.Id` post-load (comparar contra los pins `@sha256` daría mismatch siempre).
4. `compose.prod.yml` no tiene healthchecks y alembic corre en el entrypoint con
   `set -euo` (migración fallida = crash-loop): el readiness de `install up` es un poll
   propio de la CLI con diagnóstico del crash-loop.
5. El seed del perfil example **no trae sección `tools:`** → sin Connections/keys, el
   smoke de `install verify` no tendría key que usar: `profile new` scaffoldea el seed
   completo (schema de `backend/config/clients.example.yaml:26-38`).
6. El estado de licencia es un **singleton en memoria** (entitlement.py:67,153-186):
   `license install` con el backend corriendo requiere restart + poll de
   `/health/license`.
7. El **bootstrap admin actual es TOFU raceable** (el primer POST /login crea el admin —
   api/users.py:35-44): `install admin bootstrap` corre ANTES de exponer el ingress, y el
   orden con la génesis importa (`/health/license` detallado está gated a admin).

## D5 — Ledger local de emisiones y audit-log de la CLI

**Decisión**: ambos como **JSONL append-only** locales (data-model.md). El ledger de
emisiones (lado Basa) da visibilidad humana del cupo por pool con hash-encadenado para
detectar ediciones; **no** pretende el enforcement duro del cupo (eso es el portal, fase
posterior de #33 — coherente con FR-030 de la 021 que ya ubica esa validación fuera de la
caja). El audit-log de la CLI registra comando/args sanitizados/resultado, metadata-only,
exportable como archivo — trazabilidad sin egress (FR-013).

**Alternativa rechazada**: SQLite local — dependencia cgo (rompe binario estático) o
driver puro menos maduro, para un problema que JSONL + hash chain resuelve; el estado
autoritativo de seats vive en el true-up de cada caja (021), no acá.

## Fuera de alcance (confirmado)

- Portal de emisión con enforcement de cupo (forma completa del #33): fase posterior.
- Los 3 fixes out-of-repo (#35): se cierran como PR del producto (ruta 020), no como
  comandos CLI.
- Comandos [CLOUD] (`release publish`, `cloud apply`) y `ops` día-2: fase 2 (el contrato
  preliminar de `ops` queda en contracts/).
- KMS/HSM para la privada: fase 2; el MVP es age+passphrase en máquina de firma dedicada.
