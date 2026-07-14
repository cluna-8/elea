# Implementation Plan: Licensing & Seat Enforcement (offline, distributor model)

**Branch**: `021-licensing-seat-enforcement` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/021-licensing-seat-enforcement/spec.md`

## Summary

Construir el **enforcement de licencias OFFLINE** para el modelo comercial "install + X licencias"
vendido a un **distribuidor marca-blanca**, donde **el cliente corre el software** (Basa no controla la
caja) y la caja **puede no tener egress** (on-prem/VPN). Como consecuencia, el enforcement **NO puede
hacer phone-home**: se basa en un **artefacto de licencia firmado Ed25519**, verificado **localmente** al
arranque y en la creación de seats, con **evidencia de tamper** en el audit inmutable ya existente.

Es una feature **greenfield en su núcleo** (hoy: cero `max_seats`/`license_key`/`entitlement`), pero
engancha en **plomería sólida**:

1. **Unidad de seat = la Connection (`APIKey`)**, con `≤1 Connection activa por herramienta por cliente`
   ya garantizado (índice parcial `uq_api_keys_tenant_user_tool` + pre-check 409). "X licencias" =
   "X Connections activas" (o "X Clients `role=client`") **por Tenant**.
2. **Punto de enganche del gate = la CREACIÓN**: los `POST` del backend (`keys.py`/`users.py`), justo
   **antes** del provisioning al motor (`ai_engine_client.generate_key`), más una **reconciliación**
   periódica local que detecta drift.
3. **Identidad ya fail-closed**: `custom_auth.py` resuelve por `key_hash=sha256`; esta spec **extiende**
   esa postura fail-closed al gate de licencia.

El enfoque técnico central: **licencia como config firmada** (Principio VII — no fork, no binario custom;
el mismo producto opera para cualquier cliente cambiando sólo el token inyectado por la 020), **tope por
tenant** (Principio III), y **evidencia auditable de tamper** (Principio II — el audit inmutable como
prueba innegable, ya que el enforcement offline es *detectable* no *inviolable*).

## Technical Context

**Language/Version**: Python 3.11 (backend FastAPI heredado; el gate y la verificación viven en el
backend, NO en el motor LiteLLM).

**Primary Dependencies**: una librería de criptografía para **Ed25519** (verificación de firma;
**`PyNaCl` o `cryptography`/PyCA**, o **PyJWT con `alg=EdDSA`** si se prefiere JWT — evitar `python-jose`,
semi-abandonado; veredicto build-vs-buy y elección en [`research.md`](./research.md)) — **sólo
verificación** con clave pública embebida, el firmante es offline; SQLAlchemy sobre los modelos
`APIKey`/`User`/`Tenant`/`AuditLog` de la 013; el scheduler existente del backend para la reconciliación
periódica.

**Storage**: PostgreSQL (modelos `APIKey`/`User`/`Tenant`/`AuditLog` de la 013, **sin schema nuevo
propio** salvo, si hace falta, una tabla/registro para el **estado de licencia** y la **marca monotónica**
anti-rollback). El entitlement verificado vive **en memoria**; el token crudo NUNCA en DB.

**Testing**: pytest — unit tests de verificación de firma (válida/alterada/mismatch/rotación de clave) y
de conteo de seats (activas vs revocadas); integration tests del gate en `POST keys.py`/`users.py`
(402/403 antes de provisionar) y de la reconciliación (drift → over-seat); tests de ciclo de vida
(active→grace→expired) con reloj inyectado; test **offline** con egress bloqueado; test negativo de
inmutabilidad/metadata-only del audit.

**Target Platform**: Linux server en containers (Docker Compose, Principio VII). **Caja del cliente,
posiblemente sin egress** — el diseño asume ausencia de red saliente.

**Project Type**: web-service (backend FastAPI). El enforcement es **backend-only**; el motor LiteLLM no
participa en el conteo de seats (es gobernanza de uso, no de asientos).

**Performance Goals**: la verificación de firma corre una vez al arranque (y opcionalmente al recargar el
token); el gate añade **un COUNT indexado por tenant** por creación (barato, no en el hot-path de
inferencia); la reconciliación es un job periódico fuera del camino de request.

**Constraints**: **offline / no phone-home** (constraint dura del modelo distribuidor); **fail-closed**
(sin token válido → no se crean seats; extiende Constraint C3); clave **privada NUNCA** en la caja
(sólo pública embebida, Constraint C5); audit **metadata-only + inmutable** (Constraint C1); anti-rollback
best-effort con marca monotónica.

**Scale/Scope**: módulos nuevos = verificador de licencia + entitlement en memoria + gate en 2 call-sites
+ job de reconciliación + eventos de audit de licencia + endpoint de health. Sin schema nuevo del dominio
(todo viene de 013); a lo sumo una tabla/registro pequeño para estado+marca monotónica.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio / Constraint | Cómo lo cumple esta feature | Veredicto |
|---|---|---|
| **VII. Containerized & White-Label (config+seed, never fork)** | La licencia es **config firmada** inyectada por la 020; el mismo binario/imagen opera para cualquier cliente cambiando sólo el token (y `key_id`). 0 forks / builds custom por cliente. Rotación de clave por `key_id`. | PASS by-design |
| **III. Multi-Tenant** | El entitlement se escopea **por Tenant**; el conteo de seats y el estado de licencia se evalúan **aislados** por tenant; el over-seat/expired de uno no afecta a otro. | PASS by-design |
| **II. Compliance FIRST (audit inmutable como evidencia)** | Cada transición de licencia (incl. tamper y rollback de reloj) se registra en el **audit inmutable existente**, append-only y metadata-only → evidencia innegable para el contrato. | PASS by-design |
| **Constraint C1 No Raw PII/Secret Storage** | El audit de licencia es metadata-only; NUNCA persiste el token crudo ni claves. | PASS by-design |
| **Constraint C3 Fail-closed** | Sin token válido / entitlement inválido → NO se crean seats (no "sin token = ilimitado"); extiende el fail-closed de `custom_auth`. | PASS by-design |
| **Constraint C5 Credenciales fuera de config en claro** | Sólo la clave **pública** se embebe (no es secreto); la privada vive offline del lado de Basa; el token se inyecta como secret/env (020), no hardcodeado. | PASS by-design |
| **Dev Workflow — Reuse over Reinvent** | Reusa `APIKey`/`User`/`Tenant`/`AuditLog` (013), el pre-check/índice de seat, el call-site de creación y el scheduler existentes; sólo el verificador + gate + reconciliación son nuevos. | PASS by-design |

**Sin violaciones de principio que justificar** (ver Complexity Tracking): esta spec **refuerza**
principios (VII/III/II) en vez de pedir excepciones. La única tensión honesta —enforcement offline no es
criptográficamente inviolable— NO es una violación de principio: es una **propiedad del modelo
distribuidor**, mitigada con fail-closed + evidencia auditable (documentada en Assumptions y Riesgos).

## Mapeo modelo comercial → mecanismo técnico

Traducción del modelo "install + X licencias" (distribuidor) a los puntos técnicos. Columna "Dueño" =
REUSA-plomería vs PROPIO (nuevo).

| Modelo comercial / concepto | Mecanismo técnico | Dueño |
|---|---|---|
| "X licencias" compradas por el cliente final | `max_seats` en el token firmado, escopeado por `tenant_id` | PROPIO (token) |
| "Un asiento" | 1 Connection activa (`APIKey`), `≤1 por herramienta por cliente` | REUSA plomería (013) |
| Unicidad de asiento por herramienta | índice parcial `uq_api_keys_tenant_user_tool` + pre-check 409 | REUSA plomería (013) |
| "El cliente corre la caja, sin egress" | verificación Ed25519 **local** al arranque, 0 red | PROPIO (verificador offline) |
| Emisión de licencia (venta) | firma Ed25519 **offline** del lado Basa/distribuidor (fuera de scope aquí) | Externo (sólo se define formato + clave pública) |
| "No dejar crear más asientos de los pagados" | gate en `POST keys.py`/`users.py`: `COUNT(activas) ≥ max_seats` → 402/403 antes de `generate_key` | PROPIO (gate) sobre call-site REUSADO |
| Detección de trampa/backup/DB directa | reconciliación periódica local `COUNT(activas)` vs `max_seats` | PROPIO (job) sobre scheduler REUSADO |
| Vencimiento de la licencia | `expiry` + `grace_days` en el token; estado `active/grace/expired` con reloj local | PROPIO (ciclo de vida) |
| Aterrizaje suave al vencer | modo degradado **read-only-para-creación** (default), toggle a bloqueo total | PROPIO (política) |
| "Prueba de que el cliente hizo trampa" | eventos de licencia en el **AuditLog inmutable** existente (metadata-only) | PROPIO (eventos) sobre audit REUSADO |
| Anti-rollback de reloj | marca monotónica (último ts visto); `now < marca` → sospecha + degradado | PROPIO (best-effort) |
| Módulos white-label on/off | `feature_flags` del token (ausente = off, fail-closed) | PROPIO (flags) |
| Rotación de claves de Basa | conjunto de claves públicas embebidas indexadas por `key_id` | PROPIO (rotación) |
| Uso por seat (rpm/tpm/budget, 007) | **NO** es conteo de seats — gobernanza ortogonal, no se toca | REUSA 007 (ortogonal) |

## Project Structure

### Documentation (this feature)

```text
specs/021-licensing-seat-enforcement/
├── plan.md              # This file
├── spec.md              # Feature spec (user stories, FR, SC)
├── tasks.md             # Task list (por user story)
├── research.md          # Phase 0 (GENERADO): veredicto DIY Ed25519, lib (PyNaCl/PyCA/PyJWT-EdDSA), formato .lic, política de seat [D-021], anti-rollback
├── data-model.md        # Phase 1 (a generar): consume 013 (APIKey/User/Tenant/AuditLog); define estado de licencia + marca monotónica
├── quickstart.md        # Phase 1 (a generar): emitir token de prueba (offline) → inyectar en 020 → arrancar sin egress → ver /health
└── contracts/           # Phase 1 (a generar): formato del token firmado + esquema del evento de audit de licencia
```

### Source Code (repository root)

```text
backend/src/
├── licensing/                             # NUEVO: núcleo de licenciamiento (backend-only)
│   ├── token.py                           # PROPIO: parse + esquema del LicenseToken (payload + firma + key_id)
│   ├── verifier.py                        # PROPIO: verificación Ed25519 OFFLINE contra BasaPublicKeySet (por key_id)
│   ├── entitlement.py                     # PROPIO: entitlement en memoria + cómputo de estado (active/grace/expired/invalid/over_seat)
│   ├── seat_counter.py                    # PROPIO: COUNT(APIKey activas) | COUNT(User role=client) por tenant (una definición, [D-021])
│   ├── reconcile.py                       # PROPIO: job periódico de reconciliación (drift → over_seat)
│   └── audit_events.py                    # PROPIO: emisión de transiciones de licencia al AuditLog inmutable (metadata-only)
├── api/
│   ├── keys.py                            # MODIFICADO: + gate de seats en POST (402/403 antes de generate_key)
│   ├── users.py                           # MODIFICADO: + gate de seats en POST de Client (role=client)
│   └── health.py                          # MODIFICADO/NUEVO: endpoint de estado de licencia (metadata-only)
├── keys/                                  # config del producto (embebida en la imagen)
│   └── basa_public_keys.pem               # NUEVO: clave(s) PÚBLICA(s) Ed25519 por key_id (sólo pública)
├── services/                              # REUSADOS: ai_engine_client (provisioning), audit
└── models/                                # REUSADOS de la 013: APIKey (=Connection), User, Tenant, AuditLog
                                           #   + (si hace falta) LicenseState/monotonic mark (tabla pequeña)

deploy/ (020)                              # la 020 inyecta el token como secret/env/fichero montado (no en config en claro)

tests/
├── unit/                                  # verificación de firma (ok/alterada/mismatch/rotación); conteo de seats
├── integration/                           # gate en keys/users (402/403 pre-provision); reconciliación; ciclo de vida; offline
└── contract/                              # formato del token + esquema del evento de audit de licencia
```

**Structure Decision**: web-service, **enforcement backend-only** (Principio VII). El motor LiteLLM
**no** participa (evita confundir gobernanza de uso con conteo de asientos). El núcleo de licenciamiento
vive aislado en `backend/src/licensing/` para no contaminar los call-sites; los call-sites de creación
(`keys.py`/`users.py`) sólo **invocan** el gate. No se crea schema del dominio (todo viene de 013); a lo
sumo una tabla/registro pequeño para el **estado de licencia** y la **marca monotónica** anti-rollback. La
licencia se **inyecta como config** por la 020 (complementariedad explícita).

## Orden de implementación

1. **Fundacional — formato del token + verificador offline.** `token.py` + `verifier.py` + la clave
   pública embebida (`basa_public_keys.pem`) con unit tests (firma válida/alterada/mismatch/rotación por
   `key_id`). Es la base de US1 y bloquea el gate. La lib Ed25519 y el formato `.lic` ya están resueltos en
   [`research.md`](./research.md) (DIY Ed25519, PyNaCl/PyCA o PyJWT-EdDSA).
2. **US1 verificación al arranque (P1).** Cargar el token (env/secret/fichero de la 020), verificar
   offline, computar entitlement en memoria; fail-closed + audit si inválido/ausente/mismatch. Test con
   egress bloqueado.
3. **US2 gate de seats en creación (P1).** `seat_counter.py` (definición única de seat, [D-021]) + gate en
   `POST keys.py`/`users.py` (402/403 antes de `generate_key`), fail-closed, coexistiendo con el 409.
   MVP demostrable: no se puede crear el asiento N+1.
4. **US3 reconciliación (P2).** `reconcile.py` periódico local que detecta drift (`over_seat`) y dispara
   degradado + audit; misma definición de seat que US2.
5. **US4 expiry + grace + degradado (P2).** Cómputo de estado con reloj local; grace bloquea creación;
   expired → read-only-para-creación (toggle a bloqueo total); marca monotónica anti-rollback.
6. **US5 evidencia de tamper (P3).** `audit_events.py`: cada transición → AuditLog inmutable metadata-only;
   `license_clock_rollback_suspected`. Consolidar el endpoint de health/status.
7. **Cierre.** Verificación end-to-end con Docker Compose **sin egress**; validar `quickstart.md`;
   confirmar que el mismo binario opera con distintos tokens (Principio VII).

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **El cliente corre la caja → enforcement no es inviolable** (podrían parchear el binario o embeber otra clave pública). | Alto — evasión posible. | Objetivo realista: **fail-closed + evidencia auditable** (US5). No se promete inviolabilidad; se promete **detectabilidad innegable** para el contrato. Documentado en Assumptions. |
| **Caja sin egress** (on-prem/VPN): cualquier phone-home rompe el modelo. | Alto — producto inoperable en on-prem. | Verificación y reconciliación **100% locales** (Ed25519 con clave embebida); test con egress bloqueado (SC-001). |
| **Rollback de reloj** para evadir `expiry`. | Medio — extiende licencia vencida. | Marca **monotónica** (último ts visto); `now < marca` → sospecha + degradado + audit. Best-effort, explícito. |
| **Drift por restauración de backup / DB directa** crea seats fuera del gate. | Medio — más asientos que los pagados. | Reconciliación periódica (US3) detecta `over_seat` y degrada + audita. |
| **Confundir seats con uso** (usar `rpm_limit`/`max_budget` de 007 como licencia). | Medio — enforcement incorrecto. | Regla dura: seats = `COUNT(activas)`, ortogonal a 007; test explícito (SC-008). |
| **Definición ambigua de "seat"** (Connection vs User role=client). | Medio — conteo inconsistente entre gate y reconciliación. | **[D-021]** fija UNA definición (default `COUNT(APIKey activas)`) usada en ambos (FR-013); revisable en research. |
| **Rotación de la clave de Basa** rompe cajas ya desplegadas con la clave vieja. | Medio — deployments existentes dejan de validar. | Conjunto de claves públicas por `key_id` (FR-007); el token trae su `key_id`; se soportan N claves durante la migración. |
| **Downgrade de `max_seats`** en renovación deja al tenant over-seat de golpe. | Medio — bloqueo inesperado. | Política de US4: over-seat entra en grace/read-only-para-creación; NO se borran seats automáticamente; se documenta. |
| **Fail-open accidental** (bug que trata "sin token" como ilimitado). | Alto — se cae el enforcement en silencio. | Default fail-closed explícito (FR-006/FR-010) + tests negativos (SC-002); revisión de todos los early-returns del gate. |
| **Acoplamiento con la 020** (dónde/cómo se inyecta el token). | Bajo — fricción de integración. | Contrato claro: token como secret/env/fichero montado (FR-026); la 020 lo provee, esta spec sólo lo consume. |

## Complexity Tracking

> Sin violaciones de principio que justificar.

Esta feature no requiere excepciones constitucionales: refuerza VII (licencia = config firmada, no fork),
III (tope por tenant aislado) y II (audit inmutable como evidencia de tamper). La tensión intrínseca del
modelo distribuidor —enforcement offline *detectable* pero no *inviolable*— es una **propiedad del
negocio**, no una violación de principio; se aborda con fail-closed + evidencia auditable y se documenta
honestamente en `spec.md` (Assumptions) y en la tabla de Riesgos.
