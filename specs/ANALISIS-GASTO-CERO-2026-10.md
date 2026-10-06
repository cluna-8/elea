# Análisis: «gasto cero» tras reiniciar el motor — causa, impacto y arreglo (spike)

**Fecha**: 2026-10-06 · **Rama**: `cluna-8/spike-gasto-cero` · **Naturaleza**: spike de lectura. No hay código de
producto, ni spec, ni numeración, ni Docker. Sentinel se leyó **solo lectura**, con `git show`/`git grep` sobre sus refs.
**Origen**: el hallazgo **H5** del ensayo de `specs/ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` §8 (rama
`origin/cluna-8/spike-separar-bases-motor`, commit `f398b1a`): tras reiniciar el motor, el pedido siguiente queda con
`spend=0` en el motor y `audit_logs.cost_usd=0`.

**Convención**: `[verificado]` = lo leí en el código citado (`archivo:línea`) o está medido en el ensayo del 06-oct.
`[no verificado]` = deducido, o requiere el motor corriendo. Las citas del ensayo van como `ensayo:LÍNEA` (líneas del
archivo `ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` de esa rama). Las de Sentinel van como `sentinel@069:ruta:línea`
(ref `069-enmienda-pantalla-modelos`, `29c1c09`).

**Salvedad de versión**: la imagen del motor trae litellm **1.92.0** (`ensayo:83`). No tengo esa versión a mano sin
Docker. Para leer cómo litellm trata el costo usé la **1.98.0** que hay instalada en el entorno virtual de **otro**
proyecto de esta PC (`harness-guardian/.venv/.../litellm`, solo lectura). Esas citas dicen `litellm 1.98` y son
**indicativas**: la conducta puede diferir en 1.92 `[no verificado para 1.92]`.

---

## 0. Resumen

1. **Causa más consistente con la evidencia (H1): la caché de respuestas del motor.** `litellm/config.yaml:20-25` la
   deja activa (`cache: true`, Redis, `ttl: 3600`) y el ensayo repitió **el mismo pedido de 11 tokens** contra el mismo
   Redis. Cuando litellm sirve una respuesta desde caché, **fija el costo en 0** (litellm 1.98) y el logger de Elea
   transporta ese 0 sin marcarlo (`sentinel_audit_logger.py:345,376`). El backend lo acepta tal cual y **no cae a su
   tabla de precios** (`internal.py:294`, `budget_service.py:216`). El patrón del ensayo calza con esto: «primer pedido
   de cada contenido sí cuesta, los repetidos dentro de la hora, no» (§4). **Confianza: media-alta, sin confirmar** con
   el motor corriendo. Lo que falta es una consulta de una columna (`cache_hit`) que el ensayo no hizo, y el stack
   ya se borró (`ensayo:` §8.9).
2. **No es un precio perdido en un reinicio** (H2/H5 de la hipótesis del encargo): los precios viven en el archivo
   `litellm/config.yaml:55-59` horneado en la imagen (`litellm/Dockerfile:8`), no en memoria ni en tabla;
   `LiteLLM_ProxyModelTable` tenía 0 filas (`ensayo:603`); el backend nunca llama `/model/new` (§3.3). Además los tres
   pedidos buenos del ensayo dieron **exactamente** el precio del archivo (§4.2).
3. **Hay un segundo cero, latente y distinto (H3)**: un modelo **sin precio conocido** produce `response_cost=None`,
   y `kwargs.get("response_cost") or 0` (`sentinel_audit_logger.py:345`) lo convierte en `0` **sin distinguirlo** de
   «gratis/cacheado». En el plano de agentes (byok) eso significa presupuesto que no se descuenta; en el chat de la
   consola, en cambio, el mismo caso cae al precio genérico de **$5/$15** (`chat.py:1741`). Dos planos, dos
   respuestas para el mismo hecho. No explica el ensayo (el modelo del ensayo sí tenía precio), pero es la otra forma de
   «gasto cero» que el código permite.
4. **Arreglo mínimo propuesto** (§6): (A) decisión de configuración sin código: `cache: false`, como ya hacen los perfiles
   `camara-comercio` e `itv-examen`; (B) si se conserva la caché, **marcar** el acierto de caché y **separar `None` de
   `0`** en el logger, ambos cambios genéricos y retrocompatibles para portar a Sentinel.
5. **La 057 no lo arregla** (§7): trae precio por entrada del catálogo, que resuelve «modelo servido por comodín sin
   precio» (el cero de la 069-S1), no el cero por caché. Pero sí **toca la caché** (su FR-034 de la 068), así que es
   el lugar natural para decidir la política.
6. **Experimento** (§8) listo para correr con la compuerta del owner: ~12 pedidos, ≈ 3×10⁻⁴ USD, stack aislado.

---

## 1. Lo que se sabe del síntoma (evidencia del ensayo)

| Dato | Fuente |
|---|---|
| Modelo `azure-gpt-5.4-mini`, prompt «Responde solo: ok», 11 tokens de entrada y 4 de salida, ≈ 2,6×10⁻⁵ USD por pedido | `ensayo:326` |
| Siembra (directo al motor, llave `svc.tabular`) y V0 (`/gw`, 0,83 s): ambos suman `2.625e-05`; panel con `cost_usd 0.000026` | `ensayo:341,364-365` |
| V1 (tras reiniciar): HTTP 200, **gasto de la llave sin cambios**; fila nueva de `LiteLLM_SpendLogs` con `spend=0` y modelo `gpt-5.4-mini` (las dos filas buenas decían `azure/gpt-5.4-mini`); `audit_logs.cost_usd=0.00000000` | `ensayo:454` |
| Idéntico tras la vuelta atrás (V2, base compartida) y en el accidente Vx (motor sobre base sin llaves) | `ensayo:454,408,466` |
| **No** pasa en V3 (instalación nueva, primer arranque, Redis nuevo): gasto 2.625e-05 y `cost_usd 0.000026` | `ensayo:561` |
| `LiteLLM_ProxyModelTable` con 0 filas; la config declara costos | `ensayo:603` |
| El gasto por llave se vuelca por lotes (~60–70 s); el ensayo esperó 70 s antes de leer | `ensayo:343` |
| El ensayo reinició **solo `engine`** (`docker compose up -d engine`); `redis` no se recreó | `ensayo:` §8.3.4 `[verificado por los comandos; no por el uptime del contenedor]` |

El ensayo atribuyó el patrón a «tras un reinicio del motor», pero **reinicio y repetición del pedido van juntos en
todas las fases malas** (Vx, V1, V2 repiten el prompt de V0) **y la única fase buena posterior a V0 es la que arrancó
con Redis nuevo** (V3). El ensayo no tiene un pedido con prompt *distinto* tras un reinicio: ahí está la confusión
entre las dos hipótesis. `[verificado que están confundidas; no verificado cuál es la causa]`

---

## 2. Cómo viaja el costo (la cadena, con líneas)

```
motor (litellm) ──response_cost──▶ logger Elea ──POST /internal/audit──▶ backend ──▶ budgets / audit_logs / costos
```

1. **Motor**: calcula `response_cost` por pedido. En litellm 1.98 un acierto de caché fija `0.0`
   (`litellm_core_utils/litellm_logging.py:1831-1832`, `:2629-2630`; `cost_calculator.py:1770-1771`) y escribe la fila de
   gasto con `spend=kwargs.get("response_cost", 0)` y `cache_hit='True'`, con un `request_id` terminado en `_cache_hit…`
   (`proxy/spend_tracking/spend_tracking_utils.py:380-383,401,411`). `[verificado en litellm 1.98; no verificado en 1.92]`
2. **Logger de Elea**: `cost = kwargs.get("response_cost") or 0` (`litellm/extensions/sentinel_audit_logger.py:345`) →
   `"cost_usd": float(cost)` (`:376`). **No lee `cache_hit`** (no hay ninguna referencia en el archivo, `grep` sin
   resultados). `None` y `0.0` salen iguales. `[verificado]`
3. **Backend, plano de agentes (byok)**: `AuditEntry.cost_usd: float = 0.0` (`backend/src/api/internal.py:242`);
   `_acumular_gasto` corta solo si **no hay** costo ni tokens (`:285`) y pasa `override_cost=Decimal(str(entry.cost_usd or 0))`
   (`:294`). `update_budget` usa el override **si no es `None`** (`budget_service.py:216`): un `Decimal(0)` **gana** y no
   se consulta `MODEL_PRICING`. Efecto: `current_spend_usd += 0` (`:228`) pero `current_tokens += total_tokens` (`:230`).
   `[verificado]`
4. **Backend, plano del chat de la consola**: lee el header `x-litellm-response-cost` (`chat.py:1535`); si viene con
   texto, lo parsea (`:1587`) y **ese valor, aunque sea 0, desplaza el fallback**: `cost = actual_cost if actual_cost is
   not None else BudgetService.calculate_cost(...)` (`:1741`; `actual_cost` arranca en `None`, `:1436`). Solo cae a
   `MODEL_PRICING` si el header falta o no parsea. `[verificado el código; no verificado qué header manda el motor en un
   acierto de caché]`
5. **Lo que se lee después**: el panel de costos suma `audit_logs.cost_usd` (`backend/src/api/costs.py:113-135`); el tope
   de la llave se aplica contra **nuestra** tabla `budgets`, no contra el gasto del motor (`litellm/extensions/custom_auth.py:120-126`:
   «presupuesto de NUESTRA tabla `budgets` … `max_budget` es siempre NULL»). O sea que **el gasto que cuenta es el que
   pasa por el punto 3, y ahí el cero no tiene red de seguridad**. `[verificado]`

---

## 3. Hipótesis, ordenadas por evidencia

### H1 — Caché de respuestas del motor (Redis) → costo 0. **Más consistente.**

**A favor**

- Está activa en este repo: `litellm/config.yaml:20` (`cache: true`) y `:21-25` (Redis, `ttl: 3600`); `docker-compose.yml:93`
  pasa `REDIS_HOST` al motor; desde el **30-jun-2026** (`0e71e37`) y nunca se tocó (`git log -G'^  cache: '` sobre el
  archivo: un solo commit). La imagen publicada **hornea ese archivo** (`litellm/Dockerfile:8`; `ensayo:82` dice que las dos
  capas finales son `COPY config.yaml` y `COPY extensions/`). `[verificado el repo; no verificado que la config **dentro**
  de la imagen del ensayo tenga `cache: true` → es el paso E0 del experimento]`
- Lo confirma otra spec: `specs/057…/spec.md:79` (rama `origin/cluna-8/057-plan`) anota «la caché de respuestas del motor
  está activa en Redis (`litellm/config.yaml:19-25`)» y `specs/024-unmask-bridged-routes/research.md:92` la describe
  sirviendo «la MISMA respuesta (mismo id)» a pedidos distintos.
- El costo de un acierto de caché **es 0 por diseño** del motor (§2.1).
- Calza el patrón de modelo: las filas de cero dicen `gpt-5.4-mini` (sin `azure/`) y las reales `azure/gpt-5.4-mini`
  (`ensayo:454`); una respuesta servida de caché lleva el `model` de la respuesta original, no el del deployment
  `[no verificado: deducción; el ensayo no guardó `cache_hit` ni `request_id`]`.
- Calza el patrón de fases: Vx, V1 y V2 repiten el pedido de V0 sobre el **mismo Redis** (solo se reinició `engine`);
  V3 arrancó con volúmenes nuevos, o sea Redis vacío, y **sí** cobró. `[verificado el patrón]`
- Calza que el cero llegue **también** a `audit_logs.cost_usd` en Vx, donde la base no tenía llaves
  (`ensayo:408`): ese valor sale del logger (§2.2), no de la base de gasto de la llave.

**En contra / huecos** (honestos)

- **V0 no fue un acierto** aunque la siembra (chat directo) llevaba el mismo texto. Debería explicarse porque la clave de
  caché cambia con el cuerpo: el `/gw` entra por formato Anthropic (`gateway.py:1559,1636`) y no es el mismo cuerpo que el
  `chat/completions` de la siembra. `[no verificado]`
- **Ventana de 1 h**: V0 fue antes de las 06:40 UTC (empieza el accidente, `ensayo:406`) y V1/V2 vinieron después de
  las 07:00. Si V2 cayó más de 3600 s después de V0, la clave ya habría vencido (un acierto no la renueva). El orden de
  los tiempos exactos **no está en el ensayo** y el stack se destruyó. `[no verificado]` Es la grieta más seria de H1.
- La latencia no discrimina: V1 1,94 s y V2 1,53 s contra 0,83 s de V0 (`ensayo:454,466`), pero tras reiniciar el motor
  todo está frío. `[inconcluso]`

### H2 — Precios que viven en memoria o en la base del motor y se pierden al reiniciar. **Descartada para este caso.**

- Los precios son **archivo**: `litellm/config.yaml:55-59` (`azure-gpt-5.4-mini`: `0.00000075` / `0.0000045`), `:46-49`
  (`azure-gpt-5.1-chat`), `:70-73` (embeddings en 0 a propósito), horneados en la imagen (`Dockerfile:8`). `[verificado]`
- No hay precio en tabla: `general_settings` no define `store_model_in_db` (`litellm/config.yaml:1-8`; `grep -rn
  store_model_in_db` solo encuentra un comentario en `ai_engine_client.py:218`), el backend **no llama** `/model/new`,
  `/model/update` ni `/model/delete` (`grep` en `backend/src`: cero resultados; solo `/model/info`, de lectura:
  `chat.py:2486`, `costs.py:66,87`), y `LiteLLM_ProxyModelTable` tenía 0 filas (`ensayo:603`). `[verificado]`
- El precio **estaba aplicando** antes del reinicio: `11 × 7,5×10⁻⁷ + 4 × 4,5×10⁻⁶ = 8,25×10⁻⁶ + 1,8×10⁻⁵ = 2,625×10⁻⁵`,
  exactamente el `2.625e-05` del ensayo (`ensayo:364`). `[verificado: la cuenta]`
- Incluso sin `model_info`, el mapa interno de litellm trae `azure/gpt-5.4-mini` con los mismos 7,5×10⁻⁷ / 4,5×10⁻⁶
  (`model_prices_and_context_window_backup.json`, litellm 1.98 `[indicativo]`). Perder `model_info` no daría 0 para este modelo.

### H3 — Un modelo sin precio conocido → `None` → `0` silencioso (**latente, plano de agentes**). **Real en el código, no probada en vivo.**

- Hay un deployment sin `model_info`: `azure-gpt-4o-mini` (`litellm/config.yaml:34-39`); depende del mapa de litellm (en
  1.98 existe como `azure/gpt-4o-mini`, 1,65×10⁻⁷ / 6,6×10⁻⁷ `[indicativo]`; en 1.92 `[no verificado]`).
- Un cliente que registre un deployment de Azure **con nombre propio** (p. ej. `azure/mi-despliegue`) sin `model_info`
  ni `base_model`: litellm calcula con el `model` que devuelve la respuesta (`cost_calculator.py:770-775`, litellm 1.98),
  y si ese nombre no está en el mapa, `response_cost` queda `None` (`litellm_logging.py:2642-2644`). `[verificado el código
  en 1.98; no verificado el caso real]`
- Entonces **plano de agentes**: `None or 0` → `0` (`sentinel_audit_logger.py:345`) → `Decimal(0)` gana (`internal.py:294`,
  `budget_service.py:216`) → el presupuesto en USD **nunca se agota**. **Plano del chat**: sin header válido, el pedido cae a
  `MODEL_PRICING["default"]` = **$5/$15** (`budget_service.py:53-62` y warning en `:197-202`; `chat.py:1741`) →
  sobrefactura de 1,5× a 6,7× como la de la 053 (`budget_service.py:43-49`). `[verificado el código]`
- El comentario de `budget_service.py:44-49` ya declara que `MODEL_PRICING` es solo el respaldo del camino sin header; la
  asimetría entre planos **no figura** en ninguna parte.

### H4 — Caché de precios de litellm que no se recarga. **Descartada como causa; sin efecto en reinicio.**

- litellm baja el mapa de costos de la red al arrancar y cae al incluido en el paquete si no hay salida
  (`litellm_core_utils/get_model_cost_map.py:158-166,287`, litellm 1.98; `LITELLM_LOCAL_MODEL_COST_MAP=true` lo fuerza
  local). `docker-compose.yml` y los `.tmpl` **no** definen esa variable (`grep`: sin resultados). `[verificado el repo;
  indicativo litellm]`
- Reiniciar **recarga** el mapa, no lo congela; y para los deployments con `model_info.*_cost_per_token` explícito el
  mapa ni se consulta (precio personalizado, `cost_calculator.py:756-768`). No puede explicar un cero en un deployment que
  trae su precio en el archivo. `[verificado el código 1.98]`

### H5 — Precio personalizado en una tabla que el reinicio o el «baseline» reescribe. **Descartada.**

- El mecanismo de «baseline» (`P3005`) existe y **sí destruye** tablas ajenas (`ensayo:` §8.4, caso destructivo
  reproducido), pero afecta las tablas **del backend** (`users`, `audit_logs`…), no precios: no hay precios en tablas
  (H2). En Vx el baseline reconstruyó `elea_engine` y el motor siguió con costos en cero **sin** haber perdido ningún
  precio, porque no tenía ninguno guardado (`ensayo:408`). `[verificado]`
- Consecuencia útil: **Vx no distingue** entre «caché» y «sin llave a la que sumar»: la causa de su `cost_usd=0` es la
  misma que la de V1 (H1) o es un efecto de la ausencia de la fila de la llave; el ensayo no lo separó (`ensayo:408`).

### H6 — El volcado por lotes del gasto (`ensayo:343`). **Descartada como causa del `cost_usd`.**

Explica por qué `LiteLLM_VerificationToken.spend` se ve ~70 s tarde, **no** por qué `audit_logs.cost_usd` sale 0: ese valor
no pasa por el lote, lo emite el logger por HTTP en el mismo pedido (§2.2-2.3). `[verificado]`

---

## 4. El patrón del ensayo, contra H1

### 4.1 Predicciones de H1 vs. las de «reinicio»

| Situación | H1 (caché) | «Pérdida al reiniciar» |
|---|---|---|
| Mismo prompt, **sin** reiniciar, 2.º pedido | **cero** | normal |
| Prompt **distinto**, tras reiniciar | **normal** | cero |
| Mismo prompt tras reiniciar, **con Redis vaciado** | normal | cero |
| Mismo prompt tras reiniciar, Redis intacto, dentro de 1 h | cero | cero |

El ensayo solo cubrió la última fila (más la fila «Redis nuevo» en V3, que da normal). La tabla es el diseño del
experimento de §8.

### 4.2 Aritmética del precio

Los dos pedidos buenos y el panel dan `2.625e-05` / `0.000026` (`ensayo:364-365`) = precio de `litellm/config.yaml:57-58`
× 11 y 4 tokens. Es la prueba más barata de que el precio **estaba aplicado** al principio. `[verificado]`

---

## 5. Impacto y desde cuándo

**Qué se descuenta mal, y qué no** `[verificado el código; la magnitud en producción, no]`

| Superficie | Efecto de un cero en el costo | Dónde |
|---|---|---|
| **Presupuestos** (agentes/byok) | `current_spend_usd` no sube, `current_tokens` **sí** sube: el tope en USD nunca se alcanza, el de tokens sí. Un presupuesto «en USD» deja de proteger justo en tráfico repetido. | `budget_service.py:216,228,230`; `internal.py:285-294` |
| **Reportes de costo** | `SUM(cost_usd)` subestima; fila con tokens > 0 y costo 0 que **no cierra** con ninguna tarifa | `costs.py:113-135` |
| **Auditoría** | La fila es metadata correcta (tokens, modelo, latencia) pero **no dice** que fue un acierto de caché; imposible reconciliar o auditar el cero | `sentinel_audit_logger.py:359-376` |
| **Gasto por llave del motor** | Igual de bajo, pero **no se usa** para el tope (`custom_auth.py:120-126`) | `ensayo:454` |
| **Chat de la consola** | Depende de qué header mande el motor en un acierto de caché `[no verificado]`; si manda `0.0`, mismo cero; si no manda nada, **sobrecobra** a $5/$15 | `chat.py:1535,1587,1741` |

**Nota de honestidad**: un acierto de caché **no le cuesta nada al proveedor**, de modo que «0 USD» es, en cierto sentido,
cierto. El defecto no es el 0: es que (a) el sistema **no lo dice** (no hay marca), (b) el presupuesto de tokens y el de
USD pasan a medir cosas distintas, y (c) el mismo hecho se traduce distinto en los dos planos. Hay además un efecto
**económico** de política: quien decida que el tenant debe pagar el pedido repetido (lo que costaría sin caché) no puede
hacerlo con el dato actual.

**Desde cuándo** (cadena de fechas del código, `git log -S`/`-G`):

| Fecha | Hecho | Commit |
|---|---|---|
| 2026-06-29 | Chat lee `x-litellm-response-cost` | `1092bb8` |
| **2026-06-30** | **`cache: true` + Redis en `config.yaml`** | `0e71e37` |
| 2026-07-28 | El plano de agentes empieza a **acumular** gasto con el costo del evento (`override_cost`) | `e21a686` |
| 2026-08-31 | `model_info` con precios de los dos deployments propios | `484b5a9` |
| 2026-10-06 | El cero se observa por primera vez (ensayo) | `f398b1a` |

**Exposición teórica**: desde el **28-jul-2026** para cualquier instalación que corra `litellm/config.yaml` tal cual. Los
perfiles de cliente `camara-comercio` y `itv-examen` **no están expuestos a H1**: `cache: false`
(`deploy/clients/camara-comercio/config.yaml.tmpl:21`, `deploy/clients/itv-examen/config.yaml.tmpl:24`, ambos «issue #30»);
`deploy/clients/example/config.yaml.tmpl:20` sí tiene `cache: true`. **Incidencia real en el servidor de Elea: no
verificada** (no se accedió; ver §9). **Colateral que conviene mirar** (no es de este spike): la clave de caché es el
contenido y no menciona tenant/llave (`specs/024…/research.md:92`); entre tenants distintos, un acierto sirve una respuesta
ajena `[no verificado en 1.92]`.

---

## 6. Arreglo propuesto (mínimo, genérico, retrocompatible)

Todo es **base** (backend/litellm): se escribe sin strings de Elea/Eleia para portar a Sentinel, que tiene el **mismo**
código (`sentinel@069:litellm/extensions/sentinel_audit_logger.py:350`, `cost = kwargs.get("response_cost") or 0`) y la
misma config (`sentinel@069:litellm/config.yaml:60`, `cache: true`). Si se aprueba, el cambio de base vuelve por
`HANDOFF-elea-a-sentinel.md`, no por coordinación directa.

### A. Decisión, sin código (la más barata)

`litellm_settings.cache: false` en `litellm/config.yaml:20`, **igual que** los perfiles con piloto (`config.yaml.tmpl:21`/`:24`).
Elimina H1 de raíz **y** el problema de placeholders ajenos del issue #30 (`docs/docs/integrations/gotchas.md:137-139`).
Costo: se pierde el ahorro de pedidos idénticos; hay que **decirlo** (spec 012/023 hablan de ahorro). La decide el owner:
es una compuerta de producto, no técnica.

### B. Si se conserva la caché: dejar de tragarse el dato (código pequeño, TDD)

1. **Marcar el acierto** en el logger (`sentinel_audit_logger.py`, cerca de `:345`): leer `kwargs.get("cache_hit")` y
   sumarlo como booleano **metadata-only** al evento. En el backend, `AuditEntry` (`internal.py:218-250`) acepta un
   campo **opcional** `cache_hit: bool = False` (retrocompatible: el motor viejo no lo manda). Dónde se persiste es una
   decisión de spec: `routing_decision` JSON ya existe (`backend/src/models/audit.py:47`) y evita migración; una
   columna sería migración con id por hash. No contiene texto de prompt ni PII.
2. **Separar `None` de `0`**: `cost = kwargs.get("response_cost")`; si es `None` **con tokens > 0**, emitir `cost_usd=None`
   (o un campo `cost_missing=true`). En el backend, `_acumular_gasto` pasa `override_cost=None` en ese caso, para que
   `update_budget` caiga a `calculate_cost` (que ya deja el `logger.warning` de `budget_service.py:197-202`). Resultado:
   **mismo comportamiento que el chat** para un modelo sin precio, y el cero real (caché, modelo local) sigue siendo cero.
3. **Tests** (TDD, sin Docker): (a) logger con `response_cost=None` y tokens > 0 → evento sin `cost_usd`; (b) con `0.0` y
   `cache_hit=True` → `cost_usd=0` y marca; (c) `/internal/audit` sin costo → `update_budget` con precio de respaldo;
   (d) con `cost_usd=0.0` explícito → no cae al respaldo (no regresiona el ahorro por caché ni el modelo local).

### C. Sin hacer en este arreglo (a propósito)

- No tocar `MODEL_PRICING` (ya espejado con la config, `budget_service.py:42-62`).
- No hacer que un acierto de caché «cobre» el pedido: es política de producto; B solo deja el dato para decidirla.
- Documentación (`docs/docs/**`): si B o A se implementan, la página de la caché del motor
  (`docs/docs/integrations/gotchas.md:137`, `modelo-propio.md:88`) y la de costos deben decir en qué plano un acierto cuenta
  0 y cuál es el criterio; con leyenda 🟢/🟡/🔵 honesta (hoy 🟡). Es parte de la Definition of Done de la feature.

**Tamaño**: A es una línea; B ≈ 15-25 líneas de producción + 4 tests. Ninguno cambia API pública ni `.env.example`
(`make -C deploy docs-refs` solo si se agrega el campo opcional al contrato interno y este se publica `[no verificado]`).

---

## 7. Relación con la 057 y cómo calcula el costo Sentinel (solo lectura)

### 7.1 Cómo costea Sentinel un destino (069)

| Qué | Dónde (`sentinel@069`) |
|---|---|
| La entrada del catálogo guarda precio **por token**: `price_input`, `price_output`, `price_source`, `price_at` | `sentinel/catalog/models.py:104-107` |
| Se convierte a USD/millón al armar el destino | `sentinel/catalog/store.py:123-128` |
| **El guard inyecta el precio en cada pedido** (`input_cost_per_token`/`output_cost_per_token`), quitando antes cualquiera que mande el cliente | `sentinel/engine/redirect_catalog.py:121-130`; `redirect_credentials.py:85-88` |
| Jerarquía: precio de la entrada → mapa del motor (por prefijo del proveedor) → **ninguno** | `redirect_credentials.py:107-124` |
| La fuente (`destination`/`engine_map`/`none`) queda en la decisión auditada | `redirect_catalog.py:131-133` |
| Por qué: **«sin precio el motor registra costo 0 para lo servido por comodín y el presupuesto no se descuenta»** | `redirect_credentials.py:111-112`; `spike-s1.md` hallazgo 1 y fila (d): 18 pedidos de ~35 000 tokens con `cost_usd=0` |

### 7.2 Qué difiere del motor de Elea

| | Elea (hoy) | Sentinel (069 / 057) |
|---|---|---|
| Dónde vive el precio | **Estático**, por deployment, en `model_info` de `config.yaml` (`:46-49`, `:56-59`), horneado en la imagen | **Dato** en `ext_catalog_entry`, editable en la consola, inyectado **por pedido** |
| ¿Se puede perder en un reinicio? | No (archivo) | No (tabla del catálogo, no del motor) |
| Modelo sin precio | `None→0` silencioso en agentes; $5/$15 en el chat | El guard **sabe** que no hay precio y lo registra como `pricing: none`; no queda mudo |
| Cero por caché de respuestas | **Sí** (H1) | **Igual de expuesto**: misma config (`cache: true`) y mismo logger; la 069 no lo trata |
| Cambiar un precio | Redesplegar imagen | Editar la entrada (cambio de precio queda registrado, `admin.py:472`) |

### 7.3 Lo que la 057 resuelve y lo que no

- **Resuelve** el cero de «destino sin precio»: la 057 trae el subconjunto 069 (catálogo) con `price_input/price_output`
  por entrada (`specs/057…/spec.md:16-17,87`; `data-model.md` §3) y el guard de la 069. Sirve contra H3 **para los destinos
  del catálogo**; los `model_list` fijos del archivo (los tres deployments actuales) siguen como hoy.
- **No resuelve** H1: la caché de respuestas queda como está. El `price_cache_read`/`price_cache_write` de su data-model
  (`data-model.md` §3 y §4, FR-046) es la **caché del proveedor** (tokens de prompt cacheados), otro concepto: no confundir
  «caché del proveedor» (se cobra a otro precio) con «caché de respuestas del motor» (no se cobra).
- **Toca la caché igual**: su fila 13 (`spec.md:79`) la registra como activa, y la 068 exige que la caché **no sirva a un
  pedido una respuesta de otro destino ni con otro mapa de enmascarado** (`sentinel@069:specs/068…/spec.md:500`, FR-034). Con
  la 057 el motor tendrá varios destinos por nombre público: es probable que haya que acotar o apagar la caché de
  todos modos. **Conviene decidir A/B acá, una sola vez, antes que dentro de la 057.** `[no verificado]` qué hace hoy la
  clave de caché con el destino reescrito.
- **Recomendación para la 057**: heredar de Sentinel la **fuente de precio auditada** (`destination|engine_map|none`) y
  agregar un aviso (log/contador) cuando sea `none`, para que el «cero» de H3 no sea mudo en los destinos del catálogo.

---

## 8. Experimento de confirmación (con Docker; **requiere la compuerta del owner**)

**No se corrió.** Es el diseño exacto para una sesión posterior. Modelo y costos como en `ensayo:326`: ~12 pedidos de
11 tokens ≈ 3×10⁻⁴ USD de crédito real. Todo en un **stack aislado** (mismo método que `ensayo:` §8.0), nada de otros
proyectos del demonio.

**Preparación**

```
COMPOSE_PROJECT_NAME=gcero  STACK_PREFIX=gcero   # contenedores gcero-*, backend en 18092
# compose del instalador copiado, con solo: container_name elea-… → gcero-… y "8091:8000" → "18092:8000"
docker compose up -d db redis nlp-analyzer engine  &&  esperar healthy (~77 s, primer arranque)
docker compose up -d backend
# datos de prueba: login admin, usuario + llave claude-code y una llave svc.* por la API, como install.sh
# Credenciales de Azure: solo del .env local externo; no se imprimen ni se copian al repo.
```

El motor de la imagen no trae `curl` (`ensayo:341`): los pedidos salen con `docker exec gcero-engine python3` y `urllib`
(la llave por variable de entorno del exec, sin imprimirla). Cada pedido guarda **status, tiempo y los headers
`x-litellm-response-cost`, `x-litellm-cache-key`, `x-litellm-call-id`**.

| Paso | Qué hacer | Qué predice **H1** | Qué predice «reinicio» |
|---|---|---|---|
| **E0** | `docker run --rm --entrypoint cat elea-guardian-engine:latest /app/config.yaml \| grep -n -A6 cache` y `docker exec gcero-engine python3 -c "import importlib.metadata as m; print(m.version('litellm'))"` | `cache: true` en la imagen; versión 1.92.0 | — (cierra el hueco de §3.H1) |
| **E1** | **Sin reiniciar**: R1 (prompt P) → R2 (mismo P, misma llave) → R3 (prompt P′ distinto, p. ej. con un sufijo único) | R1 > 0; **R2 = 0**; R3 > 0 | R2 normal |
| **E2** | `docker compose restart engine` → R4 (P′′ nuevo, jamás visto) → R5 (repetir P de E1) | **R4 > 0**; R5 = 0 (si Redis conserva la clave y estamos < 3600 s) | **R4 = 0** |
| **E3** | `docker compose exec redis redis-cli FLUSHALL` (**solo** en este stack) → R6 (repetir P) | R6 > 0 | R6 = 0 |
| **E4** | Pedido con caché desactivada por pedido (`"cache": {"no-cache": true}` en el cuerpo) repitiendo P | > 0 | = 0 |
| **E5** | Config alternativa con `cache: false` (montada sobre `/app/config.yaml`, sin reconstruir) → repetir P dos veces | ambos > 0 | ambos = 0 |

**Qué leer después de cada bloque (esperar > 70 s, `ensayo:343`)**

```sql
-- motor
SELECT request_id, model, spend, cache_hit, "startTime"
  FROM "LiteLLM_SpendLogs" ORDER BY "startTime";
-- backend (metadata-only)
SELECT timestamp, model, prompt_tokens, completion_tokens, cost_usd FROM audit_logs ORDER BY timestamp;
SELECT current_spend_usd, current_tokens FROM budgets;   -- si hay presupuesto sobre el usuario de prueba
```

- **Confirma H1** si R2, R5 tienen `cache_hit='True'`, `request_id` con `_cache_hit`, `spend=0`, modelo sin `azure/`; y R3, R4, R6
  cuestan. **Refuta H1** (y deja el reinicio como causa) si R4 sale 0 con prompt nuevo.
- **E5 cierra la discusión**: con `cache: false` el patrón del ensayo no puede reaparecer.
- **E6 opcional (H3, asimetría de planos)**: copia de la config con un deployment cuyo `model_info.base_model` apunte a un
  nombre **que no está** en el mapa de litellm y sin precio. Esperado: motor con `response_cost=None`; `audit_logs.cost_usd=0`
  y `budgets.current_spend_usd` sin moverse (plano de agentes), mientras el chat de la consola factura a $5/$15.
- **E7 opcional (header del chat en un acierto)**: repetir P por el chat de la consola (no por `/gw`) y registrar qué
  `x-litellm-response-cost` devuelve el motor; resuelve la fila «Chat de la consola» de §5.

**Limpieza**: igual que `ensayo:` §8.9 — `docker compose down -v` solo del proyecto `gcero`, `.env` y claves con `shred`,
`docker ps -a`/`volume ls`/`network ls` antes y después. **Criterio de parada**: si E1 ya muestra R2 = 0 y R3 > 0, H1
está confirmada sin reiniciar nada; E2 y E3 son para sellarla.

---

## 9. No verificado (todo lo que sigue es una pregunta abierta, no un hallazgo)

1. **Que la caché sea la causa.** H1 es la hipótesis más consistente, no una causa probada. El ensayo no registró
   `cache_hit` ni `request_id` y el stack se borró. Se confirma con el experimento (§8, E1–E3).
2. **Que la imagen publicada lleve `cache: true`.** Se verificó el repo (`litellm/config.yaml:20`) y que la imagen hornea
   ese archivo, no su contenido real (E0).
3. **La ventana de 3600 s** entre V0 y V2 del ensayo: no hay tiempos para reconstruirla (§3.H1).
4. **Por qué V0 no fue acierto** si la siembra llevaba el mismo texto: se supone una clave de caché distinta por el cuerpo
   que arma el `/gw`, no se midió.
5. **Todo lo de litellm 1.98** (`cache_hit→0`, `_cache_hit` en `request_id`, `None` en modelo desconocido, mapa de costos) vale
   para **1.92.0** (la imagen) solo si no cambió entre versiones.
6. **Qué manda el motor en `x-litellm-response-cost` en un acierto de caché** y por tanto qué hace el chat de la consola.
7. **La incidencia en el servidor de Elea**: si reinicia el motor, si su config lleva `cache: true`, si hay ya filas con
   `cost_usd=0` y tokens > 0 repetidas. Consulta de diagnóstico para el owner (solo lectura):
   `SELECT date_trunc('day', timestamp) d, count(*) FILTER (WHERE cost_usd=0 AND prompt_tokens>0) AS ceros, count(*) FROM
   audit_logs GROUP BY 1 ORDER BY 1;` — daría la magnitud y la fecha real de inicio. `[no corrida]`
8. **H3 en vivo**: no se probó un deployment sin precio ni la asimetría entre planos; es lectura de código.
9. **Aislamiento entre tenants de la caché** (colateral de §5).
10. **El efecto de la 057 sobre la clave de caché** (§7.3) y si `make -C deploy docs-refs` haría falta (§6.C).
11. **Qué hace Sentinel** más allá de lo leído: solo se leyó la rama `069-enmienda-pantalla-modelos` por `git show`; no
    se ejecutó nada y no se miró si su motor de producción reinicia con el mismo patrón.

---

## Apéndice: evidencia leída (comandos, sin salida de secretos)

- Repo: `litellm/config.yaml`, `litellm/Dockerfile`, `litellm/extensions/sentinel_audit_logger.py`, `custom_auth.py`;
  `backend/src/api/{internal,chat,costs,gateway}.py`, `backend/src/services/{budget_service,ai_engine_client}.py`;
  `deploy/clients/*/config.yaml.tmpl`, `deploy/docker/compose.prod.yml`, `docker-compose.yml`.
- Historia: `git log -S/-G` sobre los mismos archivos (fechas de §5).
- Ensayo: `git show origin/cluna-8/spike-separar-bases-motor:specs/ANALISIS-SEPARAR-BASES-MOTOR-2026-10.md` (§8).
- 057: `git show origin/cluna-8/057-plan:specs/057-porte-sentinel-068-redireccion-modelos/{spec,data-model}.md`.
- Sentinel (solo lectura): `git show`/`git grep` sobre `069-enmienda-pantalla-modelos` (`catalog/models.py`, `catalog/store.py`,
  `engine/redirect_{catalog,credentials}.py`, `specs/069…/spike-s1.md`, `specs/068…/spec.md`) y su `litellm/config.yaml`.
- litellm 1.98.0 (copia ajena, solo lectura): `cost_calculator.py`, `litellm_core_utils/{litellm_logging,get_model_cost_map}.py`,
  `proxy/spend_tracking/spend_tracking_utils.py`, `model_prices_and_context_window_backup.json`.
