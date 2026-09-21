# Specs de Eleia — índice

**Eleia es el perfil de país de Argentina** sobre Guardian Secure. Tres niveles, según
**ADR-0007** (`guardian-secure`, `docs/adr/0007-localizaciones-como-perfiles-de-pais.md`):

| Nivel | Qué es | Quién |
|---|---|---|
| **Base** | El producto genérico: firewall, motor, enmascarado, auditoría, licensing, metodología | `guardian-secure` |
| **Localización** | El **perfil de país**: normativa aplicable, entidades de PII/NLP, idioma, precios | Sentinel = Europa · **Eleia = Argentina** |
| **Instalación** | Un cliente concreto: marca, seed, catálogo de modelos, superficies | `deploy/clients/<slug>` |

Se dice **"perfil de país"** y no "policy pack" porque tiene referente en el código: el perfil de
enmascarado se llama `latam_ar` y así lo trata la [spec 016](016-real-nlp-masking/).

**El perfil de país NO es este repositorio.** [ADR-0001](../docs/adr/) sigue vigente ("queda
prohibido crear ramas o forks por país"), y que hoy Eleia y Sentinel sean repos separados es
**deuda declarada con plan de salida**, no doctrina. El plan vive en la spec
`050-convergencia-localizaciones` de `guardian-secure`; la deuda se revisa cuando cierre su fase 1
o el **15-dic-2026**, lo que pase primero.

El argumento más fuerte contra el repo-por-país es que **la localización ya está implementada más
fina de lo que un fork puede dar**: `SENTINEL_ENTITY_REGION` es sólo el default de arranque de la
instalación, y la fuente canónica es **por tenant** — `pii_masking.config.region` la pisa
(documentado en [`docs/docs/api-reference/configuration.md:57`](../docs/docs/api-reference/configuration.md),
spec 016, issues 137/141). Una sola instalación puede servir a la vez a un tenant argentino y a uno
español con detectores distintos. Un fork no da esa granularidad.

> **Numeración de specs** (ADR-0007): las specs **001-038** son las mismas en los dos repos
> —están en los 524 commits de historia común— y van **sin prefijo**. De la **039 en adelante**
> divergen: se referencian como `ELEIA-0xx` / `SENTINEL-0xx`.

> ⚠️ **Numeración de MIGRACIONES: el mismo problema, sin convención todavía, y falla más feo.**
> Nuestras revisiones de Alembic usan ids secuenciales (`revision = "018"`, `down_revision = "017"`)
> y las tres líneas consumen ese contador por separado: base, Sentinel (head `021`) y Eleia
> (head `020`). Dos revisiones con el mismo id en el mismo directorio **no arrancan** — no es un
> conflicto de texto, Alembic no levanta.
>
> Ya pasó una vez: el PR [guardian-secure#345](https://github.com/cluna-8/guardian-secure/pull/345)
> proponía una migración `018` para la base, y la nuestra —`018_workspaces_service_accounts_audit_surface`,
> specs 043/044— ya ocupa ese id. Se detectó antes del merge y allá la cambiaron por un hash
> (`fd25cc8bcb94`), que es lo que Alembic genera solo cuando no se le pide lo contrario.
>
> **Para la próxima migración de esta línea: no usar `021`** — Sentinel ya lo tiene aplicado en
> producción. Usar el hash que genera `alembic revision`. Renumerar lo ya aplicado **no** es
> opción: `alembic_version` guarda el id en cada base instalada, incluida la de Elea.
>
> La política de fondo la decide Cristian; está planteada como paralelo de ADR-0007.

Esta carpeta tenía 44 specs sin ningún criterio visible y 332 casillas sin marcar, de las que la
mayoría no era trabajo pendiente. Reorganizada el **15-sep-2026**; acá está el criterio.

## Cómo leer esta carpeta

| Carpeta | Qué contiene | ¿Sus tareas son backlog? |
|---|---|---|
| `0xx-*` en la raíz | Specs vigentes: la línea Eleia (040+) y la base compartida (001-039) | Sí, con el matiz de abajo |
| [`_retiradas/`](_retiradas/) | Specs que ya no describen el sistema (absorbidas o superadas) | **No** |
| [`_no-aplica-eleia/`](_no-aplica-eleia/) | Funcionalidad de la base que no vive en este repo | **No** |

**Importante:** una spec en la raíz no significa "trabajo comprometido". Las de la base
(`001-039`) llegaron con el fork y su backlog es del producto base, no el plan de Eleia. Los
números están separados más abajo.

---

## 1. Línea Eleia — el backlog real

Lo único que hay que mirar para saber qué falta en Eleia.

| Spec | Estado | Pendiente |
|---|---|---|
| [040 Cliente RAG de Elea](040-cliente-rag-elea-completo/) | Entregada | **0** — el hallazgo del CBU se cerró el 31-ago y se verificó el 15-sep (patrón presente, perfil `latam_ar` activo en el contenedor). Ver el gap adyacente en §3. |
| [042 Rediseño UI bóveda/PII/hilos](042-rediseno-ui-boveda-pii-hilos/) | Entregada | **Sin `spec.md`** — solo CHANGELOG. Hueco de documentación. |
| [043 Aislamiento y atribución](043-aislamiento-atribucion-motor/) | Entregada | 3 — sitio de docs (DoD), correr `quickstart.md`, reconstruir imágenes. *Probablemente cubiertas por 050 (imágenes `2026-09-14`); confirmar y cerrar.* |
| [044 Hub Chat + panel admin](044-hub-chat-panel-admin/) | Entregada | 9 — todas "correr `quickstart.md` §N y registrar", diferidas por necesitar datos reales. *Mismo caso que 043.* |
| [045 Carga de formatos y documentos](045-generacion-carga-documentos-eleia-hub/) | **Recortada** por 050 | Queda solo la carga de `.pptx` al RAG. Sin `tasks.md`. |
| [047 Formato de respuesta y presupuesto por rol](047-formato-respuesta-presupuesto-rol-eleia-hub/) | Sin arrancar | Sin `plan.md` ni `tasks.md`. |
| [049 Motor de generación de documentos](049-motor-generacion-documentos/) | **Recortada** por 050 | Queda docx/xlsx/pdf, sin presentaciones. Sin `tasks.md`. |
| [050 IA Hub — conector + motores](050-ia-hub-conector-motores/) | **Activa** (rama actual) | 7 puntos en su [CHANGELOG](050-ia-hub-conector-motores/CHANGELOG.md#estado-al-cierre-14-sep-2026-y-pendientes), no en un `tasks.md`. Ver abajo. |
| [051 Historial en Planillas](051-historial-planillas/) | Investigación **cerrada** | [RESULTADOS.md](051-historial-planillas/RESULTADOS.md) escrito; falta convertirlo en plan. |
| [052 Generación multimedia](052-generacion-multimedia/) | 🔬 **Investigación pendiente** | **Tarea abierta: investigar** imagen, audio y video. Arranca por relevar **qué proyectos ya lo hacen** — el patrón de este producto es integrar, no construir. "No lo hacemos acá" es un cierre válido. Sin implementación comprometida; no entra en el piloto. |
| [053 Integridad de costos y restricción tabular](053-integridad-costos-restriccion-tabular/) | US1 y US3 🟢 **implementadas** (17-sep), US2 Draft | Mail de Tomás Mc Nally (16-sep). US1 (atribución + precio de respaldo desalineado) y US3 (restricción `.csv`/`.xlsx` en el chat RAG) verificadas con tests y EN VIVO contra el stack real. Queda US2 (tarifario: precio manual al alta, reload periódico del cost map). Sin `plan.md` ni `tasks.md` todavía. |
| [054 Baja de equipos](054-baja-de-equipos/) | 🟢 **Implementada** (17-sep) | Hallazgo probando la 053 en vivo: un equipo se podía crear pero nunca dar de baja. Mismo patrón que la baja de usuario (spec 043 US5) — `is_active`/`deactivated_at` en `Group`, migración con id por hash. Sin `plan.md` ni `tasks.md`. |
| [055 Cambio obligatorio de contraseña en el primer ingreso](055-cambio-obligatorio-password-primer-ingreso/) | 🟢 **Cerrada, en producción** (21-sep) | Pedido directo del dueño. `must_change_password` en `User`, se prende en alta/reseteo admin y se apaga al cambiar voluntariamente. Implementada primero solo en Guardian (`frontend/`); el dueño aclaró que los usuarios reales nunca entran ahí, solo por **Eleia Hub** (`client/`) — se agregó una segunda ronda ahí (endpoint + modal propios, el Hub no comparte código de UI con Guardian). Verificado en vivo en ambas superficies, local y contra el servidor real del cliente. Handoff a Sentinel escrito. Sin `plan.md` ni `tasks.md`. |

**Total contable en la línea Eleia: 12 tareas** (043: 3, 044: 9 — el hallazgo del CBU de 040 se
cerró el 15-sep), más los 7 puntos de 050 que no están como tareas, más **2 investigaciones
pendientes de arrancar**: convertir la [051](051-historial-planillas/) en plan, e **investigar la
[052](052-generacion-multimedia/) (imagen, audio, video)** — más la [053](053-integridad-costos-restriccion-tabular/),
la [054](054-baja-de-equipos/) y la [055](055-cambio-obligatorio-password-primer-ingreso/), recién
creadas, todavía sin convertir a tareas.

### Pendientes de 050 (los que importan hoy)

1. **Barrido de nombres de tecnología** — regla del dueño, reiterada el 14-sep: que no quede
   "LiteLLM", "Ollama", "Presenton", "AnythingLLM" ni "Presidio" en nada visible al cliente.
   Hoy el panel todavía dice **"Modelos & Ollama"**. La spec que cubre esto es la
   [039](039-white-label-motor-marketplace/) — ver §4.
2. ~~Atribución de gasto por persona en el engine (`acted_for_user_id`).~~ **Movido a la
   [053](053-integridad-costos-restriccion-tabular/)**, que amplió el diagnóstico (17-sep): no era
   solo atribución, también hay un precio de respaldo desalineado y una pregunta abierta sobre dos
   sistemas de tracking de costo que pueden divergir.
3. Allow-list de términos de negocio por tenant en el NLP ("OTC", "FASON" detectados como PERSON).
4. Specs 047 y 049.
5. Restos de DB-GPT ocupando disco en el servidor (`elea-exact-analysis-engine`), con el disco
   chico como riesgo.
6. Dos tarjetas fantasma en la pantalla de plantillas de Presenton local (cosmético).

### Informes sueltos de la línea Eleia

- [`RESULTADOS-PRUEBA-MANUAL-UI.md`](RESULTADOS-PRUEBA-MANUAL-UI.md) — prueba manual de UI de 043/044 (10-sep), 20 bugs.
- [`RESULTADOS-QA-046-ANALISIS-EXACTO.md`](RESULTADOS-QA-046-ANALISIS-EXACTO.md) — QA de Análisis Exacto (11-sep) + addendum del 15-sep.
- [`VERIFICACION-043-044-pruebas.md`](VERIFICACION-043-044-pruebas.md) — verificación por API de 043/044.
- [`GENERACION-DOCUMENTOS.md`](GENERACION-DOCUMENTOS.md) — **cómo se decidió hacer la generación de
  documentos**: los dos modos, qué hace Presenton y qué el motor 4, y el contrato ya reservado.
  Junta lo que hoy está repartido en 045, 049, 050 y las dos investigaciones.
- [`RESULTADOS-INVESTIGACION-DOCGEN-*.md`](.) — investigación de docgen y DB-GPT (las fuentes).

---

## 2. Base compartida (001-039)

El núcleo Guardian sobre el que corre Eleia: gateway, firewall, enmascarado NLP, RBAC, auditoría,
retención, multi-tenant, licencias, ahorro de costes, docs de producto.

**272 tareas abiertas.** Es el backlog del **producto base**, no el plan de Eleia. Antes de tomar
cualquiera, confirmar que aplica a la versión argentina.

Las más pesadas: `035-load-harness` (46), `026-cli-operador-sentinel` (39),
`019-integration-surfaces` (33), `012-ahorro-costes-ia` (29), `017-auth-rbac-sso` (27),
`029-ui-foundry` (15), `018-retencion-tiers` (15).

**Dos que conviene revisar:**
- `029-ui-foundry` (15 tareas) — rediseño del panel. Posiblemente superado por 042/044/050. Confirmar.
- `026-cli-operador-sentinel` (39 tareas) — **sí aplica**: el CLI existe (`cli/sentinel_admin`) y
  las licencias están activas (`backend/src/licensing/`, seats). Pero **el nombre `sentinel-admin`
  es deuda de marca** en una instancia de Elea — ver §4.

---

## 3. Localización argentina — lo que falta

Eleia es la versión argentina, pero el compliance está escrito sobre marco europeo.

| Tema | Estado |
|---|---|
| Entidades argentinas (DNI, CUIL, CBU, PASSPORT) en el perfil `latam_ar` | **Implementado y activo.** Verificado el 15-sep dentro del contenedor: `SENTINEL_ENTITY_REGION=latam_ar`, cuatro entidades. El instalador lo pone como default (`elea-installer/docker-compose.yml`). El CBU se cerró el 31-ago. |
| El paracaídas de detección no cubría Argentina | 🟢 **CERRADO el 15-sep** (`8a8c8df`) — era el único agujero de protección. Ver abajo |
| **Ley 25.326** de Protección de Datos Personales | **No mapeada.** [005](005-compliance-policies-gdpr-ai-act/) cubre GDPR + EU AI Act |
| Registro de bases ante la **AAIP** | **No cubierto.** [008](008-audit-export-gdpr-art30/) exporta el Art. 30 del GDPR |

Las tres specs llevan una nota de localización en su encabezado. Decisión del 15-sep: se mantienen
como base compartida —el cliente es farmacéutica con operación internacional— y el mapeo a la ley
argentina queda como trabajo pendiente, sin fecha.

### 🟢 El paracaídas de detección no cubría Argentina (cerrado el 15-sep-2026)

Hay **dos** tablas de patrones en `litellm/extensions/sentinel_guardian_policy.py`, y sólo una
conoce Argentina:

| Tabla | Cuándo se usa | Regiones |
|---|---|---|
| `STRUCTURED_ID_PATTERNS_BY_REGION` | Camino normal: reconocedores ad-hoc → Presidio | `eu`, `latam_ar` |
| `FALLBACK_STRUCTURED_BY_REGION` | Paracaídas `default_analyze()`, cuando el sidecar NLP no responde | **antes: sólo `eu`** · ahora: `eu`, `latam_ar` |

**El problema, hasta el 15-sep:** si se caía el `nlp-analyzer`, una instalación argentina se quedaba sin ningún patrón estructurado.
No hereda los europeos: la resolución es `FALLBACK_STRUCTURED_BY_REGION.get(region, {})`
(`sentinel_guardian_policy.py:369`), y con `region="latam_ar"` eso devuelve `{}`. Los patrones
efectivos por región:

| región | patrones efectivos del paracaídas |
|---|---|
| `eu` | `EMAIL_ADDRESS`, `PERSON`, `ES_NIF`, `ES_NIE`, `PHONE_NUMBER`, `PHONE_INTL` |
| **`latam_ar`** | **`EMAIL_ADDRESS`, `PERSON`** — y nada más |

O sea: en modo degradado no se detecta **ni DNI, ni CUIL, ni CUIT, ni CBU** — y tampoco los
europeos. Lo único que sigue cubriendo es el fail-safe de tarjeta/IBAN, que enmascara cualquier
corrida larga de dígitos: por eso un CBU de 22 dígitos se salva de carambola, etiquetado como
`CREDIT_CARD`. Un DNI de 8 dígitos no.

> **Corrección del 15-sep:** la primera versión de esta nota decía "degrada a patrones españoles".
> Era falso, y la evidencia original —una prueba con CBU y DNI que detectó sólo `CREDIT_CARD`— no
> permitía distinguir las dos hipótesis, porque `ES_NIF` es `\b\d{8}[A-Za-z]\b` y no habría
> matcheado `28.455.910` de todos modos. Corregido tras la verificación cruzada con la sesión de
> Sentinel. El modo de fallo real es **peor**: pérdida total de detección estructurada.

Para un firewall de PII el camino degradado es justo donde más importa: corre **cuando algo ya
falló**.

**Arreglado el 15-sep en `8a8c8df`** (FR-015 y FR-016 del plan de convergencia, User Story 6 P1),
en dos mitades:

1. `FALLBACK_STRUCTURED_BY_REGION` ahora **espeja** las regiones: `latam_ar` con DNI, CUIL, CBU,
   PASSPORT y teléfono internacional. Los patrones se toman de la tabla principal con `[0]`, así no
   pueden divergir en silencio. La simetría es de **regiones, no de entidades**: `eu` deja PASSPORT
   afuera a propósito —su patrón `[A-Z0-9]{6,9}` sin palabras de contexto matchea casi cualquier
   token— y `latam_ar` sí lo lleva, porque `[A-Z]{3}\d{6}` aguanta solo en un camino de regex puro.
2. Cuatro tests en `backend/tests/test_policy_unit.py` que rompen si alguien agrega una región a
   una tabla y se olvida de la otra.

Los tests se verificaron **por mutación**: reintroduciendo el bug, dos se ponen en rojo. Vale
decirlo porque el primer intento de mutación no se aplicó y la corrida salió en verde igual —
quedarse ahí habría dado por verificado un test que nunca se ejecutó contra el fallo.

> **Es código de la base, no de la localización.** Se implementó acá porque es donde el agujero se
> sufría; la sesión de Sentinel lo toma por merge en vez de escribir un gemelo.

**Asimetría, para no confundirla:** `eu` era la única región que el paracaídas sí cubría, y por eso
el agujero era nuestro y no de la localización europea. En modo degradado Europa conserva sus
estructurados y pierde el NLP (el `PERSON` del paracaídas es regex y su propio docstring lo llama
*lossy*); Argentina, antes de este arreglo, no conservaba **nada** estructurado. Son dos pérdidas
distintas y sólo la segunda dejaba documentos de identidad en claro.

De paso, dos cosas del mismo archivo:
- El `TODO(región)` de la línea 364 (**FR-018** del plan de convergencia) (*"no se threadea `SENTINEL_ENTITY_REGION` desde los
  call-sites … hoy el único despliegue es eu"*) **está vencido**: los call-sites sí pasan `region`
  (`sentinel_guardrail.py:542,582`, `gateway.py:352,510`) y ya no es cierto que el único
  despliegue sea `eu`.
- La env var se llama **`SENTINEL_ENTITY_REGION`**: la instalación argentina configura su perfil
  de país con una variable con marca de Evidenze. Suma a la deuda de marca (§4); lo neutro sería
  `GUARDIAN_ENTITY_REGION` con alias retrocompatible (**FR-019** del plan de convergencia).

---

## 4. Deuda de marca

La regla: el cliente no debe ver nombres de tecnología ni la marca de otro cliente. Lo que hoy
incumple, verificado el 15-sep:

| Dónde | Qué se ve |
|---|---|
| Panel de Guardian | Menú **"Modelos & Ollama"** |
| `frontend/src/services/auth.ts:3` | Clave de sesión **`sentinel_session_token`** (también `basa_current_user`) |
| `cli/sentinel_admin` | El CLI de operador se llama **`sentinel-admin`** |

Va como **US4 del plan de convergencia** (`050-convergencia-localizaciones`, en `guardian-secure`), escrita
explícitamente como **trabajo de la base**: si lo hace cada fork por su lado se multiplica la
divergencia que el plan busca reducir. De nuestro lado la spec que lo toca es la
[039](039-white-label-motor-marketplace/) — creada exactamente por
este pedido ("no quiero que el cliente vea la dependencia tan directa de litellm"). **No tiene
`tasks.md`**; es la candidata natural para absorber el punto 1 de los pendientes de 050.

---

## 5. Huecos de documentación

| Hueco | Dónde |
|---|---|
| Spec sin `spec.md` | `042` (solo CHANGELOG) |
| Specs sin `tasks.md` | `023`, `039`, `042`, `045`, `047`, `049`, **`050`**, `051`, `053`, `054` |
| Specs sin `plan.md` | `045`, `047`, `049`, `050`, `051`, `053`, `054` |
| **Spec citada que nunca se escribió** | **`015`** — la cascada de `SecurityPolicy`/`entity_configs` (`client > group > tenant > default`) se cita como "spec 015" en `013` (3 veces), `016` y sus checklists, pero **no existe ni acá ni en Sentinel**, y nunca se creó en la historia común. Consecuencia real medida abajo. |
| **Roadmap desactualizado respecto al código real** | `specs/ROADMAP-pisos.md` (líneas ~45, 51) y `specs/033-engine-reload-restart-ui/tasks.md` (T001-T006 sin marcar) dicen "🔨 por construir" para alta de modelos sin reiniciar y reinicio desde la UI — verificado el 17-sep (investigación de la [053](053-integridad-costos-restriccion-tabular/)) que **ya está implementado**: `litellm/supervisor.py` + `POST /models` + `/models/apply` + `/models/status`, integrado en `deploy/docker/compose.prod.yml:225`. Falta actualizar el roadmap y tildar las tareas, no construir código. |

#### Qué significa que la 015 no exista (verificado el 15-sep)

Investigado a la par con la sesión de Sentinel, y **medido en este repo**, no asumido:

`SecurityPolicy` **no es multi-tenant en la práctica**, pese a tener la columna `tenant_id`. Lo
dice el propio código en [`backend/src/models/governance.py:20`](../backend/src/models/governance.py):

> *"esa tabla no es multi-tenant en la práctica pese a tener `tenant_id` — su lector real es
> `db.query(SecurityPolicy).first()` sin filtrar tenant"*

Confirmado en los lectores: `api/policy.py:34` y `api/costs.py:335-336` hacen `.first()` sin filtro
de tenant, y el invariante se mantiene apagando el resto en cada escritura. O sea que
`entity_configs` —qué entidades se enmascaran, cuáles se bloquean, y los flags de GDPR/AI Act— es
un **singleton efectivo de toda la instalación**.

**Lo que NO afecta, y es lo que importa para el modelo de localización:** la región no viaja por
`SecurityPolicy`. Viaja por la fila `Guardian(guardian_type="pii_masking")`, y su lector
`_select_pii_guardian` **sí filtra** (`entity_catalog_service.py:435`:
`.filter(Guardian.tenant_id == tenant_id, Guardian.guardian_type == "pii_masking")`). La
afirmación de arriba —región por tenant, más fina que un fork— se sostiene.

**El límite honesto:** dos tenants de países distintos en la misma instalación tendrían
**detectores distintos** (correcto) pero **compartirían la acción** —qué se enmascara y qué se
bloquea— hasta que exista la cascada. Es acotado y no es un agujero en el modelo de tres niveles,
pero conviene saberlo antes de vender multi-país sobre una sola instalación.

Escribir la 015 es una spec aparte; está marcada **fuera de alcance** del plan de convergencia
para que no se cuele ahí.

### Enlaces y referencias cruzadas

`scripts/enlaces-rotos.py` valida los enlaces markdown relativos de `specs/` y `docs/` (sale con
código 1 si hay rotos, sirve para un gate). Viene de la sesión de Sentinel; cuando esto converja,
va a la base y lo corren las dos localizaciones.

Al 15-sep: **521 enlaces, cero rotos.** Los 6 que encontró se arreglaron — dos apuntaban a otro
repositorio con rutas `file:///home/...` (que no son enlaces, son notas que sólo funcionan en una
máquina), uno contaba mal la profundidad desde el origen, uno apuntaba a `design-system/`
(repositorio aparte), uno a la extensión de navegador que no vive acá, y **uno era mío**: al mover
`046` a `_retiradas/` corregí los enlaces con `../` y con `specs/`, pero se me escapó uno relativo
pelado.

**Referencias cruzadas entre localizaciones:** las que apuntan a una spec de la otra llevan
prefijo, según ADR-0007. Hoy hay dos a `SENTINEL-037` (el wizard de onboarding, que vive sólo en
la localización europea), en `040/spec.md` y `ROADMAP-guardian.md`.

El más costoso es **050**: es la rama actual y el mayor cuerpo de trabajo del mes, y su estado vive
en prosa dentro del CHANGELOG. Si algo se convierte en `tasks.md`, que sea eso.

---

## 6. Pendientes acordados entre localizaciones (sin implementar)

**Tarifario centralizado (17-sep-2026)** — acordado entre esta sesión y la sesión de Sentinel,
confirmado por el dueño del producto: hoy cada línea (Sentinel, Eleia, y cualquier futura)
mantiene su propia tabla `MODEL_PRICING` hardcodeada a mano en su propio código
(`backend/src/services/budget_service.py` acá; Sentinel confirmó tener el mismo patrón, con el
mismo bug de sobrefacturación para `azure-gpt-5.1-chat`/`azure-gpt-5.4-mini` sin precio manual
cargado — ver [053](053-integridad-costos-restriccion-tabular/spec.md) US2). La iniciativa: un
servicio o fuente de precios **centralizada y compartida** entre todas las localizaciones, para
que ninguna tenga que mantener su tabla por separado ni pueda quedar desalineada del resto.

**Estado: acordado como dirección futura, nada implementado todavía.** No tiene spec propia ni
número asignado — cuando se tome, conviene que sea una spec de la **base** (`guardian-secure`),
no de Eleia ni de Sentinel por separado, para que ambas localizaciones (y las que vengan) lean de
la misma fuente desde el día uno. Del lado de Sentinel quedó anotado en su propio registro de
cambios (sesión "Cambios de Elea", 17-sep) — si esta nota se pierde de un lado, el otro repo la
tiene igual.

---

## Números, antes y después

|  | Antes | Después |
|---|---|---|
| Carpetas en la raíz | 44 | 40 |
| Casillas sin marcar visibles | 332 | 285 |
| De esas, backlog real de Eleia | *no se podía saber* | **12** (+ 7 puntos de 050, + 1 gap abierto en §3) |
| Backlog del producto base | *mezclado* | 272, separado y rotulado |
| Tareas de specs muertas contadas como pendientes | 47 | 0 |
