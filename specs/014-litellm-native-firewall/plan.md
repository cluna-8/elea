# Implementation Plan: LiteLLM-Native Firewall (base_url clients)

**Branch**: `014-litellm-native-firewall` | **Date**: 2026-07-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/014-litellm-native-firewall/spec.md`

## Summary

Portar el firewall del demo (hoy hand-rolled en `gatelite-salud-eu/backend/src/api/gateway.py`) a
extensiones **nativas** de LiteLLM, con una arquitectura **híbrida** de dos hogares:

1. **Motor LiteLLM** (ruta BYOK + guardrails + audit): la política Basa vive en tres puntos de
   extensión documentados — `BasaGuardrail` (CustomGuardrail: pre/post/streaming), `custom_auth`
   (identidad), `BasaAuditLogger` (CustomLogger: audit metadata-only) — sobre el endpoint
   `/v1/messages` nativo con guardrails ON. El motor pasa a ser dueño del framing SSE, la
   decodificación UTF-8, el parsing de usage, los reintentos/fallbacks/rpm-tpm/cost-ceiling.
2. **Backend** (única excepción del Principio VI): el passthrough OAuth de **suscripción**, porque
   LiteLLM reclama el header `Authorization` como su virtual key y el token OAuth Pro/Max no puede
   atravesar el motor. Es un thin reverse-proxy que reenvía el OAuth verbatim pero **importa** la misma
   `basa_guardian_policy` que el guardrail, para no divergir.

Ambos hogares comparten una **librería pura** `basa_guardian_policy` (mask/unmask/detect/carry-split).
El enfoque técnico central: **reuso del motor** (Principio VI) — sólo la política Basa es código propio;
todo lo de infraestructura de protocolo se delega. La entrega se pinnea por versión y se blinda con
contract tests de las firmas de los hooks + su ejecución sobre `/v1/messages`.

## Technical Context

**Language/Version**: Python 3.11 (backend FastAPI heredado + módulos de extensión montados en el
contenedor LiteLLM).

**Primary Dependencies**: LiteLLM (motor white-label, **pinneado** por tag+digest) con sus interfaces
`CustomGuardrail` / `CustomLogger` / `custom_auth` / `UserAPIKeyAuth` / `ModelResponseStream`; FastAPI +
httpx (backend, sólo para el passthrough OAuth de suscripción); servicios existentes
`ComplianceService`, `GuardianService`, `PresidioService`, `AuditService`.

**Storage**: PostgreSQL (modelos `APIKey`/`AuditLog` de la 013, metadata-only). Feed del monitor:
ring en memoria (efímero, no persistido). Redis heredado (no central a esta spec).

**Testing**: pytest — **contract tests** de las 4 firmas contra la versión pinneada + ejecución sobre
`/v1/messages`; integration tests por user story; unit tests de `basa_guardian_policy` (carry-split,
colisión de placeholder, round-trip text/thinking/tool_use).

**Target Platform**: Linux server en containers (Docker Compose es la base de la verificación local,
Principio VII).

**Project Type**: web-service (backend FastAPI + motor LiteLLM en containers separados). Extensiones del
motor montadas como volumen (mismo patrón que `./litellm/config.yaml:/app/config.yaml`).

**Performance Goals**: no degradar la latencia del proxy actual; el masking/unmask corre inline en los
hooks. Sin objetivo de throughput nuevo (el motor ya gobierna rpm/tpm).

**Constraints**: masking ANTES de cualquier compresión (los placeholders son tokens atómicos); el mapa
reversible jamás se delega ni se persiste (Constraint C1); fail-closed en identidad (Constraint C3); credenciales fuera de
`config.yaml` en claro (Constraint C5). GDPR-routing N/A en esta ruta base_url (excepción acotada Principio II).

**Scale/Scope**: 5 módulos nuevos (guardrail, policy, custom_auth, logger, monitor) + `config.yaml` +
adelgazamiento de `gateway.py` + pin de imagen. Sin schema nuevo propio (todo el schema viene de 013).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio / Constraint | Cómo lo cumple esta feature | Veredicto |
|---|---|---|
| **I. Privacy & Masking-First** | Masking reversible en el guardrail (motor) y en el passthrough (misma policy); placeholders atómicos; mapa en `metadata.pii_tokens`, nunca delegado; unmask en respuesta incl. streaming. | PASS by-design / a verificar |
| **II. Compliance FIRST** | Enforcement duro en `async_pre_call_hook` (AI-Act Art.5→400, secretos→block). **Excepción documentada**: GDPR-routing N/A en la ruta base_url; garantía trasladada a masking/audit/allowlist. | PASS by-design / a verificar (con excepción acotada ya ratificada) |
| **VI. LiteLLM-Native, No Patching** | Reusa `CustomGuardrail`/`custom_auth`/`CustomLogger`/`/v1/messages` nativo; NO reimplementa routing/streaming/cost-ceiling. **Única excepción**: passthrough OAuth de suscripción en backend, que importa la policy compartida (no reimplementa). Pin de versión + contract tests. | PASS by-design / a verificar |
| **VIII. Pipeline Transparency** | `pipeline_metadata` real por capa (mask→compliance→routing→unmask); monitor en vivo alimentado por el CustomLogger, animación cosmética sobre datos reales. | PASS by-design / a verificar |
| **Constraint C1 No Raw PII/PHI Storage** | Audit metadata-only; scrub explícito de `pii_tokens` en el logger + test negativo. | PASS by-design / a verificar |
| **Constraint C3 Fail-closed auth** | `custom_auth` rechaza requests BYOK sin virtual key válida; no cae a admin. | PASS by-design / a verificar |
| **Constraint C5 Credenciales fuera de config** | Referencia OAuth de suscripción y master key vía env/secretos, no en `config.yaml` en claro. | PASS by-design / a verificar |
| **Dev Workflow — Reuse over Reinvent** | El port borra ~470 líneas hand-rolled y delega al motor; sólo la policy Basa es propia. | PASS by-design / a verificar |

**Única violación justificada → ver Complexity Tracking**: el passthrough OAuth de suscripción es proxy
propio (excepción explícita del Principio VI, autorizada por la constitución).

## Mapeo demo → hooks nativos

Traducción fiel de `gateway.py` (demo) a los puntos de extensión (objetivo). Columna "Dueño" =
REUSA-motor vs PROPIO.

| Demo (gateway.py, hand-rolled) | Objetivo nativo | Dueño |
|---|---|---|
| `POST /gw/v1/messages` | `/v1/messages` nativo con guardrails ON | REUSA motor |
| `_extract_inspect_text` + `ComplianceService.evaluate_prompt` + `GuardianService.process_prompt` (bloqueo) | `BasaGuardrail.async_pre_call_hook` | PROPIO (wrapper) |
| `_redact_body` (mask reversible con nonce) | `async_pre_call_hook` → `basa_guardian_policy.mask_reversible`; mapa en `data["metadata"]["pii_tokens"]` | PROPIO (policy) |
| unmask no-streaming (`_unmask`/`_unmask_deep` en la rama `not is_stream`) | `async_post_call_success_hook` | PROPIO (wrapper) |
| `_rewrite_sse_event` + `gen_redacted` (rewrite de bytes SSE, decoder UTF-8, flush de carry) | `async_post_call_streaming_iterator_hook` sobre `ModelResponseStream`; **sólo** se porta el carry-split | PROPIO (carry) + REUSA motor (framing/decoder/usage) |
| `_safe_split` / `_PH_TYPE_RE` / `_PH_TAIL_RE` | `basa_guardian_policy` (carry-split) | PROPIO (policy) |
| `_detect_tool` / `_TOOL_UA` | `custom_auth.user_api_key_auth` (UA→tool_type) | PROPIO (resolución) |
| `_resolve_identity` (X-Basa-Key → user/group) | `custom_auth` (virtual key → tenant/client/team vía `APIKey`) | PROPIO (resolución) sobre `UserAPIKeyAuth` del motor |
| `_log_tx` → `AuditService.log_transaction` | `BasaAuditLogger.async_log_success_event` + scrub `pii_tokens` | PROPIO (wrapper), REUSA `AuditService` |
| `_IN_RE`/`_OUT_RE` (parsing de tokens en SSE crudo) | usage/tokens del motor | REUSA motor (se borra) |
| `Accept-Encoding: identity`, `codecs.getincrementaldecoder` | framing/decodificación del motor | REUSA motor (se borra) |
| `_plain_passthrough` + `/gw/v1/messages/count_tokens` + `/gw/v1/models` | endpoints nativos del motor | REUSA motor (se borra) |
| modo `subscription-passthrough` (013; "anthropic" en el demo) — OAuth passthrough | thin reverse-proxy en backend + `basa_guardian_policy` | PROPIO (única excepción VI) |
| `_LIVE` deque + `/gw/events` + `/gw/monitor` (`_MONITOR_HTML`) | ring en memoria del logger + vista de monitor | PROPIO (vitrina) |
| `/gw/config` toggle `_REDACT_MODE` (singleton global) | toggle por-key (`redact_enabled` de la Connection/013), leído del contexto resuelto | PROPIO (lee de 013, no del config global) |

## Project Structure

### Documentation (this feature)

```text
specs/014-litellm-native-firewall/
├── plan.md              # This file
├── spec.md              # Feature spec (user stories, FR, SC)
├── tasks.md             # Task list (por user story)
├── research.md          # Phase 0 (a generar): madurez de guardrails sobre /v1/messages, 2 estrategias de unmask streaming
├── data-model.md        # Phase 1 (a generar): consume el schema de la 013 (no crea schema propio)
├── quickstart.md        # Phase 1 (a generar): levantar el contenedor + apuntar Claude Code + ver el monitor
└── contracts/           # Phase 1 (a generar): firmas de los 3 hooks + user_api_key_auth vs versión pinneada
```

### Source Code (repository root)

```text
litellm/                                   # montado en el contenedor LiteLLM (volumen)
├── config.yaml                            # + guardrails / callbacks / custom_auth; conserva model_list + fallbacks
└── extensions/                            # paquete de extensiones Basa (nuevo)
    ├── basa_guardian_policy.py            # PROPIO: librería pura (mask/unmask/detect/carry-split) — compartida
    ├── basa_guardrail.py                  # PROPIO: BasaGuardrail(CustomGuardrail) — 3 hooks
    ├── custom_auth.py                     # PROPIO: user_api_key_auth (identidad, fail-closed)
    └── basa_audit_logger.py               # PROPIO: BasaAuditLogger(CustomLogger) — audit + feed monitor

backend/src/
├── api/
│   ├── gateway.py                         # ADELGAZADO: sólo passthrough OAuth de suscripción sobre basa_guardian_policy
│   └── monitor.py                         # PROPIO (vitrina): vista de monitor + feed en memoria
├── services/                              # REUSADOS sin cambios: compliance/guardian/presidio/audit
└── models/                                # REUSADOS de la 013: APIKey (=Connection), AuditLog, Tenant

tests/
├── contract/                              # firmas de hooks + custom_auth vs versión pinneada; ejecución sobre /v1/messages
├── integration/                           # por user story (block/mask/unmask/identity/audit/passthrough)
└── unit/                                  # basa_guardian_policy: carry-split, colisión, round-trip

docker-compose.yml                         # image litellm: main-latest -> tag+digest PINNEADO
```

**Structure Decision**: web-service en containers (Principio VII). El código propio se divide por
**hogar de ejecución**: (a) extensiones montadas en el contenedor LiteLLM (`litellm/extensions/`) para
la ruta motor; (b) el backend FastAPI (`backend/src/api/gateway.py` adelgazado + `monitor.py`) para la
única excepción (passthrough OAuth) y la vitrina. La librería pura `basa_guardian_policy` es importable
desde ambos hogares (mismo paquete instalable / path compartido) para garantizar DRY. No se crea schema
nuevo: todo viene de la 013.

## Orden de implementación

1. **Fundacional — librería pura + pin.** `basa_guardian_policy` (mask/unmask/detect/carry-split,
   portando `_redact_body`/`_unmask`/`_safe_split`/`_PH_*_RE`) con unit tests; pin de la imagen LiteLLM
   por tag+digest. Bloquea todo lo demás (ambos hogares la importan).
2. **US2 identidad (P1).** `custom_auth.user_api_key_auth` (UA→tool_type + virtual key→tenant/client/team,
   fail-closed) registrado en `general_settings.custom_auth`. Va antes que US1 porque los hooks consumen
   su metadata de identidad.
3. **US1 firewall nativo (P1).** `BasaGuardrail` con los tres hooks importando la policy; registro en
   `guardrails:` con los tres modes. MVP demostrable: block + mask + unmask (no-streaming y streaming).
4. **US3 audit + monitor (P2).** `BasaAuditLogger` (metadata-only + scrub) en
   `litellm_settings.callbacks`; feed en memoria + vista de monitor.
5. **US4 excepción suscripción (P2).** Adelgazar `gateway.py` a sólo el passthrough OAuth, reescrito
   sobre `basa_guardian_policy`; borrar `/gw/v1/messages`, count_tokens, models, `_rewrite_sse_event`,
   `_redact_body`, `_detect_tool`, `_resolve_identity`, `_passthrough_headers`, `_IN_RE`/`_OUT_RE`.
6. **US5 contract tests (P3).** Firmas de los 4 puntos de extensión vs versión pinneada + ejecución
   sobre `/v1/messages` + paridad de rutas (motor vs passthrough).
7. **Cierre.** Verificación con Docker Compose; validación de `quickstart.md`; retiro final del código
   propio (FR-030) confirmado.

## Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| **La doc de LiteLLM va por detrás del código**: firmas reales de los hooks / `custom_auth` pueden diferir de lo documentado. | Alto — el port no compila / no ejecuta. | Phase 0 research que inspecciona el código de la versión **pinneada** (no la doc); contract tests como puerta (US5). |
| **Guardrails podrían no ejecutarse sobre `/v1/messages` nativo** (sólo `/chat/completions`). | Alto — el masking no correría en la ruta titular. | Contract test explícito (FR-028); si no corre, fallback documentado a un shim que enruta `/v1/messages` por el pipeline de guardrails. |
| **Unmask en streaming tiene 2 estrategias** (ver abajo). | Medio — round-trip incorrecto entrega placeholders crudos o corrompe tool-calls. | Elegir estrategia en Phase 0 research; portar los tests de los 12 bugs del demo (formalizados en 016) como contract tests. |
| **Fuga de `pii_tokens`**: viaja en `metadata`; si un callback lo persiste se viola Constraint C1. | Alto — incumplimiento de compliance. | Scrub explícito en el logger + test negativo; revisar que ningún otro callback lo toque. |
| **Deriva entre los dos call-sites** (motor BYOK vs backend suscripción). | Medio — verdictos/masking divergentes. | Librería pura compartida + contract test de paridad (FR-029). |
| **Despinnear cambia superficie de comportamiento**; el pin puede quedar atrás en features. | Bajo — deuda de mantenimiento. | Proceso: bump + correr contract tests, no reescribir (Principio VI). |
| **Ambigüedad de identidad en suscripción sin `X-Basa-Key`** (Constraint C3 vs modo sin key). | Medio — o se rompe la demo, o se abre un agujero. | **Resuelto por [D-014]** (default revisable): fail-closed duro sólo en `byok`; en `subscription-passthrough` la credencial es el OAuth y `X-Basa-Key` es atribución opcional (si falta, `tenant-default` anónimo, auditado como tal). US4 desbloqueado. |
| **Provisioning virtual keys ↔ APIKey Basa** (doble fuente de verdad). | Medio — identidad inconsistente. | Resolución directa por `key_hash` contra `APIKey` en `custom_auth` (mantiene el modelo de identidad en 013). |

### Dos estrategias para el unmask en streaming (decisión de Phase 0)

- **Estrategia A — hook sobre objetos parseados (`ModelResponseStream`)**: el motor entrega chunks ya
  decodificados; `async_post_call_streaming_iterator_hook` recorre los deltas
  (text/thinking/tool_use.input_json), aplica unmask y mantiene el carry-split de `basa_guardian_policy`.
  **Preferida** (Principio VI: el motor hace framing/decoder/usage; sólo portamos el carry). Riesgo:
  depende de que el motor exponga los deltas de la Messages API sin normalizarlos de forma que rompa el
  round-trip de tool_use.
- **Estrategia B — rewrite de bytes SSE (como el demo)**: replicar `_rewrite_sse_event` + decoder UTF-8.
  **Rechazada salvo bloqueo de A**: reintroduce framing/decoder propios (viola VI). Sólo como fallback si
  el hook parseado del motor no cubre la ruta `/v1/messages`.

## Complexity Tracking

> Única violación de principio a justificar.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| Passthrough OAuth de suscripción = **proxy propio** en el backend (excepción del Principio VI) | LiteLLM reclama el header `Authorization` como su virtual key, así que el token OAuth Pro/Max del cliente **no puede** atravesar el motor. Sin este proxy no existe la "firewall on top of your subscription story" (el caso que hace las demos). | Enrutar la suscripción por el motor es imposible: el motor sobreescribiría el `Authorization` con su master/virtual key y la suscripción del cliente nunca pagaría. La constitución **autoriza explícitamente** esta única excepción; se acota importando `basa_guardian_policy` (no reimplementa la política) y con un contract test de paridad. |
