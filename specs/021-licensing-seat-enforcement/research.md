# Research T004 (Phase 0) — Build-vs-Buy del enforcement de licencias offline (distribuidor)

**Fecha**: 2026-07-13 · **Feature**: 021-licensing-seat-enforcement · **Método**: evaluación de
plataformas de licenciamiento/billing contra las **dos restricciones duras y arquitectónicas** del
modelo distribuidor de esta spec — (1) **air-gapped / sin phone-home** (on-prem/VPN puede no tener
egress) y (2) **el cliente corre la caja** (Basa no controla el runtime) — más el hecho de que la
**unidad de seat** (`Connection activa por Tenant`) ya vive en **NUESTRO Postgres** (bedrock 013).

> **Pregunta de investigación**: ¿existe un "LiteLLM de licencias" —una plataforma que reusemos como
> reusamos el motor de inferencia— o el enforcement es código propio? · **Hipótesis a validar**: DIY
> con tokens firmados **Ed25519**, verificados 100% offline con clave pública embebida.

---

## VEREDICTO — **DIY con tokens firmados Ed25519, verificados 100% offline** (hipótesis VALIDADA)

**No hay un "LiteLLM de licencias" que aplique, y la razón es ARQUITECTÓNICA, no de madurez de producto.**
Las dos restricciones del modelo —**air-gapped** + **el cliente corre la caja**— **descartan de raíz todo
SaaS de licenciamiento/billing**:

- **Billing ≠ enforcement.** Stripe/Paddle/LemonSqueezy resuelven **cobro y suscripción**, no *enforcement
  local*. Su modelo de "verificar licencia" es una **llamada HTTP a su API** (p.ej. la License API de
  LemonSqueezy valida por red) → **muere en una caja sin egress**. Sirven para facturarle al distribuidor,
  jamás para decidir, dentro de la caja del cliente, si se puede crear el seat N+1.
- **Los "on-prem license server" son control teatral.** Cryptolens y LicenseSpring ofrecen modos
  "air-gapped / offline activation", pero cuando el **servidor de licencias corre en la infra del
  cliente**, la **autoridad de decisión se mudó a la caja del cliente**. Eso es exactamente lo que ya
  tenemos con un token firmado + verificación local; añadir su servidor sólo agrega una pieza más que el
  cliente puede parchear, sin ganar ninguna garantía criptográfica adicional.
- **Keygen es el único serio que respeta el air-gap** (self-hostable, *cryptographic license files*
  verificables 100% offline con Ed25519). **PERO** su parte útil para nosotros = **"firmar un blob y
  verificar la firma"** = **~40 líneas con PyNaCl**. Todo lo demás que Keygen aporta —activación de
  máquinas, *floating/lease*, distribución, portal de emisión— asume una **topología que no usamos**,
  porque nuestro **conteo de seats (`COUNT(Connection activa)` por Tenant) ya vive en NUESTRO Postgres**
  (013), no en un registro de dispositivos externo. Adoptar Keygen sería importar una plataforma entera
  para usar su 5%.

**Conclusión**: el "buy" no compra nada que no tengamos, y **carga** con un servicio/servidor extra que
contradice el air-gap o duplica estado que ya poseemos. El **build** es una librería de verificación
minúscula sobre criptografía estándar y auditada. **Se construye.**

---

## Tabla comparativa (build-vs-buy)

| Opción | Categoría | ¿Air-gapped real (0 red)? | ¿Autoridad fuera de la caja del cliente? | Seat-count = nuestro Postgres | Superficie que aporta | Veredicto |
|---|---|---|---|---|---|---|
| **DIY Ed25519 (PyNaCl / PyCA `cryptography`)** | Build | **Sí** — verificación local con clave pública embebida | N/A (no hay servidor; la firma es la autoridad, offline) | **Sí, nativo** — el gate cuenta en NUESTRA DB | ~40 LOC (firmar/verificar) + gates propios | **ELEGIDA** |
| **Keygen (self-hosted, offline license files)** | Buy (OSS/self-host) | Sí (cryptographic files offline) | Parcial — self-host en infra del cliente | No — asume su registry de máquinas/activaciones | Activación, floating, distribución, portal (no los usamos) | Rechazada: usamos su 5%, cargamos su 100% |
| **Cryptolens (offline activation)** | Buy (SaaS + on-prem) | Modo offline sí; core es SaaS | On-prem mueve autoridad a la caja del cliente = teatral | No | License server + activación | Rechazada: control teatral, pieza extra parcheable |
| **LicenseSpring (air-gapped portal)** | Buy (SaaS + on-prem) | Modo air-gapped documentado | Igual que Cryptolens | No | License manager + air-gapped portal | Rechazada: misma razón + dependencia comercial |
| **LemonSqueezy / Paddle / Stripe (License/Billing API)** | Buy (SaaS billing) | **No** — validación por HTTP a su API | Autoridad remota (SaaS) | No | Cobro/suscripción (útil para facturar al distribuidor) | Rechazada para enforcement: muere sin egress. Billing ≠ enforcement |

---

## Recomendación

**Construir** un verificador de licencia propio, backend-only, con estas decisiones cerradas:

- **Firma**: **Ed25519** (curva de firma rápida, claves/firmas cortas, sin parámetros que elegir mal).
- **Librería (verificación en la caja del cliente)**: **PyNaCl** *o* **`cryptography` (PyCA)** — ambas
  exponen Ed25519 con binding a libsodium/OpenSSL, auditadas y mantenidas. PyNaCl es la más directa para
  "verificar un blob"; PyCA conviene si el backend ya la trae por otras razones. **Sólo verificación** con
  la **clave pública embebida**; el firmante nunca vive en la caja.
- **Formato del token** — **decisión: JSON firmado (detached) propio**, no JWT, por defecto:
  - Un `.lic` = **JSON canónico** + firma Ed25519 detached (base64). Control total del schema, cero
    dependencia de una capa JOSE, verificación trivial.
  - **Alternativa si se prefiere JWT**: **PyJWT con `alg="EdDSA"`** (EdDSA = Ed25519 en JOSE). **Preferir
    PyJWT sobre `python-jose`** (semi-abandonado, con CVEs históricas y menor mantenimiento). El `kid` del
    header JOSE mapea 1:1 a nuestra rotación de claves.
- **Custodia de claves (lado Basa/distribuidor, offline)**: la **clave privada** vive en **KMS/HSM** de
  Basa; en la caja del cliente se embebe **sólo la pública**. **Rotación** vía **`kid` multi-clave**: el
  producto embebe un *set* de públicas indexadas por `kid` y el token trae su `kid` → una rotación no
  rompe cajas ya desplegadas (se soportan N claves durante la migración).
- **Definición de seat [D-021]**: **`COUNT(APIKey activas)` por Tenant** como default (misma definición
  de "activa" que el índice parcial `uq_api_keys_tenant_user_tool`), alternativa `COUNT(User role=client)`.
  Se usa **una** definición, idéntica en el gate (US2) y en la reconciliación (US3).

---

## Riesgos + mitigaciones

| Riesgo | Origen | Mitigación |
|---|---|---|
| **Patch de código del binario** (el cliente corre la caja → podría parchear el verificador o embeber otra clave pública). | **Residual inherente a on-prem**: ningún esquema offline es criptográficamente inviolable end-to-end cuando el adversario controla el runtime. | **True-up vía audit log inmutable** (US5): cada estado (over-seat/expired/token inválido) queda como **evidencia append-only** = **incumplimiento contractual detectable**. No se promete inviolabilidad; se promete **innegabilidad** para el contrato. |
| **Reloj atrasado** para evadir `expiry`. | El expiry se evalúa con reloj **local** (offline, por diseño). | **Timestamp monótono guardado** (último ts de licencia/audit visto); si `now < marca` → `license_clock_rollback_suspected` + degradado + audit. Best-effort, explícito. |
| **Replay de un token legítimo de otro deployment.** | Un `.lic` válido copiado a otra caja. | **Atar a `tenant_id` fail-closed**: `token.tenant_id` debe coincidir con el `tenant_id` del deployment (013/020); si no, `mismatch` y no se carga el entitlement. |
| **Custodia / fuga de la clave de firma.** | Compromiso de la privada = licencias falsificables. | Privada en **KMS/HSM** (nunca en la caja); rotación por **`kid`**: revocar la comprometida y firmar con una nueva sin re-desplegar cajas que ya traen la pública nueva en el set. |
| **Confundir billing con enforcement** (tentación de "usar la License API de X"). | Presión de reusar un SaaS de cobro. | Regla dura documentada: **billing (Stripe/Paddle/LemonSqueezy) factura al distribuidor; el enforcement es local**. Ninguna decisión de seat depende de una llamada de red. |

---

## Esbozo del artefacto `.lic` (JSON firmado Ed25519)

Payload **JSON canónico** + firma Ed25519 detached. Nombres wire compactos; mapeo a los nombres
conceptuales de la spec entre paréntesis.

```jsonc
{
  "schema": 1,                       // versión del formato del artefacto (permite evolucionar sin romper)
  "lic_id": "lic_7f3a…",             // license_id — id único de la licencia (para audit/soporte)
  "kid": "basa-2026-a",              // key_id — selecciona la clave pública embebida (rotación)
  "tenant_id": "t_acme",             // ámbito: la licencia se escopea POR tenant (anti-replay)
  "max_seats": 25,                   // tope de asientos = COUNT(Connection activa) por tenant
  "feature_flags": ["monitor"],      // módulos white-label on/off; flag ausente = OFF (fail-closed)
  "not_before": "2026-07-01T00:00:00Z", // inicio de validez (≈ issued_at si se omite)
  "expiry":     "2027-07-01T00:00:00Z", // fin de validez
  "grace_days": 14                   // ventana de gracia tras expiry (bloquea creación, no el tráfico)
}
```

**Firma**: `sig = Ed25519(privkey_basa, canonical_json(payload))`, adjuntada como campo detached
(base64). El producto embebe **sólo** la(s) pública(s) en `BasaPublicKeySet`, indexada(s) por `kid`.
**Nunca** se persiste el token crudo ni ninguna clave en el audit (metadata-only, Constraint C1).

### Verificación en **2 gates fail-closed**

1. **Gate de arranque (lifespan del backend)**: al arrancar, leer el `.lic` (inyectado como config por la
   **020**), seleccionar la pública por `kid`, **verificar la firma Ed25519 offline**, validar
   `tenant_id` == deployment y `not_before ≤ now ≤ expiry (+ grace)`, y cargar el **entitlement en
   memoria**. Firma inválida / ausente / `mismatch` / expirado más allá del grace → **modo degradado
   fail-closed** (no crea seats) + audit. **0 llamadas de red.**
2. **Gate de creación (`POST` de Connection/Client)**: antes de provisionar en el motor
   (`ai_engine_client.generate_key`), contar seats activos del tenant y **rechazar 402/403**
   `license_seat_limit_exceeded` si `COUNT(activas) ≥ max_seats`. Si el entitlement no está cargado o es
   inválido → **bloqueo fail-closed** (nunca "sin token = ilimitado").

La **reconciliación periódica local** (US3) es la red de seguridad detrás de los dos gates: re-cuenta
`COUNT(activas)` vs `max_seats` por tenant y marca `over_seat` ante drift (backup/DB directa), sin
phone-home.

---

## Fuentes (URL)

- Keygen — self-hosting (air-gap real, self-hostable): `https://keygen.sh/docs/self-hosting/`
- Keygen — offline/cryptographic licenses: `https://keygen.sh/docs/choosing-a-licensing-model/offline-licenses/`
- PyNaCl — signing/verify (Ed25519): `https://pynacl.readthedocs.io/`
- Cryptolens — offline verification (on-prem = autoridad en la caja del cliente): `https://help.cryptolens.io/examples/offline-verification`
- LicenseSpring — air-gapped portal: `https://docs.licensespring.com/portals/air-gapped`

> Nota de método: las fuentes se usaron para **confirmar la propiedad arquitectónica** (quién puede
> operar sin egress y dónde vive la autoridad de decisión), no como guía de implementación — el
> verificador propio se especifica arriba y se blinda con los unit/contract tests de `tasks.md`
> (T006/T037).
