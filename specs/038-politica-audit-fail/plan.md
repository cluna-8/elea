# Implementation Plan: Política de auditoría cuando NO se puede auditar — por riesgo, no global

**Branch**: `038-politica-audit-fail` | **Date**: 2026-08-18 | **Spec**: [spec.md](./spec.md)

**Input**: spec.md con D1–D5 **selladas por JF el 18-ago** (todas con la recomendación del
manager; constancia en PR #221). La evidencia de código de la spec fue re-verificada contra
`origin/main@85c9c55` al escribir este plan; donde una línea derivó, acá va la vigente.

## Summary

`BASA_AUDIT_FAIL` gana el valor `policy` y pasa a ser el **default** (D1). En modo policy,
la decisión servir/cortar ante auditoría no-disponible se toma **por pedido** según el
`applied_risk_level` que la cascada 013 ya resuelve: `minimal`/`limited` sirve y cuenta,
`high_risk_annex1`/`annex3` corta con el 503 honesto (D2). `open`/`closed` explícitos
siguen siendo overrides globales bit-a-bit idénticos a hoy; el tier estricto sigue
imponiendo postura `closed` (D3). Los 400/422 de validación previa dejan contador
estructurado sin fila durable (D4, cierra #165) y `/gw` marca a máquina toda respuesta
servida sin fila (D5).

## Technical Context

**Language/Version**: Python 3.12 (backend FastAPI + extensiones litellm del motor)

**Primary Dependencies**: FastAPI, SQLAlchemy async, Redis (contadores), litellm (motor)

**Storage**: Postgres (`audit_logs` — sin cambios de schema) · Redis (`basa:audit:lost`
existente + contador nuevo D4)

**Testing**: `cd backend && pytest tests/ -q` (unit + contract + integration); SC-001/002/003
contra stack real (evidencia E2E en el PR, capa 4 del merge autónomo)

**Target Platform**: instalación on-prem (docker compose), 3 planos: chat, `/gw`, motor byok

**Project Type**: web-service multi-plano (backend + espejo en motor)

**Constraints**: fail-closed hacia lo REVERSIBLE (un 503 se reintenta; una fila no escrita
no vuelve) · overrides `open`/`closed` sin cambio de semántica (SC-002) · lectores de env
únicos por proceso · decisión centralizada en el backend (el motor pregunta, no decide)

## Puntos de anclaje medidos (origin/main@85c9c55, 18-ago)

| Qué | Dónde |
|---|---|
| Lector único backend | `backend/src/services/audit_service.py:59` (`audit_fail_mode()`) |
| Espejo motor — **son DOS lectores, no uno** | `litellm/extensions/basa_guardrail.py:164` (`_audit_fail_mode()`, pre-check closed vía probe cacheado 5 s `:280`) **y** `litellm/extensions/basa_audit_logger.py:88` (`audit_fail_mode()`, camino de escritura) |
| Probe interno | `GET /api/v1/internal/audit/probe` (consumido por guardrail `:99`, tests `backend/tests/integration/test_internal_plane.py:43`) |
| Cascada de riesgo (013) | `backend/src/services/context_resolution.py:66-70` → aplicada por pedido en `backend/src/api/chat.py:1319` (`_applied_risk_level`) |
| Aserción de postura del tier (018 US2) | `backend/src/services/basa_governance.py` (§ hoy :309-329) |
| Precedente marcador máquina | `X-Basa-Rejected` (#135) · `STATUS_SATURATED` en `gateway.py:1199` |
| Contador existente | `basa:audit:lost` (`audit_service.py:35`, contrato 031 `/health`) |
| Lectores de config/doc a barrer | `.env.example` (hoy NO documenta `BASA_AUDIT_FAIL` — hueco #190) · `docker-compose.yml:91,178-179` · `docs/docs/api-reference/errors.md:84-90` (+ referencia a `configuration.md`) · `specs/031-durable-audit/contracts/audit-durable.md:31-35` · **`frontend/src/services/api.ts`** (lector no listado en la spec, encontrado en el barrido del 18-ago) · `deploy/clients/itv-examen/client.env.example:43-45` (NO cambia — es el testigo de SC-002) |

## Diseño del mecanismo

1. **Parser de modo** (backend): `BASA_AUDIT_FAIL ∈ {open, closed, policy}`; ausente o
   ilegible ⇒ `policy` (D1). `audit_fail_mode()` conserva nombre y contrato de string para
   los llamadores existentes.
2. **Punto de decisión nuevo**: `audit_fail_decision(risk_level: str | None) -> bool`
   (¿se sirve sin fila?) en `audit_service.py`, único lugar donde vive la matriz D2:
   `minimal`/`limited` → sirve · `annex1`/`annex3` → corta · `None`/desconocido → corta
   (fail-closed hacia lo reversible). La clase `config_audit` NO pasa por acá (FR-002).
3. **Tres planos, mismo punto**: cada plano llama a la decisión donde HOY consulta
   `audit_fail_mode()` — chat y `/gw` en el backend con su `applied_risk_level` ya
   resuelto; el motor byok vía **probe con contexto**: el probe existente acepta la
   credencial del pedido y responde servir/cortar ya decidido (la matriz nunca se duplica
   en el motor; el cache de 5 s del guardrail pasa a cachear por-modo y NO por-decisión
   cuando el modo es `policy` — a evaluar en implementación con el criterio: jamás cachear
   una decisión de riesgo de un pedido para otro).
4. **Tier estricto** (D3): con `enforcement_tier_estricto=on`, la postura efectiva es
   `closed` global; la aserción existente de `basa_governance` se extiende para tratar
   `policy` como incoherencia igual que hoy trata `open` (degrada health, no corta boot).
5. **Contadores y marcador**: servir sin fila ⇒ `INCR basa:audit:lost` (igual que hoy,
   contrato 031 sin cambios) + en `/gw` header machine-readable (D5; nombre propuesto
   `X-Basa-Audit-Lost: 1`, sellado a nivel spec como «marcador», nombre final es decisión
   de implementación documentada en el contrato). Los 400/422 de validación previa ⇒
   contador estructurado por tenant/endpoint + log sin cuerpo, cero filas (D4).

## Constitution / Gates

- **Área de riesgo: SÍ** — gobierna si se sirve tráfico sin registro de auditoría
  (compliance). Gate completo: review adversarial cross-familia del manager en cada PR de
  implementación + evidencia E2E real (SC-001/002/003) para el merge.
- **Decisiones de producto**: TODAS selladas (D1-D5, 18-ago). Ningún PR de esta spec
  introduce decisión nueva ⇒ elegible para merge autónomo con harness completo.
- **QA Bob**: sin superficie visible nueva (el 503 y `/health` ya existen). Pasada
  dirigida solo si la implementación termina tocando el panel (`frontend/`).
- **Precondición FR-007 (gate de arranque, estado 18-ago)**: #176 CERRADO ✅ · **#207
  ABIERTO** (se cierra antes o en el mismo ciclo — bloquea el checkpoint de US1) · **#212
  ABIERTO** (call-site en `/gw`, coordinado con La ITV — no bloquea US1, sí el cierre de
  la spec). Sin esto, la política decide sobre escrituras que fallan calladas = teatro.

## Project Structure

### Documentation (this feature)

```text
specs/038-politica-audit-fail/
├── spec.md              # sellada 18-ago (D1-D5)
├── plan.md              # este archivo
└── tasks.md             # descomposición para el equipo de Jeff (Ola 2)
```

(Sin `research.md`/`data-model.md` propios: la evidencia vive en spec §«El problema» y fue
re-medida acá; no hay entidades nuevas ni cambio de schema.)

### Source Code (repository root)

```text
backend/src/services/audit_service.py      # parser 3 valores + audit_fail_decision()
backend/src/services/basa_governance.py    # aserción tier vs policy (D3)
backend/src/api/chat.py                    # plano chat: decisión por pedido
backend/src/api/gateway.py                 # plano /gw: decisión + marcador D5 + contador D4
backend/src/api/<internal probe>           # probe con contexto de credencial
litellm/extensions/basa_guardrail.py       # pre-check por pedido vía probe (lector 1)
litellm/extensions/basa_audit_logger.py    # camino de escritura (lector 2)
backend/tests/{unit,contract,integration}/ # RED→verde por fase (ver tasks.md)
.env.example · docker-compose.yml · docs/docs/api-reference/errors.md ·
specs/031-durable-audit/contracts/audit-durable.md · frontend/src/services/api.ts
```

**Structure Decision**: sin módulos nuevos — la spec extiende el lector único existente y
sus tres consumidores. El único contrato que se toca es el del probe interno (gana
contexto) y la doc del 031 (documenta `policy`).

## Complexity Tracking

Sin violaciones: cero dependencias nuevas, cero tablas nuevas, un solo punto de decisión.
El riesgo del cambio es semántico (postura de servicio), no estructural — por eso el gate
es adversarial completo aunque el diff vaya a ser chico.
