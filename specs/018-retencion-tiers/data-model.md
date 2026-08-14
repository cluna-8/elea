# Data Model — 018 (cero migraciones: todo opera sobre esquema existente)

## Clase de retención (existente: `retention_policies`, seed 004:100-109)

| Campo | Estado | Notas |
|---|---|---|
| `log_type` (UNIQUE global) | sin cambios | FR-010: partición `(tenant_id, log_type)` diferida con nombre |
| `retention_days` | sin cambios | validación de rango pasa al backend (FR-007): mínimos por clase + pisos/topes por tier (tabla en research.md D7). **Piso independiente en el punto de destrucción** — ver abajo |
| `purge_log` (JSONB) | **estrena escritores** | ver «Corrida de purga» |

Las 4 clases y su predicado sobre `audit_logs` viven en el **clasificador** (contrato 1 en `contracts/`), no en el esquema.

### Piso del plazo en el purgador (`PLAZO_MINIMO_DIAS`) — implementado con T008, dictamen del manager 14-ago

La columna **no tiene CHECK de rango**: medido contra el Postgres del compose el 14-ago, `retention_policies` tiene exactamente tres constraints —PK, `UNIQUE (log_type)` y la FK de tenant— y el seed 004 no agrega ninguna. La única regla del esquema es `INTEGER NOT NULL` (`alembic/versions/004_compliance_tables.py:92`, `models/compliance.py:96`), así que el `0` y los negativos son valores que la tabla admite.

Por eso el purgador lleva su propio piso, y va anotado acá porque es una regla efectiva sobre esta columna que **no** sale del esquema ni del endpoint:

| Dónde | Qué | Efecto |
|---|---|---|
| `purger.PLAZO_MINIMO_DIAS = 1` (`purger.py:536`) | menor plazo con el que el cutoff cae en el PASADO | constante única, sin mínimos por clase (hoy no hay ninguno legible por código) |
| `_plazo_en_dias` (`purger.py:554`, chequeo en `:579`) | paso obligado del plazo de una clase | `retention_days < 1` → `PlazoDeRetencionInvalido`: **aborta esa clase** (`result: error`, `cutoff: None`, `rows_deleted: 0`), las otras tres siguen |
| `cutoff_de_residuo` (`purger.py:667`, chequeo en `:692`) | umbral del contador `filas_no_clasificadas` | sin plazo válido no se cuenta: `filas_no_clasificadas = None`, nunca `0` |

Rige **también en simulacro** — un ensayo con plazo inválido reportaría un conteo bajo `cutoff = AHORA`, que es el número que el DPO firma. Cobertura: `tests/integration/test_retention_piso_plazo.py` (8 casos; la tabla de mutación que mide que muerden —cero sobrevivientes, 14-ago— está en el docstring de ese archivo).

**Alcance, dicho en voz alta**: el piso defiende del presente y del futuro (`0`, negativos), **no** de un plazo válido pero absurdamente corto. Con `retention_days=1` el cutoff cae en `ahora − 1 día` y la clase se vacía salvo las últimas 24 h — el endpoint lo acepta hoy con 200 y el purgador lo ejecuta. Cerrar ESE hueco es FR-007/T015 (mínimos por clase y pisos del tier), que se apila encima de este piso sin reemplazarlo.

## Corrida de purga (sin tabla nueva)

Representación doble, ambas metadata-only:

1. **Entrada en `purge_log`** (JSONB de su clase, capado a las últimas 50 corridas):
   `{run_id, started_at, finished_at, cutoff, rows_deleted, batches, window, result: ok|partial|error, dry_run, filas_no_clasificadas}`
2. **Fila resumen en `audit_logs`** clase `config_audit` (mismos campos como metadata) — entra al canal de evidencia estándar del DPO y muere a los 730 d como cualquier config_audit.

*(enmiendas del manager: `dry_run` 13-ago — Contrato 4 regla 3 —, `filas_no_clasificadas` 14-ago — Contrato 1 regla 6.)* Los dos campos son obligatorios y por el mismo motivo: sin `dry_run`, simulacro y corrida real dejan un rastro idéntico y el registro afirma borrados que nunca ocurrieron; sin `filas_no_clasificadas`, el residuo del fail-closed —las filas que el portón no pudo demostrar que fueran tráfico y por eso nadie borró— no tiene número y «nadie se entera». `filas_no_clasificadas` sale **también en la corrida `dry_run`**: el officer que ensaya la purga tiene que ver el residuo antes de apretar el botón.

Idempotencia: el predicado es «vencida al momento de la corrida» contra el reloj de la DB — una corrida interrumpida que se relanza no duplica el efecto (las borradas ya no están) y no salta filas (las vencidas siguen matcheando). El `purge_log` registra `result: partial` para la interrumpida.

## Tier de enforcement (existente: `governance_profiles`, migración 012)

- Capa nueva **solo en código**: `enforcement_tier_estricto`, decision `on`/`off` (CHECK existente respetado; `layer_key` sin FK/CHECK por diseño 027).
- `on` = tier `estricto` · `off`/ausente = `estándar` (default de fábrica).
- Cambio de tier = cambio de configuración auditado (SC-006), con valor anterior y nuevo.
- Consumidores: solo backend (validación FR-007, aserción `BASA_AUDIT_FAIL`, consecuencias con grado). El resolutor del motor la ignora (capa desconocida para él, comportamiento 027 verificado).

## Mutaciones sobre datos existentes

| Objeto | Operación | Regla |
|---|---|---|
| `audit_logs` filas vencidas de clases purgables | DELETE por lotes | jamás evidencia de licencias (FR-003, estructural en el clasificador: portón por FORMA) |
| `human_reviews.response_text` vencido (plazo `prompt_content`) | UPDATE → NULL | la fila de review persiste; `audit_log_id` huérfano lógico documentado |
| `licensing/audit_events.py` emisor | refactor de identidad | `SessionLocal` pelado → `tenant_context(None, bypass=True)` (FR-006) |

*(enmiendas aprobadas por el manager 13-ago, la primera REESCRITA el 14-ago)* Dos precisiones sobre esta tabla, las dos por el gate adversarial:

- **Lo que la purga no toca se decide por la FORMA de `guardian_events`, no por la columna `model`** *(dictamen 14-ago: «la exclusión la compra la FORMA, no el literal»)*. La fila es purgable sólo si esa columna prueba que es tráfico: array cuyo primer evento sea un objeto SIN `seq`, SIN `prev_hash` y SIN `event_type` — o la lista vacía, que es el caso mayoritario del producto. La columna `model` no participa: la escribe el cliente (`api/gateway.py:1455`), y una exclusión apoyada en ella deja pedir la inmortalidad desde el body.

  La letra del 13-ago (`model='license'` **y** `seq`) queda derogada: anclar en `seq` habría borrado irreversiblemente las filas de licencia legítimas anteriores a la 021 US5 —la ventana 16→20-jul-2026, con `event_type` y sin `seq`—, que caían en clase mortal por su `compliance_status`. Ver Contrato 1, regla 2.
- La firma real es `tenant_context(tenant_id, bypass=False)` con `tenant_id` posicional (`database.py:65`) — el `tenant_context(bypass=True)` que decía la letra anterior no compila. El `None` significa «este job no es de ningún tenant», que es el motivo del bypass. Ver Contrato 2 (a).

## Estados y transiciones

Fila de auditoría: `viva → vencida (edad > plazo de su clase, reloj DB) → purgada` — sin estado intermedio persistido; «vencida» es un predicado, no una columna.

Quién tiene la transición a `purgada` y quién no lo decide **el portón por FORMA**, no la columna `model` *(dictamen del manager 14-ago; ver Contrato 1, regla 2)*:

- **No la tiene la evidencia de licencias**, y es la excepción permanente. Cubre a los eslabones de la 021 US5 en adelante (`seq` + `prev_hash` + `event_type` en el primer `guardian_event`) **y también** a las filas de licencia legítimas anteriores a la US5 (`event_type`, sin `seq`), que los lectores de la cadena SALTEAN por no ser eslabones legibles (`_is_chain_link` pide `seq` y `prev_hash`) pero que siguen siendo evidencia que no se reconstruye. La protección la da la marca en el primer evento, no el literal de `model`. Esa asimetría —el portón protege un superconjunto de lo que los lectores consideran eslabón— es deliberada y está argumentada en el Contrato 1, regla 2.
- **Tampoco la tienen las formas que el portón no reconoce**: `guardian_events` en SQL `NULL` o JSON `null`, un jsonb que no es lista, un primer evento que no es objeto. No es un limbo accidental, es el fail-closed — «no se pudo demostrar que sea tráfico» no es «es tráfico» — y esas filas se CUENTAN en `filas_no_clasificadas`, también en simulacro (regla 6).
- **Sí la tiene una fila que sólo *dice* `license`.** Verificado contra el clasificador: la columna `model` no entra en el predicado, así que una fila con ese literal y un `guardian_events` de tráfico (típicamente `[]`, que es lo que persiste el producto cuando no se disparó ningún guardián) pasa el portón, cae en la clase que le toque por su `compliance_status` y muere con su plazo. Es tráfico disfrazado: el emisor de la cadena nunca escribió esa forma. **Cambio de comportamiento del 14-ago** — hasta esa fecha una condición aditiva sobre `model` la mantenía inmortal aunque fuera un spoof, y sólo servía para eso.
