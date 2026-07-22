# Data Model — 026 CLI de operador (`basa-admin`)

La CLI **no introduce esquema nuevo en la base del producto**: opera sobre artefactos
de archivo y sobre entidades ya definidas por 013/020/021. Este doc fija los artefactos
que la CLI produce/consume y las dos estructuras locales nuevas (ledger de emisiones y
audit-log local), ambas **archivos**, nunca tablas del producto.

## Artefactos existentes (contratos ajenos, la CLI los respeta)

### Licencia `.lic` (definida en 021 — `backend/src/licensing/token.py`)

JSON con firma Ed25519 detached:

- Campos obligatorios (`REQUIRED_FIELDS`): `schema` (=1), `lic_id`, `kid`, `tenant_id`,
  `distributor_id`, `pool_id`, `max_seats` (int ≥ 0), `not_before`, `expiry` (ISO 8601
  con timezone), `grace_days` (int ≥ 0), `feature_flags` (lista). Opcional: `issued_at`.
- Firma: campo `sig` = base64url de la firma Ed25519 sobre los **bytes canónicos** del
  payload SIN `sig`: `json.dumps(payload, sort_keys=True, separators=(",",":"),
  ensure_ascii=False).encode("utf-8")`.
- **Invariante de la CLI**: el emisor Go DEBE producir bytes canónicos **idénticos** a
  los de Python (contrato cross-lenguaje con golden vectors — ver research.md D1).

### Keyset público (`basa_public_keys.pem` — `backend/src/licensing/verifier.py`)

Bloques PEM `PUBLIC KEY` (SubjectPublicKeyInfo, Ed25519), cada uno precedido por un
comentario `# key_id: <kid>`. Soporta N claves (rotación sin romper cajas viejas).
**Invariantes de la CLI**: (a) rotar = **AGREGAR** un bloque nuevo, nunca reemplazar el
archivo (el foot-gun histórico); (b) exportar nunca incluye material privado.

### Perfil de cliente (definido en 020 — `deploy/clients/<slug>/`)

Layout: `client.env` (con `TENANT_SLUG` == nombre del directorio), `branding.env`,
`config.yaml.tmpl`. Render → `rendered/` (config.yaml + brand.json + instance.env).
La CLI valida el layout y las variables del template antes de renderizar.

### Bundle air-gapped (definido en 020 — `deploy/release/bundle.sh`)

Tarball con las **7 imágenes** (`docker save`) + perfil renderizado + `MANIFEST` con
digests. **Invariante de la CLI**: `bundle verify` comprueba que TODAS las imágenes del
manifiesto están presentes y sus digests coinciden **antes** de transferir/cargar.

### Entidades del producto tocadas vía seed/bootstrap (013/021)

`Tenant`, `Client`/`User`, `Connection`/`APIKey`, licencia instalada
(`BASA_LICENSE_TOKEN[_FILE]`), génesis de la cadena de audit. La CLI **no** las accede
por SQL propio: orquesta los entrypoints del backend (ver plan.md, decisión de
integración) que ya encapsulan modelos y validaciones.

## Estructuras nuevas (locales de la CLI, archivos)

### Clave privada de firma cifrada (lado Basa)

- **Qué**: la privada Ed25519 del emisor, **cifrada en reposo** (passphrase; formato según
  research.md D2), permisos `600`.
- **Ciclo**: se crea con la primera emisión o con `keyset rotate`; nunca existe en claro en
  disco; la passphrase se pide por prompt (jamás flag/env).
- **Relación**: 1 privada activa ↔ 1 `kid` en el keyset público; las viejas se conservan
  cifradas para auditoría, no para firmar.

### Ledger local de emisiones (lado Basa)

- **Qué**: registro append-only (JSONL) de cada `.lic` emitido: `{lic_id, tenant_id,
  distributor_id, pool_id, max_seats, expiry, kid, emitido_at, archivo_out}`.
- **Para qué**: visibilidad humana del cupo consumido por pool ("cuánto le queda a
  Cámara") **sin** pretender enforcement duro — el enforcement del cupo es del portal
  (fase posterior de #33). Una re-emisión para el mismo `tenant_id` se registra como
  supersede (consistente con FR-030 de la 021).
- **Integridad**: hash-encadenado (cada entrada referencia el hash de la anterior) para
  detectar ediciones manuales; verificable offline.

### Audit-log local de la CLI (ambos lados)

- **Qué**: JSONL append-only por máquina: `{ts, comando, args_sanitizados, resultado,
  operador}` — **sin secretos ni payloads sensibles** (mismo estándar metadata-only del
  producto).
- **Para qué**: FR-013 — trazabilidad de qué se emitió/instaló/rotó sin egress;
  exportable como archivo junto al true-up.

## Estados y transiciones relevantes

- **Keyset**: `sin claves` → `1 kid activo` → (rotación explícita) → `N kids` (todas
  válidas para verificar; solo la última firma). Nunca hay transición que ELIMINE un kid
  con licencias vivas — la CLI lo bloquea salvo `--force` con confirmación doble.
- **Instalación** (secuencia de US2): `perfil` → `secretos` → `bundle verificado` →
  `stack up` → `seed aplicado` → `licencia instalada + génesis` → `admin bootstrapeado`
  → `verificado`. Cada paso valida sus precondiciones; la CLI puede retomar desde el
  último paso completado (idempotencia por paso, no transaccionalidad global).
