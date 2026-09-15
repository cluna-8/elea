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

> **Numeración** (ADR-0007): las specs **001-038** son las mismas en los dos repos —están en los
> 524 commits de historia común— y van **sin prefijo**. De la **039 en adelante** divergen: se
> referencian como `ELEIA-0xx` / `SENTINEL-0xx`.

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

**Total contable en la línea Eleia: 12 tareas** (043: 3, 044: 9 — el hallazgo del CBU de 040 se cerró el 15-sep), más los 7 puntos de 050
que no están como tareas.

### Pendientes de 050 (los que importan hoy)

1. **Barrido de nombres de tecnología** — regla del dueño, reiterada el 14-sep: que no quede
   "LiteLLM", "Ollama", "Presenton", "AnythingLLM" ni "Presidio" en nada visible al cliente.
   Hoy el panel todavía dice **"Modelos & Ollama"**. La spec que cubre esto es la
   [039](039-white-label-motor-marketplace/) — ver §4.
2. Atribución de gasto por persona en el engine (`acted_for_user_id`).
3. Allow-list de términos de negocio por tenant en el NLP ("OTC", "FASON" detectados como PERSON).
4. Specs 047 y 049.
5. Restos de DB-GPT ocupando disco en el servidor (`elea-exact-analysis-engine`), con el disco
   chico como riesgo.
6. Dos tarjetas fantasma en la pantalla de plantillas de Presenton local (cosmético).

### Informes sueltos de la línea Eleia

- [`RESULTADOS-PRUEBA-MANUAL-UI.md`](RESULTADOS-PRUEBA-MANUAL-UI.md) — prueba manual de UI de 043/044 (10-sep), 20 bugs.
- [`RESULTADOS-QA-046-ANALISIS-EXACTO.md`](RESULTADOS-QA-046-ANALISIS-EXACTO.md) — QA de Análisis Exacto (11-sep) + addendum del 15-sep.
- [`VERIFICACION-043-044-pruebas.md`](VERIFICACION-043-044-pruebas.md) — verificación por API de 043/044.
- [`RESULTADOS-INVESTIGACION-DOCGEN-*.md`](.) — investigación de docgen y DB-GPT.

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
| **El paracaídas de detección no cubre Argentina** | 🔴 **ABIERTO** — en modo degradado se pierde TODA la detección estructurada. Ver abajo |
| **Ley 25.326** de Protección de Datos Personales | **No mapeada.** [005](005-compliance-policies-gdpr-ai-act/) cubre GDPR + EU AI Act |
| Registro de bases ante la **AAIP** | **No cubierto.** [008](008-audit-export-gdpr-art30/) exporta el Art. 30 del GDPR |

Las tres specs llevan una nota de localización en su encabezado. Decisión del 15-sep: se mantienen
como base compartida —el cliente es farmacéutica con operación internacional— y el mapeo a la ley
argentina queda como trabajo pendiente, sin fecha.

### 🔴 El paracaídas de detección no cubre Argentina (abierto, 15-sep-2026)

Hay **dos** tablas de patrones en `litellm/extensions/sentinel_guardian_policy.py`, y sólo una
conoce Argentina:

| Tabla | Cuándo se usa | Regiones |
|---|---|---|
| `STRUCTURED_ID_PATTERNS_BY_REGION` | Camino normal: reconocedores ad-hoc → Presidio | `eu`, **`latam_ar`** |
| `FALLBACK_STRUCTURED_BY_REGION` | Paracaídas `default_analyze()`, cuando el sidecar NLP no responde | **sólo `eu`** |

**Si se cae el `nlp-analyzer`, una instalación argentina se queda sin ningún patrón estructurado.**
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
falló**. El arreglo es de la **base**, no de la localización, y son dos cosas:

1. Que `FALLBACK_STRUCTURED_BY_REGION` **espeje** las regiones de la tabla principal — no que
   herede `eu`, porque un patrón español sobre datos argentinos no sirve.
2. Un **test que falle** si alguien agrega una región a la tabla principal y no al paracaídas. Sin
   eso, esto se vuelve a desincronizar solo.

En el plan de convergencia de `guardian-secure` son **FR-015 y FR-016 (User Story 6, P1)** — el
único agujero de protección de esa spec; el resto es orden y documentación.

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
| Specs sin `tasks.md` | `023`, `039`, `042`, `045`, `047`, `049`, **`050`**, `051` |
| Specs sin `plan.md` | `045`, `047`, `049`, `050`, `051` |
| **Spec citada que nunca se escribió** | **`015`** — la cascada de `SecurityPolicy`/`entity_configs` (`client > group > tenant > default`) se cita como "spec 015" en `013` (3 veces), `016` y sus checklists, pero **no existe ni acá ni en Sentinel**, y nunca se creó en la historia común. Es trabajo de arquitectura documentado sin spec en ninguna parte. |

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

## Números, antes y después

|  | Antes | Después |
|---|---|---|
| Carpetas en la raíz | 44 | 40 |
| Casillas sin marcar visibles | 332 | 285 |
| De esas, backlog real de Eleia | *no se podía saber* | **12** (+ 7 puntos de 050, + 1 gap abierto en §3) |
| Backlog del producto base | *mezclado* | 272, separado y rotulado |
| Tareas de specs muertas contadas como pendientes | 47 | 0 |
