# Feature Specification: Política de auditoría cuando NO se puede auditar — por riesgo, no global

**Feature Branch**: `038-politica-audit-fail`

**Created**: 2026-08-17

**Status**: Sellada — D1–D5 aprobadas por JF el 18-ago (todas con la recomendación ★;
constancia en PR #221). `plan.md` + `tasks.md` listos; construye el equipo de Jeff (Ola 2)

**Input**: Dirección sellada en el weekly 05-ago: «política por nivel de riesgo/rol del
usuario (alta prioridad corta, baja prioridad sirve)» (`ROADMAP-pisos.md:32` y `:115`).
Esta spec cierra además la pregunta abierta del roadmap (`:129`): dónde vive (¿capa 027 o
spec propia?) y si se auditan también los errores.

## El problema, con evidencia (17-ago, líneas verificadas en el código)

1. **Hoy la decisión es GLOBAL por instalación**: `SENTINEL_AUDIT_FAIL=open|closed`, default
   `open` (ausente o ilegible ⇒ open), con lector único en el backend
   (`audit_service.py:59-69`) y espejo en el motor (`sentinel_guardrail.py:164-175`). Con
   `open` — el default, y lo que corre en la sede (#207) — un fallo de auditoría se cuenta
   (`sentinel:audit:lost`) y TODO el tráfico se sigue sirviendo sin fila; con `closed`, TODO
   corta con 503 — también el chat de riesgo mínimo.
2. **El producto ya resuelve riesgo POR PEDIDO y no lo usa para esto**: cascada
   User > Group > Tenant (spec 013 US4, `context_resolution.py:66-70`), aplicada por
   pedido (`chat.py:1319-1323`) y reportada como `applied_risk_level`. Hoy es metadata:
   no gobierna ninguna compuerta.
3. **Entre «servir sin fila» y «cortar», la primera es la IRREVERSIBLE**: la fila que no
   se escribió no existe nunca más; un 503 se reintenta. El default global actual elige la
   opción irreversible para todos los pedidos por igual.
4. **Precondición de honestidad**: la política decide sobre un camino de escritura que hoy
   tiene agujeros que se tragan filas en silencio — #207 (`model` no-string en `/gw`:
   200 sin fila), #176 (402 del motor sin fila), #212 (el 422 del literal contado como
   «permitido»). Una política por riesgo sobre escrituras que fallan calladas sería
   teatro.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - La instalación decide por riesgo, no a todo-o-nada (Priority: P1)

Con la base de auditoría caída: un empleado cuyo pedido resuelve `applied_risk_level`
mínimo/limitado sigue chateando (se sirve, se cuenta, el degradado se ve en `/health`);
un pedido que resuelve `high_risk_annex3` recibe el 503 honesto de siempre («esta
instalación no sirve tráfico de alto riesgo que no puede registrar»). El DPO ve cuántos
pedidos se sirvieron sin fila y desde cuándo.

**Why this priority**: es la dirección sellada del weekly hecha comportamiento; corta la
irreversibilidad exactamente donde el costo de perder el registro es más alto.

### User Story 2 - Compat total con lo que ya corre (Priority: P1)

La instalación que hoy setea `open` explícito y el examen de La ITV que exige `closed`
(`deploy/clients/itv-examen/client.env.example:43-45`) no cambian de comportamiento en
absoluto: ambos valores siguen siendo overrides globales con la semántica actual.

### User Story 3 - El integrador de /gw se entera a máquina (Priority: P2)

Cuando un pedido se sirvió sin fila, la respuesta de `/gw` lleva un marcador
machine-readable (precedente: `X-Sentinel-Rejected` del #135; pedido de marcador del #166),
para que el integrador decida reintentar, marcar o degradar su propio flujo.

## Requirements *(mandatory)*

- **FR-001**: La decisión servir/cortar ante auditoría no-disponible se toma POR PEDIDO en
  función del `applied_risk_level` resuelto por la cascada 013 (User > Group > Tenant), en
  los TRES planos (chat, `/gw`, motor byok), en el MISMO punto donde hoy se consulta
  `audit_fail_mode()` (pre-check antes del proveedor; los bloqueos siguen con
  registrar→bloquear).
- **FR-002**: Matriz default (D2): `high_risk_annex1`/`high_risk_annex3` → CORTA ·
  `minimal`/`limited` → SIRVE y cuenta. El rol NO participa para el tráfico (el riesgo ya
  compone persona/grupo/tenant vía la cascada). Las acciones de configuración (clase
  `config_audit`) no entran en esta política: siguen su camino actual.
- **FR-003**: `SENTINEL_AUDIT_FAIL` acepta `policy` además de `open|closed`. Los dos valores
  actuales explícitos = override global sin cambio de semántica. Default si
  ausente/ilegible: D1. El espejo triple (backend + motor + bundle) se actualiza junto y
  los lectores únicos siguen siendo únicos.
- **FR-004**: Todo pedido servido sin fila incrementa el contador existente
  (`sentinel:audit:lost`, contrato 031 en `/health` sin cambios) y — en `/gw` — marca la
  respuesta (D5).
- **FR-005** *(cierra «¿se auditan los errores?», #165)*: los 400/422 de validación previa
  NO generan fila durable (nunca fueron tráfico LLM); SÍ generan contador estructurado por
  tenant/endpoint + log sin cuerpo (D4).
- **FR-006**: Con `enforcement_tier_estricto=on` (018 US2) la instalación se comporta como
  `closed` global: el tier ya asevera la postura de `SENTINEL_AUDIT_FAIL`
  (`sentinel_governance.py:309-329`); la incoherencia sigue degradando health (D3).
- **FR-007** *(precondición)*: #207 y #176 se cierran antes o en el mismo ciclo que esta
  spec. #212 se corrige por call-site (estado propio para el 422 del literal SOLO en
  `/gw`, precedente `STATUS_SATURATED` en `gateway.py:1190`; en los otros dos planos el
  pedido se sirve y `passed` es correcto), coordinado con La ITV porque su reconcile
  cuenta literales exactos.

## Arquitectura (decisión de spec — no requiere sello de producto)

Vive como **spec propia** (esta), NO como capa nueva del catálogo 027: las capas 027 son
gobernanza de guardianes resoluble por credencial; esto es postura de servicio de la
instalación con contexto por-pedido. El mecanismo extiende el lector único:
`audit_fail_mode()` → `audit_fail_decision(contexto)` en `audit_service.py`, espejado en
el motor a través del probe existente (`/internal/audit/probe` gana el contexto de la
credencial). `enforcement_tier_estricto` queda como único punto de contacto con el
registry 027 (FR-006, ya existe). Barrido de lectores en la implementación: `.env.example`
(hoy NI documenta `SENTINEL_AUDIT_FAIL` — hueco del #190), `docker-compose.yml:81-84,170-172`,
`docs/docs/api-reference/errors.md:84-90` (y su referencia colgada a `configuration.md`),
contrato `specs/031-durable-audit/contracts/audit-durable.md:31-35`.

## Success Criteria

- **SC-001**: con la base de auditoría tumbada a mano y modo `policy`: pedido `minimal` →
  200 + contador incrementa; pedido `high_risk_annex3` → 503. Ambos demostrados contra el
  stack real, no contra mocks.
- **SC-002**: con `closed` explícito, comportamiento bit-a-bit idéntico al actual (la
  config del examen ITV pasa sin cambios).
- **SC-003**: 400/422 de validación previa: cero filas nuevas en `audit_logs` + contador
  por tenant/endpoint observable.

## ⚖️ Menú de sellos — SELLADO 18-ago (JF aprobó la recomendación ★ en las cinco)

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| D1 | Default de instalación | a) pasa a `policy` (ausente/ilegible ⇒ policy) · b) queda `open`, policy es opt-in | ★ **a**: el default actual elige la opción irreversible (servir sin fila) para TODOS; con policy el chat normal no cambia y lo annex3 empieza a cortar. La sede no setea la env ⇒ pasaría a policy |
| D2 | La matriz la manda solo el riesgo (roles fuera) | a) sí · b) sumar eje de rol | ★ **a**: la cascada 013 ya compone persona/grupo/tenant; un eje de rol duplicaría el mecanismo |
| D3 | Tier estricto ⇒ `closed` global | a) sí · b) no, tier y política independientes | ★ **a**: coherente con la aserción de postura que la 018 ya hace |
| D4 | Errores 400/422 | a) sin fila + contador estructurado · b) fila durable para todo | ★ **a**: la fila diluye la señal del DPO y abre spam de filas; el contador cierra #165 |
| D5 | Marcador machine-readable en `/gw` al servir sin fila | a) sí · b) no | ★ **a**: honestidad a máquina, precedente #166 / `X-Sentinel-Rejected` |

Sello registrado en PR #221 (comment del 18-ago). `plan.md` y `tasks.md` viven en este
mismo directorio. Construye el equipo de Jeff (Ola 2 del sprint al 5-sep).
