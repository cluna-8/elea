# Data Model — 026 CLI de operador (`sentinel-admin` + `sentinel-admin-signer`)

Ninguno de los dos artefactos **introduce esquema nuevo en la base del producto**: operan
sobre artefactos de archivo y sobre entidades ya definidas por 013/020/021. Este doc fija
los artefactos que cada artefacto produce/consume y las dos estructuras locales nuevas
(ledger de emisiones — exclusivo de `sentinel-admin-signer` — y audit-log local — uno por
artefacto/máquina), todas **archivos**, nunca tablas del producto. La separación de qué
artefacto toca cada entidad es la misma fijada en spec.md § Clarifications (2026-08-05) y
research.md D6.

## Artefactos existentes (contratos ajenos, la CLI los respeta)

### Licencia `.lic` (definida en 021 — `backend/src/licensing/token.py`)

JSON con firma Ed25519 detached:

- Campos obligatorios (`REQUIRED_FIELDS`): `schema` (=1), `lic_id`, `kid`, `tenant_id`,
  `distributor_id`, `pool_id`, `max_seats` (int ≥ 0), `not_before`, `expiry` (ISO 8601
  con timezone), `grace_days` (int ≥ 0), `feature_flags` (lista). Opcional: `issued_at`.
- Firma: campo `sig` = base64url de la firma Ed25519 sobre los **bytes canónicos** del
  payload SIN `sig`: `json.dumps(payload, sort_keys=True, separators=(",",":"),
  ensure_ascii=False).encode("utf-8")`.
- **Invariante**: el emisor (`sentinel-admin-signer`) **importa** `canonical_payload_bytes` de
  la lib de licensing (fuente única — cero serialización paralela); el contract test del
  artefacto `.pyz` cubre que el empaquetado no rompa ese reuso (research.md D1). La
  verificación (`verifier.py`) es pública y no toca la privada del emisor, por eso
  `sentinel-admin` también puede importarla para `license verify` (research.md D6).

### Keyset público (`sentinel_public_keys.pem` — `backend/src/licensing/verifier.py`)

Bloques PEM `PUBLIC KEY` (SubjectPublicKeyInfo, Ed25519), cada uno precedido por un
comentario `# key_id: <kid>`. Soporta N claves (rotación sin romper cajas viejas).
**Invariantes** (ambos exclusivos de `sentinel-admin-signer` — es el único que rota/exporta):
(a) rotar = **AGREGAR** un bloque nuevo, nunca reemplazar el archivo (el foot-gun
histórico); (b) exportar nunca incluye material privado. `sentinel-admin` solo **consume**
el keyset ya exportado (archivo de entrada para `license verify`), nunca lo genera.

### Perfil de cliente (definido en 020 — `deploy/clients/<slug>/`)

Layout: `client.env` (con `TENANT_SLUG` == nombre del directorio), `branding.env`,
`config.yaml.tmpl`. Render → `rendered/` (config.yaml + brand.json + instance.env).
`sentinel-admin` valida el layout y las variables del template antes de renderizar.

### Bundle air-gapped (definido en 020 — `deploy/release/bundle.sh`)

Tarball con las **7 imágenes** (`docker save`) + perfil renderizado + `MANIFEST` con
digests **+ el `.pyz` de `sentinel-admin` por arquitectura** (FR-021/FR-022 — nunca el de
`sentinel-admin-signer`). **Invariante**: `sentinel-admin bundle verify` comprueba que TODAS las
imágenes del manifiesto están presentes y sus digests coinciden **antes** de
transferir/cargar.

### Entidades del producto tocadas vía seed/bootstrap (013/021)

`Tenant`, `Client`/`User`, `Connection`/`APIKey`, licencia instalada
(`SENTINEL_LICENSE_TOKEN[_FILE]`), génesis de la cadena de audit. `sentinel-admin` **no** las
accede por SQL propio: orquesta los entrypoints del backend (ver plan.md, decisión de
integración D4) que ya encapsulan modelos y validaciones.

## Estructuras nuevas (locales, archivos)

### Clave privada de firma cifrada (exclusiva de `sentinel-admin-signer`)

- **Qué**: la privada Ed25519 del emisor, **cifrada en reposo** como PEM PKCS8 con
  passphrase (`BestAvailableEncryption` de `cryptography` — estándar OpenSSL, break-glass
  con `openssl pkey`; research.md D2), permisos `600`, escrita con `O_EXCL`. Vive
  únicamente en la estación de firma de Sentinel; `sentinel-admin` no la genera, no la custodia y
  no puede importarla (research.md D6, FR-017/FR-018).
- **Ciclo**: se crea con la primera emisión o con `keyset rotate`; nunca existe en claro en
  disco; la passphrase se pide por prompt (jamás flag/env).
- **Relación**: 1 privada activa ↔ 1 `kid` en el keyset público; las viejas se conservan
  cifradas para auditoría, no para firmar.

### Ledger local de emisiones (exclusivo de `sentinel-admin-signer`)

- **Qué**: registro append-only (JSONL) de cada `.lic` emitido: `{lic_id, tenant_id,
  distributor_id, pool_id, max_seats, expiry, kid, emitido_at, archivo_out}`.
- **Para qué**: visibilidad humana del cupo consumido por pool ("cuánto le queda a
  Cámara") **sin** pretender enforcement duro — el enforcement del cupo es del portal
  (fase posterior de #33). Una re-emisión para el mismo `tenant_id` se registra como
  supersede (consistente con FR-030 de la 021).
- **Integridad**: hash-encadenado (cada entrada referencia el hash de la anterior) para
  detectar ediciones manuales; verificable offline.

### Audit-log local (ambos artefactos, un archivo por máquina — no compartido)

- **Qué**: JSONL append-only por máquina: `{ts, comando, args_sanitizados, resultado,
  operador}` — **sin secretos ni payloads sensibles** (mismo estándar metadata-only del
  producto). `sentinel-admin-signer` escribe el suyo en la estación de firma; `sentinel-admin`
  escribe el suyo en el host del cliente. No hay un log compartido entre artefactos (eso
  rompería el air-gap).
- **Para qué**: FR-013 — trazabilidad de qué se emitió (signer) o instaló/rotó (admin)
  sin egress; exportable como archivo junto al true-up.

## Estados y transiciones relevantes

- **Keyset**: `sin claves` → `1 kid activo` → (rotación explícita) → `N kids` (todas
  válidas para verificar; solo la última firma). Nunca hay transición que ELIMINE un kid
  con licencias vivas — `sentinel-admin-signer` lo bloquea salvo `--force` con confirmación
  doble. (Sigue ABIERTA la validación cross-fleet de que TODAS las cajas desplegadas
  siguen verificando antes de un retiro — ver inventario-scripts.md.)
- **Instalación** (secuencia de US2): `perfil` → `secretos` → `bundle verificado` →
  `stack up` → `seed aplicado` → `licencia instalada + génesis` → `admin bootstrapeado`
  → `verificado`. Cada paso valida sus precondiciones; `sentinel-admin` puede retomar desde el
  último paso completado (idempotencia por paso, no transaccionalidad global).
