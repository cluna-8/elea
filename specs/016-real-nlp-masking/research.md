# Research — 016 Real NLP Masking & Entity Detection Hardening

Fase 0. Resuelve las incógnitas técnicas de `plan.md` antes del diseño (Fase 1). Las dos decisiones
de producto/seguridad (alcance vs 015, fail-mode del NLP) ya se resolvieron con el usuario en `spec.md`
(Assumptions, FR-004, FR-005) — acá se resuelven las incógnitas técnicas restantes.

## 1. Motor de detección NLP real

**Decision**: Presidio Analyzer (Microsoft, open-source) como servicio HTTP sidecar, con un **modelo
spaCy en español** (`es_core_news_md`), construido en una **imagen propia** (no la imagen oficial
default, que trae inglés). Se usa **solo el Analyzer** (`/analyze`), no el Anonymizer — el reemplazo
reversible lo sigue haciendo `PlaceholderMap`/`mask_text` de `basa_guardian_policy.py` (el Anonymizer
de Presidio hace sustitución irreversible, no sirve al moat de des-enmascarar).

**Rationale**:
- Es exactamente el scaffolding que el código heredado ya anticipaba (`PresidioService.analyze_text_http`,
  Guardian `guardian_type="presidio"` con `analyzer_url`/`anonymizer_url`) — cierra la brecha entre lo
  documentado como intención y lo real (HANDOFF.md §7, Constraint SC-2).
- Confirmado (docs oficiales): la imagen oficial de `presidio-analyzer` se construye con
  `docker build --build-arg NLP_CONF_FILE=<config>.yaml`, donde el config declara el modelo spaCy a
  instalar. Para español hace falta un `NLP_CONF_FILE` propio apuntando a `es_core_news_md` (o `_lg` si
  el volumen/latencia lo justifica) — la imagen default NO trae español. Esto es un build propio, versionado
  y pinneado por digest (mismo patrón que ya usa el motor LiteLLM, Principio VI/VII), no un fork del
  proyecto Presidio.
- Confirmado (docs oficiales): el endpoint `/analyze` acepta `ad_hoc_recognizers` en el body del
  request — permite inyectar reconocedores de patrón (regex) y deny-list **por request**, sin tocar la
  imagen. Esto es la pieza clave para no duplicar listas de patrones (ver §3).

**Alternatives considered**:
- *spaCy embebido directo en el backend/motor* (sin Presidio): rechazado — se pierde el framework de
  recognizers/score-fusion de Presidio gratis, y habría que reimplementar manejo de contexto/scoring a mano.
- *API SaaS de terceros (AWS Comprehend Medical, Azure PII, etc.)*: rechazada — viola Principio I
  ("el mapa reversible... jamás se delega a un tercero") y la postura de residencia de datos EU; el
  texto crudo saldría de la infraestructura propia antes de enmascarar, que es exactamente lo que el
  producto existe para evitar.
- *Mantener regex-only pero "mejor"*: rechazado — no cumple Constraint SC-2 (NLP real es precondición
  de prod con PHI), y no resuelve el gap de nombres sin prefijo (US1) de forma sostenible.

## 2. Topología de despliegue

**Decision**: nuevo servicio `presidio-analyzer` en `docker-compose.yml`, en `basa-network`, sin puerto
expuesto al host (solo alcanzable desde `backend` y `litellm`). URL inyectada por env var
(`PRESIDIO_ANALYZER_URL`), consistente con el patrón de Constraint C5 (credenciales/endpoints fuera de
`config.yaml` en claro).

**Rationale**: mismo patrón de containerización que el resto del stack (Principio VII); no acopla el
NLP al proceso del motor LiteLLM (que sigue pinneado por digest, sin instalarle dependencias ML propias
— Principio VI, "no patching").

**Alternatives considered**: instalar spaCy/Presidio dentro de la imagen del motor LiteLLM — rechazado,
rompería el pin-by-digest y el principio de no tocar la imagen del motor.

## 3. Una sola fuente de patrones/entidades (cierra SC-006)

**Decision**: los patrones estructurados **que Presidio no cubre ya con un reconocedor propio validado
para el idioma activo**, más la deny-list de nombres personalizados (hoy `Guardian.config.custom_names`,
editable desde el panel), se envían como `ad_hoc_recognizers` en cada llamada a `/analyze`, construidos
desde **una sola función Python** (`build_ad_hoc_recognizers`, en `basa_guardian_policy.py`, la librería
PURA que ya comparten ambos caminos — panel y firewall) parametrizada por **región** (`STRUCTURED_ID_PATTERNS_BY_REGION`).
Se eliminan los dos diccionarios `PII_PATTERNS` duplicados (`presidio_service.py` y `basa_guardian_policy.py`).

**Corrección post-review (despliegue objetivo confirmado: Europa, España primero — no Argentina)**: el
set inicial de este documento asumía DNI/CUIL argentinos como ejemplo de "lo que hay que inyectar ad-hoc".
Para España, **no hace falta inyectar nada propio para el DNI/NIE**: Presidio ya trae `ES_NIF`/`ES_NIE`
como reconocedores **built-in con validación de checksum** para `supported_language="es"` — más precisos
que cualquier regex propio, así que se usan tal cual (cero código nuestro). El único `ad_hoc_recognizer`
real de la región `"eu"` es `PASSPORT` (sin formato único a nivel UE, patrón genérico + palabras de
contexto). DNI/CUIL argentinos quedan documentados como región `"latam_ar"`, preparada pero **inactiva**
hasta que haya un despliegue en esa región (`BASA_ENTITY_REGION`).

**Rationale**: cierra literalmente el comentario "espejo de PresidioService.PATTERNS" que hoy documenta
la duplicación como deuda conocida — Y evita reinventar con regex algo que el motor NLP ya resuelve mejor
(precisión: FR-003, pedido explícito del usuario de "que sea preciso, no regex hardcodeado"). `custom_names`
pasa de ser una lista hardcodeada en Python (y exclusiva del camino legacy) a viajar como deny-list ad-hoc
en cada request — ahora sí tiene efecto en el firewall real (US1 se beneficia también de esto: nombres
conocidos se detectan aunque el NLP falle en casos borde).

**Alternatives considered**: reconstruir un `RecognizerRegistry` custom dentro de la imagen de Presidio
(vía `conf/`) — rechazado para v1: requiere rebuild de imagen por cada cambio de patrón/nombre, mientras
que `ad_hoc_recognizers` permite que un compliance officer edite `custom_names` desde el panel y tenga
efecto inmediato sin redeploy. Reimplementar NIF/NIE con regex propio — rechazado: Presidio ya lo hace
con checksum, reimplementarlo sería peor (menos preciso) y duplicaría lógica que el motor ya mantiene.

## 4. Fail-closed real ante indisponibilidad del NLP (FR-004)

**Decision**: la llamada HTTP a Presidio Analyzer usa un timeout corto (research: 2s) dentro de
`async_pre_call_hook`. Si falla (timeout, 5xx, conexión rechazada), el hook **retorna un motivo de
bloqueo** (mismo contrato que ya usan hoy AI-Act/secretos: un `str` → HTTPException 400/503) en vez de
devolver `[]` y seguir. Esto es un **cambio de contrato** respecto al código heredado: hoy
`PresidioService.analyze_text_http` atrapa la excepción y devuelve `[]` silenciosamente — fail-**open**.
Ese comportamiento se reemplaza.

**Rationale**: es exactamente la decisión que tomó el usuario (fail-closed, ver spec.md). Reusa el
mismo canal de bloqueo que ya existe para AI-Act/secretos — no se inventa un mecanismo nuevo.

**Alternatives considered**: circuito breaker con caché de "último resultado conocido bueno" — rechazado
por complejidad no justificada para v1; ninguna garantía de que el contenido cacheado sea representativo
del nuevo prompt.

## 5. Resolución de coincidencias solapadas (FR-009)

**Decision**: función pura `resolve_overlaps(entities) -> entities` en `basa_guardian_policy.py`,
aplicada ANTES del reemplazo en `mask_text`. Regla determinística: se ordenan las entidades por
`(start, -length)`; una entidad que queda completamente contenida dentro del rango de otra ya aceptada
se descarta (gana la coincidencia más larga/específica); a igual rango, gana el score más alto, y a
empate total el orden de detección original (estable).

**Rationale**: reemplaza el comportamiento actual (ordenar solo por `start` descendente, sin deduplicar)
que puede corromper offsets ante rangos solapados. "Más larga gana" es la heurística estándar para
tokenizadores/NER con múltiples reconocedores (evita que un match genérico y corto gane sobre una entidad
más larga/específica que lo contiene, sin importar el tipo — el algoritmo es agnóstico de región).
**Corrección**: la implementación real usa clustering de intervalos (componentes conexas del grafo de
solapamiento), no comparación par-a-par contra el último aceptado — necesario para resolver correctamente
3+ entidades solapadas en cadena (A solapa B, B solapa C, A y C no se tocan directamente), caso que la
comparación par-a-par simple no garantiza resolver sin dejar un solapamiento residual.

**Alternatives considered**: descartar solapamientos y bloquear la request — rechazado, sobre-reacciona
a un caso que tiene una resolución determinística simple; "primero detectado gana" (comportamiento
implícito actual) — rechazado por ser dependiente del orden de iteración de los reconocedores, no
reproducible.

## 6. Conectar `entity_configs` al firewall real (FR-005)

**Decision**: extender la consulta SQL de identidad ya existente en `litellm/extensions/custom_auth.py`
(`_IDENTITY_SQL`) para además traer la `SecurityPolicy` activa (`entity_configs` JSONB) — hoy esa
consulta ya resuelve tenant/user/group/tool en una sola query contra la misma base. `entity_configs`
viaja en la identidad (`metadata.basa`) que ya llega al guardrail. `BasaGuardrail.async_pre_call_hook`
resuelve la acción de cada entidad detectada vía `resolve_entity_action(entity_type, entity_configs)`
ANTES de tocar el body: si alguna resuelve a `BLOCK`, la request se rechaza entera (mismo path que
AI-Act/secretos, un solo preview de detección — no se enmascara nada primero para bloquear después);
si ninguna es `BLOCK`, sigue el flujo de enmascarado reversible (`MASK`) actual.

**Rationale**: reusa el patrón ya establecido en spec 014 (acceso a DB vía el propio motor, sin agregar
dependencias a la librería PURA) en vez de inventar un mecanismo nuevo de resolución de policy dentro
del guardrail. Deja el terreno preparado para que la 015 reemplace esta única query global por la
cascada `client > group > tenant > default` sin tocar el wiring de acciones (mismo contrato:
`entity_configs: dict[str, "MASK"|"BLOCK"]`).

**Default para tipos no configurados (FR-008)**: `MASK`. Es el default seguro — un tipo de entidad
detectado pero no configurado explícitamente nunca pasa en crudo; a la vez no bloquea tráfico por
omisión de configuración (evita que un olvido de config tumbe operación).

## 7. Consistencia panel/playground vs firewall (FR-012)

**Decision**: `presidio_service.py` (camino legacy/panel) pasa a llamar al mismo Presidio Analyzer HTTP
(ya tiene `analyze_text_http`, solo le falta aceptar `ad_hoc_recognizers` y dejar de fail-open en el
`except`). `guardian_service.py` deja de mantener su propio catálogo de `PATTERNS` — reusa la función
de construcción de `ad_hoc_recognizers` de §3.

**Rationale**: cierra la duplicación en la dirección panel→firewall (comparten fuente), consistente con
"Reuse over Reinvent" (Development Workflow, constitución).

## 8. Presupuesto de latencia (informa SC-005)

**Decision de trabajo (interna, no un nuevo SC de usuario)**: timeout de red de 2s al Analyzer (§4);
objetivo operativo de referencia ~300ms p95 para la llamada de análisis sobre prompts dentro del cap
existente (`INSPECT_CAP` = 16000 chars). Llamada async (no bloquea el event loop del motor).

**Rationale**: mantiene el guardrail dentro de rangos interactivos para las herramientas soportadas
(Claude Code, Copilot) sin introducir un SC técnico que viole "Success criteria tecnología-agnósticas".

**Alternatives considered**: cache de resultados por hash de texto — rechazado para v1 (la mayoría de
los prompts son únicos; complejidad de invalidación no justificada todavía).
