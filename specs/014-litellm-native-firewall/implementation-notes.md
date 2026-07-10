# Spec 014 — Notas de implementación

**Fecha**: 2026-07-10 · **Estado**: **US1 + US2 + US3 + US5(contract) implementadas y
verificadas end-to-end** contra el proxy real (litellm 1.92.0 pinneado por digest).
Falta **US4** (passthrough OAuth de suscripción) — ver "Qué queda".

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
- **Contract tests** (US5): `litellm/extensions/contract_checks.py` (20 checks de firmas
  + gotchas + round-trip, corre DENTRO de la imagen pinneada — puerta de bump) y
  `integration_checks.py` (cableado del guardrail: mask/unmask/streaming/scrub).
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

> No hay provider keys ni ollama alcanzable en el entorno dev, así que **no se hizo un
> round-trip contra un LLM real**. El mask→unmask está verificado ejercitando los hooks
> directamente con los tipos reales del motor (`integration_checks.py`); el feed del
> monitor se poblará con tráfico exitoso real.

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
- **[D-014] identidad en suscripción**: sin implementar aún (es US4). El diseño previsto:
  fail-closed duro solo en `byok`; en `subscription-passthrough` la credencial es el
  OAuth y `X-Basa-Key` es atribución opcional (tenant-default anónimo auditado si falta).

## Qué queda (siguiente sesión)

- **US4 — passthrough OAuth de suscripción** (T029-T031): crear el thin reverse-proxy
  en `backend/src/api/gateway.py` (NO existe aún en este repo; se porta de
  `../gatelite-salud-eu/backend/src/api/gateway.py`) que reenvía el `Authorization`/OAuth
  verbatim a `api.anthropic.com` invocando `basa_guardian_policy` (block+mask+unmask,
  carry-split streaming). Router GDPR = N/A. **Requiere OAuth de suscripción real para
  verificar** — por eso se difiere. Materializa [D-014].
- **US5 restante** (T033): contract test de **paridad de rutas** (motor BYOK vs
  passthrough) — depende de que US4 exista.
- **Polish** (T034-T037): `data-model.md`, `quickstart.md`, retiro final (FR-030),
  enganchar los 12 bugs del demo como contract tests del round-trip (coordinado con 016).
- Sincronizar el `custom_auth` con el registro de keys en el motor: hoy `seed_client`/
  `/keys` no crean la virtual key en LiteLLM; `custom_auth` resuelve directo por
  `key_hash` contra la `APIKey` de Basa (preferido, sin doble fuente de verdad), pero
  el enforcement de budget/rpm del motor necesita la key registrada — reconciliación
  pendiente (nota del plan, FR-013).
