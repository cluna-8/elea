# Spec 014 — Notas de implementación

**Fecha**: 2026-07-10 · **Estado**: **US1 + US2 + US3 + US4 + US5(contract) implementadas
y verificadas end-to-end** contra el proxy real (litellm 1.92.0 pinneado por digest).
Sólo queda **Polish** (T034-T037, opcional) — ver "Qué queda". La feature 014 está
**completa** en sus 5 user stories.

## Qué se entregó

- **Research T005** ([research.md](./research.md)): inspección del código real de la
  imagen. Confirmó las 4 firmas de hooks, que los guardrails corren sobre `/v1/messages`
  (`call_type="anthropic_messages"`), y que en streaming los chunks son **bytes SSE
  Anthropic crudos** (no `ModelResponseStream`). Decisión: **Estrategia A′** — hook
  nativo + rewrite SSE de la policy compartida dentro del hook (el motor sigue dueño
  del transporte; no se reimplementa framing, viola nada del Principio VI).
- **Pin** del motor por tag+digest (litellm 1.92.0) en `docker-compose.yml`.
- **`litellm/extensions/basa_guardian_policy.py`** (librería PURA, compartida entre el
  motor y el backend): mask reversible con nonce, unmask texto/estructuras, carry-split
  (`safe_split`, `rewrite_sse_block`, `StreamUnmasker`), y los detectores portados de
  los servicios heredados (PII regex, AI-Act Art.5, secretos) inyectables. 10 unit
  tests en `backend/tests/test_policy_unit.py`.
- **`custom_auth.py`** (US2): identidad `virtual key → key_hash → tenant/client/tool +
  toggles` contra la `APIKey` de la 013, vía el prisma client del motor (reuse, la
  imagen no trae otro driver). **Fail-closed**: sin key válida → 401; solo la master
  key del motor es admin. UA→tool portado 1:1 del demo.
- **`basa_guardrail.py`** (US1): `BasaGuardrail(CustomGuardrail)` con los 3 hooks —
  pre_call (AI-Act 400 / secretos block / mask reversible → `litellm_metadata.pii_tokens`),
  post_call_success (unmask no-streaming, Anthropic y OpenAI-like), y streaming (A′:
  decoder UTF-8 incremental + buffer de frames + carry-split, re-emite bytes).
- **`basa_audit_logger.py`** (US3): `CustomLogger` metadata-only con **scrub explícito
  de `pii_tokens`** (C1) + feed efímero a Redis (`basa:gw:events`, TTL 300s, preview
  YA enmascarado).
- **`backend/src/api/monitor.py`** (US3, vitrina): `GET /gw/monitor` (HTML autocontenido
  que refresca) + `GET /gw/events` (JSON del ring). Datos reales, cero PII cruda.
- **`backend/src/api/gateway.py`** (US4, T029-T031): el thin reverse-proxy de
  **suscripción OAuth** — la ÚNICA excepción de proxy propio (Principio VI). Reenvía el
  `Authorization`/OAuth del cliente **verbatim** a `api.anthropic.com` (la suscripción
  paga) e invoca la MISMA `basa_guardian_policy` que el guardrail: bloqueo AI-Act/
  secretos, mask/unmask reversible no-streaming y streaming (Estrategia A′ vía
  `rewrite_sse_block`). Identidad **[D-014]**: NO fail-closed acá (la credencial es el
  OAuth); `X-Basa-Key` = atribución opcional → tenant/client reales para auditoría;
  ausente → tenant por defecto anónimo, igual auditado. Feed del monitor con el MISMO
  esquema que el logger del motor (la vitrina renderiza ambas rutas). Passthroughs finos
  `count_tokens`/`models` (verbatim, sin política). Montado en `/api/v1/gw`.
- **Contract tests** (US5): `litellm/extensions/contract_checks.py` (20 checks de firmas
  + gotchas + round-trip, corre DENTRO de la imagen pinneada — puerta de bump),
  `integration_checks.py` (cableado del guardrail: mask/unmask/streaming/scrub), y
  **`backend/tests/contract/test_route_parity.py`** (T033, 20 tests): paridad de rutas
  (verdicto+mask del passthrough == librería compartida) + E2E del endpoint con upstream
  mockeado (block→400, mask→upstream/unmask→caller no-streaming y streaming incl. frame
  partido, OAuth verbatim, preview sin PII ni secretos, bodies malformados → 400 honesto).
- Registro en `litellm/config.yaml`: `custom_auth` + `custom_auth_run_common_checks` +
  bloque `guardrails` (`BasaGuardrail`, modes pre_call/post_call) + `callbacks`
  (audit logger). Mount `./litellm/extensions:/app/extensions`.

## Verificación end-to-end (proxy real, `http://localhost:4010/v1/messages`)

| Caso | Resultado |
|---|---|
| Sin key / key inválida | **401** (fail-closed, SC C3) |
| Key válida + práctica AI-Act Art.5 (`social scoring`) | **400** con verdicto del guardrail |
| Key válida + secreto (`sk-…`) | **400**, bloqueado antes del LLM |
| Key válida + prompt benigno | pasa auth+guardrail, falla en upstream (sin provider key) — el pipeline completo corre |
| `contract_checks.py` en la imagen | 20/20 OK contra litellm 1.92.0 |
| `integration_checks.py` (mask/unmask/streaming/scrub) | 13/13 OK — placeholder partido reensamblado, upstream ve placeholders, caller ve valores reales |
| `custom_auth` (detect_tool + resolución) | UA→tool y key→tenant/client verificados (la resolución DB vive en el proxy booteado) |

### Passthrough OAuth (US4), proxy real `http://localhost:8091/api/v1/gw/v1/messages`

| Caso | Resultado |
|---|---|
| AI-Act Art.5 (`social scoring`) | **400** `[Basa Gateway] … Ley de IA` (no toca upstream) |
| Secreto (`sk-…`) | **400**, bloqueado antes del upstream |
| Prompt benigno + `Authorization: Bearer …` | reenviado **verbatim** a `api.anthropic.com` → **401 `Invalid bearer token`** con `request_id` real de Anthropic (prueba que el OAuth llega intacto; con token válido, pasa) |
| Feed `/gw/monitor` | renderiza los eventos del passthrough (mismo esquema que el motor) |
| Body malformado (`[1,2,3]`, `null`, `messages:123`) | **400** honesto (no 500) tras el review |
| Preview de la vitrina con secreto | `[SECRET_REDACTED]` (C1: fix hallado en verificación live) |
| `test_route_parity.py` | **20/20** — paridad puro + E2E endpoint (upstream mockeado) |

> No hay provider keys ni ollama alcanzable en dev, así que **no se hizo round-trip contra
> un LLM real**. El mask→unmask (motor y passthrough) está verificado ejercitando los hooks
> con los tipos reales (`integration_checks.py`) y el endpoint con upstream mockeado que
> ECO del texto enmascarado (`test_route_parity.py`). El feed del monitor se poblará con
> tráfico exitoso real; el passthrough ya se probó reenviando OAuth de verdad a Anthropic.

**Review adversarial (US4)**: workflow multi-agente de 5 dimensiones (parity, streaming,
security/C1, identity-db, robustness) → 7 hallazgos crudos → **3 confirmados** tras verify
adversarial (parity/streaming/security/identity **limpias**). Los 3 (todos robustness) ya
aplicados + tests: (1) streaming `timeout=None` colgaba ante upstream mudo → `Timeout(None,
connect=10, read=60)`; (2) body JSON no-objeto → 500 → 400; (3) `messages` escalar → 500 →
400 (+ endurecido en la librería pura, protege ambas rutas).

## Decisiones tomadas

- **Estrategia A′** (research T005): el punto de extensión es nativo; el rewrite SSE de
  bytes ocurre DENTRO del hook porque en `/v1/messages` los chunks son bytes crudos.
  La misma `rewrite_sse_block` la usará el passthrough OAuth (US4) → paridad por librería.
- **`pii_tokens` en `litellm_metadata`** (no `metadata`): en la ruta anthropic el motor
  filtra `metadata` a los campos válidos de la API ANTES del upstream
  (`validate_anthropic_api_metadata`), así el mapa reversible no puede fugar al proveedor.
- **Gotchas de la research aplicados**: no definir `apply_guardrail` (redirigiría al
  unified_guardrail); override del streaming hook en la clase hoja; custom_auth resuelto
  relativo al config.yaml (mount al lado del config).
- **[D-014] identidad en suscripción — RESUELTO (US4)**: fail-closed duro solo en `byok`
  (motor, custom_auth); en `subscription-passthrough` la credencial es el OAuth y
  `X-Basa-Key` es atribución opcional (tenant-default anónimo auditado si falta).
  Implementado en `_resolve_attribution` + `_upstream_headers` (cliente verbatim, o
  `oauth_credential_ref` Fernet gestionado por Basa).
- **Montaje del gateway**: bajo `/api/v1/gw` (junto al monitor de US3, sin tocar
  `main.py`). El `ANTHROPIC_BASE_URL` de la coding tool apunta a `…/api/v1/gw`.

## Qué queda (Polish, opcional — la feature está completa en sus 5 US)

- **Polish** (T034-T037): `data-model.md` (consume el schema de la 013), `quickstart.md`
  (levantar → apuntar Claude Code a `/api/v1/gw` → ver `/monitor`), y enganchar los 12
  bugs del demo como contract tests del round-trip de deltas (coordinado con 016).
- **`oauth_credential_ref` (modo gestionado)**: implementado (descifra Fernet e inyecta),
  pero **no verificado con un OAuth de suscripción real** (no hay credencial en dev). El
  caso normal —cliente manda su propio OAuth verbatim— sí está verificado contra Anthropic.
- Sincronizar el `custom_auth` con el registro de keys en el motor: hoy `seed_client`/
  `/keys` no crean la virtual key en LiteLLM; `custom_auth` resuelve directo por
  `key_hash` contra la `APIKey` de Basa (preferido, sin doble fuente de verdad), pero
  el enforcement de budget/rpm del motor necesita la key registrada — reconciliación
  pendiente (nota del plan, FR-013).
