# Research — 026 CLI de operador (`basa-admin`)

**Fecha**: 2026-07-22 · **Método**: 4 investigaciones en paralelo (firma cross-lenguaje,
custodia de clave, arquitectura, mapa de integración con el stack), la de firma
**verificada empíricamente en Docker** contra el `verifier.py` real del repo.
**Decisión de lenguaje (JF, 22-jul): Python.** La alternativa Go fue evaluada a fondo y
es viable (ver "Alternativa Go" al final — la evidencia se conserva por trazabilidad SDD);
se eligió Python por reuso directo de la lib de licensing y por ser el lenguaje nativo
del equipo. No quedan NEEDS CLARIFICATION.

## D1 — Firma: reusar la lib de licensing existente (cero divergencia por construcción)

**Decisión**: el emisor de la CLI **importa** `canonical_payload_bytes` y el formato de
`token.py` + `verifier.py` (spec 021) — la MISMA lib que corre en las cajas desplegadas.
No existe serialización paralela: el riesgo de que emisor y verificador diverjan
desaparece **por construcción**, no por tests. El build del artefacto CLI (D3) incluye
`backend/src/licensing/` como fuente única; un **contract test del artefacto** garantiza
que lo que el binario empaquetado firma lo valida el backend del producto (mismo código,
pero el test cubre el empaquetado).

**Invariantes que la CLI hereda del wire de la 021** (sin reimplementar):
`json.dumps(payload, sort_keys=True, separators=(",",":"), ensure_ascii=False).encode("utf-8")`,
firma Ed25519 detached en `sig` (base64url **con** padding), keyset PEM con línea
`# key_id: <kid>` antes de cada bloque (verifier.py:57-72), rotación = **agregar** kid.

**Validador pre-firma fail-closed** (sigue siendo necesario — el bug no era solo de
serialización sino de entradas): tenant/seats/expiry por flags validados (ints, ISO 8601
con timezone, expiry futura), rechazo de payload con campos extraños (coherente con el
`schema` estricto del verifier).

**Alternativas rechazadas**: reimplementar el emisor (aunque sea en Python) sin importar
la lib — duplicación innecesaria; JCS/RFC 8785 — cambiaría el wire desplegado.

## D2 — Custodia de la privada: PKCS8 cifrado con la lib `cryptography` (cero deps nuevas)

**Decisión**: la privada Ed25519 vive ÚNICAMENTE como **PEM PKCS8 cifrado** generado con
`private_bytes(..., BestAvailableEncryption(passphrase))` de `cryptography` — la lib que
el proyecto **ya** usa para verificar (cero dependencias nuevas). Escritura con `O_EXCL`
+ `0600` en dir `0700` (jamás truncar/pisar una clave existente — el foot-gun de FR-002).
Passphrase SIEMPRE por prompt sin eco (`getpass`/`click.prompt(hide_input=True)`); **sin
fallback por env en el MVP** (cosign tiene `COSIGN_PASSWORD` para CI; nosotros
explícitamente no). Para firmar: descifrar en memoria, firmar, descartar. Break-glass
documentado: el PEM cifrado es estándar OpenSSL (`openssl pkey -in key.pem`). Migración:
`key import` lee el PEM dev en claro, valida que su pública coincide con el kid del
keyset, escribe el PEM cifrado y borra el claro (best-effort, documentando que en
APFS/SSD el borrado no es forense — la dev ya fue rotada el 20-jul, riesgo bajo; la
clave PROD jamás pasa por un PEM en claro).

**Gotchas**: `O_EXCL` obligatorio (un `open('w')` trunca sin avisar); prompt TTY
detectado y error claro en pipes con camino `--password-stdin` estilo docker login para
automatización consciente; Python no zeroiza strings → riesgo aceptado en máquina de
firma dedicada, anotado sin venderlo como mitigado; recovery = segunda copia cifrada
aparte, nunca la misma passphrase reutilizada.

**Alternativas**: age/rage vía `pyrage` (dep compilada nueva para lo que
BestAvailableEncryption ya da con estándar OpenSSL); SOPS (orientado a YAML de deploy);
keyring del OS (no portable a la máquina de firma dedicada); KMS/HSM = fase 2 (research
021 fijó DIY Ed25519). Patrón de referencia: cosign/minisign (clave cifrada con
passphrase en archivo, de un humano en una máquina).

## D3 — Arquitectura: paquete Python `cli/` + click, distribuido como zipapp `.pyz`

**Decisión**: paquete `cli/basa_admin/` en la raíz del repo (hermano de `backend/`),
framework **click** (maduro, prompts/confirm integrados, `CliRunner` para tests), con la
lib de licensing del backend como fuente única (el build la incluye — sin fork del
código). Distribución: **zipapp single-file (`shiv`) → `basa-admin.pyz`** por plataforma
(linux x86_64/arm64 — las wheels de `cryptography` van adentro), con sha256 en el
MANIFEST del bundle. **Prerrequisito del host: Python 3.11+** (se añade al perfil de
prerrequisitos del partner en la doc 025 — hoy ya exige Docker/shell/SQL; en los Linux
objetivo Python está presente por default). Build y tests corren **en contenedor** (la
imagen backend ya tiene Python + deps — no se exige nada nuevo al equipo). Versión
embebida en el artefacto; `basa-admin --version` la reporta.

**Garantía offline por construcción**: el núcleo no importa `requests`/`httpx`/sockets —
un test del gate lo verifica (grep de imports + suite corrida con la red cortada). Los
comandos [CLOUD] de fase 2 llegan como subárbol separado con su propio gate.

**Gotchas**: los strings de `--help`/errores del `.pyz` viajan en el bundle → aplican los
checks **white-label** (`prohibited_names.txt`); el `.pyz` (ambas arch linux) va DENTRO
del tarball air-gapped — mismo edge case que las imágenes: artefacto fuera del tarball =
install roto sin egress; las wheels de `cryptography` son por-plataforma → un `.pyz` por
arquitectura, nombrado y verificado en el MANIFEST; `shiv` cachea en `~/.shiv` al primer
run → documentar (y fijar `SHIV_ROOT` a un dir del operador para no sorprender en hosts
restringidos).

**Alternativas**: Go (ver al final — viable, descartada por decisión); PyInstaller
(binario más pesado y frágil ante SO viejos; `.pyz` es más simple y auditable); pip
install en el host (host airgap sin índice → no); correr TODO dentro del contenedor
backend (chicken-and-egg: `install load`/`up` corren ANTES de que exista el stack).

## D4 — Integración con el stack: "la CLI orquesta, los entrypoints ejecutan dominio"

**Decisión**: la CLI implementa nativo (en su propio proceso) todo lo que es
archivos/docker (profile scaffold/render con golden-test contra la salida del bash
actual, secrets gen con `secrets`/`os.urandom`, bundle create/verify/load, up + readiness
poll, license verify/issue — la firma es local, D1) y **shellea a entrypoints
`python -m` endurecidos dentro del contenedor backend** para lo que toca modelos
SQLAlchemy con la DB del deployment (seed, admin bootstrap/rotate, génesis) — la CLI del
host no arrastra SQLAlchemy/psycopg ni credenciales de DB; el contenedor ya los tiene.
Los entrypoints nuevos (`backend/src/cli_entrypoints/`) nacen con flags, `--dry-run` y
confirmación — el endurecimiento es parte de esta spec, no un wrapper sobre los scripts
horribles (FR-012).

**Hallazgos que la implementación DEBE resolver** (independientes del lenguaje, todos con
evidencia archivo:línea):

1. **Los 3 volúmenes nombrados de `compose.prod.yml` nadie los puebla en el camino
   compose** (`licenses`, `litellm_config`, `branding` — solo cloud-init los escribe en
   el camino tofu): `install up`/`license install` deben poblarlos o el stack prod
   arranca sin licencia/config/marca.
2. **`docker save` por referencia `@sha256` produce imágenes sin RepoTags** tras
   `docker load` → compose no resuelve y dispara pull (= install roto en airgap):
   `install load` debe **re-taggear desde el MANIFEST**.
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
   api/users.py:35-44): `install admin bootstrap` corre ANTES de exponer el ingress, y
   el orden con la génesis importa (`/health/license` detallado está gated a admin).

## D5 — Ledger local de emisiones y audit-log de la CLI

**Decisión**: ambos como **JSONL append-only** locales (data-model.md). El ledger de
emisiones (lado Basa) da visibilidad humana del cupo por pool con hash-encadenado para
detectar ediciones; **no** pretende el enforcement duro del cupo (eso es el portal, fase
posterior de #33 — coherente con FR-030 de la 021 que ya ubica esa validación fuera de
la caja). El audit-log de la CLI registra comando/args sanitizados/resultado,
metadata-only, exportable como archivo — trazabilidad sin egress (FR-013).

**Alternativa rechazada**: SQLite local — estado opaco para un humano y otra superficie
de tooling, para un problema que JSONL + hash chain resuelve legible; el estado
autoritativo de seats vive en el true-up de cada caja (021), no acá.

## Alternativa Go — evaluada, viable, descartada (registro por trazabilidad)

La opción Go (binario estático sin runtime en el host) se investigó a fondo y quedó
**verificada empíricamente**: con Go ≥ 1.22, `json.Encoder` + `SetEscapeHTML(false)` +
recorte del `\n` final sobre `map[string]any` produce bytes canónicos **idénticos** a
`canonical_payload_bytes`, y la firma Ed25519 de `crypto/ed25519` es byte-idéntica a la
de PyCA (probado en contenedores golang 1.21/1.22/1.24 contra la imagen real del backend:
`verify_license_blob` aceptó licencias firmadas en Go, PEMs interoperables en ambas
direcciones). Los gotchas mapeados (HTML escaping, U+2028/29, `\b\f` pre-1.22, floats,
structs por orden de declaración) exigían un validador fail-closed y golden vectors
cross-lenguaje como blindaje permanente. **Por qué se descarta**: Python reusa la lib de
licensing como fuente única (la clase entera de riesgo desaparece por construcción, no
por tests), no introduce un segundo lenguaje al repo, y el costo (Python 3.11+ como
prerrequisito del host) es aceptable para el perfil de partner ya documentado. Si algún
día el prerrequisito Python resulta un problema real en el campo, esta evidencia deja el
camino Go listo para retomarse.

## Fuera de alcance (confirmado)

- Portal de emisión con enforcement de cupo (forma completa del #33): fase posterior.
- Los 3 fixes out-of-repo (#35): se cierran como PR del producto (ruta 020), no como
  comandos CLI.
- Comandos [CLOUD] (`release publish`, `cloud apply`) y `ops` día-2: fase 2 (contrato
  preliminar en contracts/).
- KMS/HSM para la privada: fase 2; el MVP es PKCS8 cifrado en máquina de firma dedicada.
