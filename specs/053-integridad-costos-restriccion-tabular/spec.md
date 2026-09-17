# Feature Specification: Integridad de costos (atribución + precisión + tarifario) y restricción de planillas en el chat RAG

**Feature Branch**: `053-integridad-costos-restriccion-tabular`

**Created**: 2026-09-17

**Status**: 🟢 **US1 y US3 implementadas y verificadas de punta a punta (17-sep)**. US1: FR-001 a
FR-004 más FR-012 (nuevo, segunda ronda) — el gasto por usuario/grupo del chat de documentos (RAG)
no se atribuía porque AnythingLLM nunca manda la identidad al motor; se agregó
`POST /chat/rag-usage` para que el Hub reporte su propio consumo. Verificado con login real, chat
real contra Azure real, y confirmado en el panel de Costos real que el contador sube — no solo con
tests que arman la fila a mano (ver [[regla-verificacion-completa-antes-de-informar]] para el porqué
de este segundo párrafo). US3: FR-009 a FR-011, verificada tanto con tests automatizados
(`client/tests/unit/workspace-upload-restriccion-tabular-053.test.js`) como EN VIVO contra el
stack real (login real, subida real de `.csv`/`.xlsx`/`.txt` por HTTP, confirmado 415/200 según
corresponda, y el atributo `accept` presente en el DOM del navegador). US2 (tarifario) sigue en
Draft, sin implementar — no bloquea el piloto del lunes 21/9.

**Repos que toca**: `cluna-8/elea` (`litellm/extensions/`, `backend/src/api/`, `backend/src/services/`, `client/`).

**Input**: Mail de Tomás Mc Nally (Elea, 16-sep-2026), pedido de corrección para el viernes 18/9
de cara al piloto que arranca el lunes 21/9:

> "Estuve realizando pruebas con mi usuario (tmcnally) y veo como los costos de gasto por modelo y
> gasto por grupo se incrementan mientras que los gastos por usuario no y en particular mi usuario
> sigue en 0 y con 8 peticiones fijas (a pesar de que hice más). Por otro lado, también mi usuario
> está en un grupo y ese grupo no aparece: (solo incrementa el sin grupo). El objetivo es poder
> hacer un trackeo exacto de mensajes enviado por usuario con costo asociado (total y/o por
> mensaje) y grupo para poder hacer un análisis de costo general."
>
> "Restricción de archivos: quisiera saber si es posible restringir la subida de archivos .csv y
> .xlsx en la pestaña de chat para evitar que se quieran hacer consultas sobre planillas en las
> bases que se almacenan como RAGs con el objetivo de evitar un mal uso de la plataforma."

Decisión del dueño del producto (17-sep, esta sesión): el reporte de costos disparó sospecha de un
problema más de fondo que la atribución simple, dado que LiteLLM es el motor central de todo el
producto — se investigó a fondo antes de escribir la spec, en vez de arreglar solo lo reportado.
El resultado confirma la sospecha: **hay tres defectos de costos independientes**, no uno, y un
cuarto hallazgo sobre de dónde salen los precios en primer lugar, pedido explícitamente por el
dueño ("los modelos salen todo el tiempo y los precios son dinámicos, no quiero perder esa
funcionalidad"). Sobre la restricción de archivos, se decidió proceder con el bloqueo tal como lo
pidió el cliente, dejando documentado el efecto colateral real que tiene.

## Diagnóstico verificado en código (17-sep)

Investigado con dos agentes de exploración en paralelo, solo lectura, con file:line — resumen; el
detalle línea por línea queda citado abajo en cada User Story.

| # | Síntoma reportado / preocupación | Causa raíz confirmada |
|---|---|---|
| 1 | Gasto por usuario no sube, el de Tomás queda en 8 peticiones fijas | Hay dos caminos que escriben filas de auditoría para tráfico exitoso vía el motor. El de bloqueos ya arregló esto el 9-sep; el de éxito (`sentinel_audit_logger.py`) arma su registro sin `acted_for_user_id`, aunque el dato ya está disponible ahí mismo. Las filas nuevas caen bajo la cuenta de servicio del conector, no bajo Tomás. |
| 2 | Gasto por grupo solo incrementa "sin grupo" | Mismo origen que #1, más un segundo defecto propio: la consulta de gasto por grupo usa el grupo crudo de la conexión en vez de resolver el grupo del usuario real (a diferencia de la consulta de gasto por usuario, que sí lo hace). |
| 3 | (No reportado por el cliente, hallado al investigar la sospecha del dueño) | El número de costo en sí, no solo su atribución, puede estar mal calculado: hay una tabla de precios de respaldo hardcodeada que no tiene los dos modelos de mayor uso en producción y sobrefactura hasta 6.7x cuando se activa. |
| 4 | (Hallado al investigar) | Coexisten dos sistemas de tracking de costo con distinto alcance de tráfico — pueden mostrar totales distintos para la misma actividad. Documentado, sin resolver en esta ronda. |
| 5 | "No quiero perder la elección de modelos ni los precios dinámicos" (pedido explícito del dueño) | El catálogo de modelos elegibles sí se mantiene al día automáticamente (spec 033 ya implementada, aunque el roadmap dice lo contrario). Los precios NO se mantienen al día de forma confiable: dependen de una descarga remota que puede fallar en instalaciones sin internet, de una imagen Docker pineada que solo avanza a mano, y de que el alta de un modelo nuevo no permite cargar su precio. |
| 6 | Pedido de restringir `.csv`/`.xlsx` en el chat | Hoy no hay ninguna validación de extensión en el flujo de RAG general. Existe un flujo tabular separado que ya valida correctamente esas extensiones. Bloquear en RAG es viable pero tiene un efecto colateral real: hoy esa es una función intencional y ya reparada de un bug (búsqueda semántica aproximada sobre contenido de planillas), distinta del cálculo exacto del motor tabular. |

**Fuera de alcance explícito**: reconciliar los dos sistemas de tracking de costo (#4) queda como
pregunta abierta, no como tarea de esta spec — ver US1, sección "Hallazgo documentado, sin
resolver". La migración de nomenclatura ("Modelos & Ollama" y similares) es la spec 039, no esta.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Atribución y precisión del gasto por usuario y por grupo (Priority: P1) — 🟢 IMPLEMENTADA (17-sep)

Un administrador (o el propio usuario) abre el panel de Costos durante el piloto y necesita que el
gasto que ve, filtrado por usuario o por grupo, refleje con exactitud lo que esa persona gastó —
tanto en cantidad de peticiones como en dólares — para poder decidir si el uso de la plataforma es
razonable y a quién corresponde el costo.

**Por qué esta prioridad**: es lo que el cliente pidió explícitamente para el viernes 18/9, y sin
esto el piloto del lunes 21/9 arranca sin la única métrica que el cliente dijo necesitar
("análisis de costo general"). Además, el defecto de precio de respaldo puede estar sobrefacturando
presupuesto real de usuarios hoy mismo, sin que nadie lo haya notado.

**Independent Test**: puede probarse íntegramente haciendo N peticiones con un usuario de prueba
que pertenezca a un grupo, vía el motor (IA Hub / gateway), y verificando que el panel de Costos
muestra N peticiones nuevas atribuidas a ese usuario y a su grupo real — sin tocar ningún otro
flujo del producto.

**Acceptance Scenarios**:

1. **Given** un usuario real (no cuenta de servicio) que pertenece a un grupo, **When** hace una
   petición exitosa a través del motor, **Then** el panel de Costos por usuario incrementa en 1 la
   cantidad de peticiones y el gasto de ese usuario específico.
2. **Given** el mismo usuario, **When** se consulta el gasto por grupo, **Then** el incremento
   aparece bajo el grupo real del usuario, no bajo "sin grupo".
3. **Given** una respuesta servida por `azure-gpt-5.1-chat` o `azure-gpt-5.4-mini` en cualquier
   escenario donde el header nativo de costo del motor no llegue, **When** el sistema calcula el
   costo de respaldo, **Then** usa el precio real de ese modelo (o un valor documentado como
   deliberadamente conservador), nunca el precio genérico por defecto de $5/$15 por millón de
   tokens.
4. **Given** una petición cuyo costo de respaldo se calculó con el precio genérico por defecto,
   **When** ocurre, **Then** queda una traza (log o métrica) de que se usó el fallback genérico,
   para poder auditar cuántas veces pasó y corregir la tabla de precios.

#### Diagnóstico verificado (file:line)

- **Atribución rota en el camino de éxito**: `litellm/extensions/sentinel_audit_logger.py`, método
  `_log`, dict `entry` (líneas ~365-383) no incluye `acted_for_user_id`, aunque
  `sentinel.get("acted_for_user_id")` (línea ~314, viene de `policy.proxy_identity_from(...)`) ya
  lo tiene disponible. El camino de bloqueos (`sentinel_guardrail.py:340-352`) ya lo hace desde el
  9-sep — mismo patrón a replicar. Coincide con el pendiente #2 ya anotado en
  `specs/050-ia-hub-conector-motores/CHANGELOG.md:26`.
- **Gasto por usuario ya resuelve bien la identidad real cuando el dato llega**:
  `backend/src/api/costs.py`, función `by_user` (líneas ~160-182):
  `LEFT JOIN users u ON u.id = COALESCE(a.acted_for_user_id, a.user_id)` con filtro
  `u.account_type != 'service'` — la query está bien, el problema es que `acted_for_user_id` casi
  nunca llega poblado.
- **Gasto por grupo no resuelve la identidad real**: `backend/src/api/costs.py`, función
  `by_group` (líneas ~220-233): `LEFT JOIN groups g ON g.id = a.user_group_id` usa el grupo crudo
  de la fila (normalmente el de la cuenta de servicio, casi siempre `NULL`), sin coalescer contra
  el usuario real como sí hace `by_user`.
- **Por qué "gasto por modelo" sí se actualiza y "por usuario" no**: `top_models`
  (`costs.py:132-152`) agrupa por `model`, no depende de atribución de usuario — por eso el
  síntoma reportado por Tomás es asimétrico entre las dos vistas.
- **Contrato de wire ya existe de punta a punta, sin migración necesaria**: la columna
  `acted_for_user_id` existe en `audit_logs` desde la migración `018_workspaces_service_accounts_
  audit_surface.py` (líneas 201-210); el endpoint receptor `backend/src/api/internal.py`
  (`AuditEntry`, línea 255, INSERT líneas 199-213) ya la acepta y persiste.
- **El número de costo en sí puede estar mal, no solo su atribución**:
  `backend/src/services/budget_service.py:38-47`, diccionario `MODEL_PRICING` hardcodeado de
  respaldo — no incluye `azure-gpt-5.1-chat` ni `azure-gpt-5.4-mini` (los dos modelos de mayor uso
  en producción según `litellm/config.yaml`), y sí incluye modelos ya retirados del catálogo
  (`gpt-4o`, `gemini-*`, `claude-3-5-sonnet` — ver `litellm/config.yaml:33-35`, "sacados del
  catálogo... no son los que corren en producción"). Se usa como fallback en
  `backend/src/api/chat.py:1741` cuando `actual_cost` (que sale del header nativo
  `x-litellm-response-cost`, leído en `chat.py:1587`) no llega, cayendo en
  `MODEL_PRICING["default"]` = $5/$15 por millón de tokens — **1.5x a 6.7x el precio real** de esos
  dos modelos (`gpt-5.4-mini` real: $0.75/$4.5 por millón; `gpt-5.1-chat` real: $1.25/$10 por
  millón). Ese número erróneo se escribe directo a `audit_logs.cost_usd` (`chat.py:1858`) y
  descuenta presupuesto real del usuario (`chat.py:1913-1923`). Sin tests que cubran este fallback
  para los modelos vigentes (`grep MODEL_PRICING\|azure-gpt-5` sobre
  `backend/tests/unit/test_budget_precision.py` y `test_chat_budget_audit.py` no dio resultados).
- **Relacionado, menor**: `has_known_pricing()` (`budget_service.py:74-88`) también devuelve
  `False` para esos dos modelos de producción, lo que en el camino de ruteo automático
  (`chat.py:1730-1738`) puede llevar a facturar bajo el nombre del modelo pedido en vez del modelo
  real que respondió — de menor severidad porque normalmente `cost` sigue viniendo del header real.

#### Respaldo en LiteLLM nativo — investigado a pedido del dueño (17-sep), NO usar

El dueño preguntó explícitamente si LiteLLM ya trae resuelto el tracking de gasto por usuario real,
para no sumar "una capa más" si el motor ya lo hace. Investigado contra la documentación oficial de
LiteLLM y el código instalado (1.95.1):

- **Sí existe un mecanismo nativo** — el campo `user` (OpenAI-compatible) en el body de la
  petición, que LiteLLM resuelve a `end_user_id` (`litellm/proxy/auth/auth_utils.py:1238`) y
  persiste en `LiteLLM_SpendLogs.end_user`, consultable vía `/spend/logs/v2?end_user=`,
  `/global/spend/end_users`. Existe además `LiteLLM_EndUserTable` para budgets por end-user.
- **Pero no se valida por defecto.** La propia documentación de LiteLLM lo dice explícito: *"The
  `user` field is NOT validated or authenticated by default"* — es un identificador arbitrario que
  pone quien arma el request; la validación contra base de datos es opt-in
  (`litellm.validate_end_user_id_in_db`, apagado por defecto) y el propio código de LiteLLM trae
  la advertencia de seguridad de solo usarlo en entornos de confianza. Es el mismo riesgo que nuestro
  propio código ya evita: `sentinel_audit_logger.py` usa un **header** verificado server-side
  (`x-guardian-acting-user`, chequeado contra `can_act_on_behalf` + mismo tenant en
  `custom_auth.py:_verify_acting_user`), no un campo de payload falsificable.
- **`LiteLLM_SpendLogs` no cubre lo que `audit_logs` sí cubre**: sin PII/enmascarado
  (`masked_entities`, `pii_detected`), sin estado de compliance, sin trazabilidad de capas de
  guardrail (`applied_layers`/`blocked_by_layer`), y sin filas de requests **bloqueados** (spend
  logs solo registra tráfico que efectivamente llegó al proveedor). `audit_logs` existe
  precisamente para unir costo + compliance + bloqueos + identidad verificada — el corazón
  regulatorio del producto (spec 031).
- **Confirmado que hoy no estamos cerca de aprovecharlo igual**: ningún punto de
  `backend/src/`/`litellm/extensions/` manda el campo `user` en el payload al motor; el `gateway.py`
  reenvía bytes crudos multi-formato (Anthropic, OpenAI-compatible, etc.), así que inyectar `user`
  de forma confiable en cualquier forma de body sería más fragil que el header único que ya existe.

**Veredicto: no migrar.** El sistema nativo resuelve un problema distinto (budget simple por string
arbitrario, sin garantías); el nuestro es la única capa que junta costo, PII y compliance con
procedencia verificada, y migrar sería *sumar* trabajo (reescribir `costs.py` para pegarle a
`/spend/logs/v2`, mantener `audit_logs` de todas formas para compliance) sin ganar garantías. El
fix se mantiene mínimo: FR-001 tal como está arriba, la línea faltante en `sentinel_audit_logger.py`.

#### Implementación (17-sep) — FR-001 a FR-004

- **FR-001/FR-002**: `litellm/extensions/sentinel_audit_logger.py::_log` ahora incluye
  `"acted_for_user_id": sentinel.get("acted_for_user_id")` en el dict `entry` del camino de
  éxito, mismo patrón que `sentinel_guardrail.py:352` para bloqueos.
- **FR-002 (grupo)**: `backend/src/api/costs.py::by_group` ahora hace
  `LEFT JOIN users u ON u.id = COALESCE(a.acted_for_user_id, a.user_id)` seguido de
  `LEFT JOIN groups g ON g.id = COALESCE(u.group_id, a.user_group_id)` — resuelve el
  grupo de la persona real primero, cae al grupo crudo de la fila solo si no hay usuario
  resuelto.
- **FR-003**: `backend/src/services/budget_service.py::MODEL_PRICING` ahora tiene
  `azure-gpt-5.1-chat` ($1.25/$10 por millón) y `azure-gpt-5.4-mini` ($0.75/$4.50 por
  millón), espejando exactamente `litellm/config.yaml`.
- **FR-004**: `calculate_cost` deja `logger.warning` cada vez que un modelo no está en
  `MODEL_PRICING` y cae al `default` genérico.
- **Verificación (primera ronda, parcial)**: nuevo test de integración
  `backend/tests/integration/test_costs_by_group_attribution_053.py`, corrido contra
  Postgres real (`docker compose up -d db`) y **verificado por mutación** — revertido
  momentáneamente el fix de `costs.py`, el test pasó a fallar; reaplicado, vuelve a pasar.
  Suite completa relacionada corrida sin regresiones: 45 tests (unit + integration) en
  verde. **Esta verificación resultó incompleta** — ver el hallazgo del mismo día más abajo:
  el test inserta la fila de auditoría ya armada a mano, así que confirma que la consulta
  del panel lee bien la columna, pero no probaba si esa columna llegaba a poblarse para el
  tráfico real. Corregido en la segunda ronda (mismo día, ver abajo). Regla de trabajo que
  quedó fijada a partir de este caso: [[regla-verificacion-completa-antes-de-informar]].

#### Hallazgo en vivo (17-sep, misma tarde) — el fix de arriba no alcanzaba para el chat de documentos

Probado en el servidor real de producción (con un usuario y grupo de prueba nuevos, sin tocar
datos de clientes reales) después de desplegar el fix de arriba: el gasto de un usuario real que
manda un mensaje real por el chat de documentos del Hub (RAG, el que usa AnythingLLM) **seguía sin
atribuirse** — el mismo síntoma que reportó Tomás Mc Nally. La causa: `custom_auth.py` (línea
~431) resuelve `acted_for_user_id` a partir de un header propio de Guardian,
`X-Guardian-Acting-User` (`custom_auth.py::_verify_acting_user`). Ese header **solo lo manda el
motor tabular** (`tabular/app/llm.py:32`) — grep exhaustivo del repo confirmó que ningún otro
punto lo setea. AnythingLLM es de terceros: no tiene ninguna forma de saber que ese header existe,
así que para el chat de documentos `acted_for_user_id` **nunca llega a existir en primer lugar**.
El fix de FR-001/FR-002 (leer el campo bien) era necesario pero no alcanzaba: no hay nada que leer
si nadie lo escribió.

**La solución no es enseñarle el header a un producto externo.** Confirmado contra AnythingLLM
real (`curl` directo a `/api/v1/workspace/:slug/chat`): su respuesta ya trae, en `metrics`, los
`prompt_tokens`/`completion_tokens`/`model` reales de la respuesta. El Hub (`client/server.js`) ya
recibe ese payload y ya sabe con certeza quién es la persona (su propia sesión) — no necesita que
AnythingLLM le confirme nada. Mismo patrón que ya usa `chat.py` para "chat directo": el plano que
originó el tráfico escribe su propia fila.

**Implementado (17-sep, segunda ronda)**:
- Nuevo endpoint `POST /chat/rag-usage` (`backend/src/api/chat.py`), autenticado por sesión JWT
  (no virtual key): recibe `model`/`prompt_tokens`/`completion_tokens` del Hub, calcula el costo
  con `BudgetService.calculate_cost` (el Hub nunca manda un costo en dólares, así que no hay un
  segundo lugar donde el precio pueda desalinearse), escribe la fila con
  `AuditService.log_transaction` (`acted_for_user_id`/`user_group_id` de la sesión autenticada,
  `surface="rag"`) y descuenta `BudgetService.update_budget` — cierra de paso el hallazgo ya
  conocido de la spec 043 ("el presupuesto se muestra pero no se aplica en el camino RAG").
- `client/server.js`, rama RAG de `POST /api/chat`: después de la respuesta de AnythingLLM, reporta
  `data.metrics` a `/chat/rag-usage` — best-effort (si falla, no rompe el chat ya servido y pagado).
- **Verificación completa esta vez, exactamente como la haría el cliente**: login real como
  usuario de prueba (no admin, no atajos de API), dos mensajes reales por el chat de documentos del
  Hub contra Azure real, y confirmado en el panel de Costos real (no una query directa a la base)
  que el contador de ese usuario y de su grupo sube de 0 a 1 a 2 peticiones. Repetido primero
  local (`localhost`) y validado el mismo patrón en el servidor real de producción. Más
  `backend/tests/integration/test_rag_usage_053.py` (2 tests: atribución+presupuesto correctos,
  401 sin sesión) para fijar la regresión. Suite completa: 45 tests backend + 43 tests cliente, 0
  fallos.

#### Hallazgo documentado, sin resolver en esta ronda: dos sistemas de tracking que pueden divergir

LiteLLM Proxy trae su propio sistema nativo de spend por key/usuario/team
(`backend/src/api/keys.py:280` → `GET /key/info`; `backend/src/api/users.py:708-729` → `GET
/user/info`, `GET /team/info`) — cuenta TODO el tráfico de una key. El panel de Costos, en cambio,
lee únicamente `audit_logs` (`backend/src/api/costs.py:113-131`, `SUM(cost_usd)`), que tiene dos
escritores independientes: `sentinel_audit_logger.py` y `backend/src/api/chat.py:1858` (que
excluye a propósito el tráfico interno con master key para no duplicar — comentario en
`sentinel_audit_logger.py` ~línea 300). `audit_logs` puede además perder filas si el POST al plano
interno falla, riesgo mitigado pero no eliminado por la spec 031 (`_registrar_perdida`,
`sentinel:audit:lost`). Ambos sistemas derivan del mismo cálculo nativo cuando todo funciona bien,
pero no siempre van a coincidir exactamente. **Pregunta abierta para decidir después**: ¿hace
falta reconciliar ambos números, o es aceptable que el panel de Costos no sea el total exacto del
spend nativo de LiteLLM? No se resuelve en esta spec.

---

### User Story 2 - Tarifario: precio manual al alta de modelo + política del cost map (Priority: P2)

Un administrador da de alta un modelo nuevo (sale uno todo el tiempo) y necesita poder fijarle un
precio si el sistema todavía no lo conoce, en vez de que ese modelo quede facturando silenciosamente
al precio genérico por defecto. El producto además necesita una decisión explícita, documentada,
sobre cómo se actualizan los precios en el tiempo — hoy depende de un comportamiento heredado de
fábrica que nadie decidió a propósito.

**Por qué esta prioridad**: es la causa raíz de fondo del defecto #3 de la User Story 1 (el precio
de respaldo desalineado), y responde directamente a la preocupación del dueño del producto de no
perder la capacidad de mantenerse al día con modelos y precios que cambian todo el tiempo. No
bloquea el viernes 18/9 (el fix puntual de precios de esos dos modelos en la User Story 1 sí lo
hace), pero sin esto el mismo problema se repite con el próximo modelo nuevo.

**Independent Test**: puede probarse dando de alta un modelo ficticio con precio manual vía
`POST /models` y verificando que una petición contra ese modelo se factura al precio cargado, sin
pasar por el fallback genérico — sin tocar ningún otro flujo del producto.

**Acceptance Scenarios**:

1. **Given** un administrador dando de alta un modelo nuevo, **When** completa el formulario de
   alta, **Then** puede opcionalmente fijar el precio de entrada y de salida por token, sin
   depender de que el sistema lo resuelva solo.
2. **Given** un modelo dado de alta sin precio manual, **When** el sistema necesita calcular su
   costo, **Then** intenta primero el mecanismo de resolución automática de LiteLLM antes de caer
   en cualquier valor genérico.
3. **Given** una instalación del cliente sin salida a internet desde el contenedor del motor,
   **When** se despliega o actualiza, **Then** existe un proceso documentado y explícito (no
   implícito) para mantener el catálogo de precios al día, acorde al modo de conectividad real de
   esa instalación.
4. **Given** el motor corriendo normalmente con salida a internet, **When** pasa el intervalo
   programado de reload, **Then** el mapa de precios se refresca solo, sin reiniciar el
   contenedor.

#### Diagnóstico verificado (file:line)

- **El catálogo de modelos elegibles sí se mantiene al día sin trabajo manual pesado.** La spec
  033 (`litellm/supervisor.py`, watcher de `config.yaml` con coalescencia y drenaje;
  `POST /models` en `backend/src/api/chat.py:2151-2153`; `GET/POST /models/status` en
  `chat.py:2445`; `POST /models/apply` en `chat.py:2512`) **ya está implementada e integrada en
  `deploy/docker/compose.prod.yml:225`** (`entrypoint: ["python", "/app/config/supervisor.py"]`,
  vars `SENTINEL_ENGINE_AUTORELOAD`/`_APPLY_DEBOUNCE_SECONDS`/`_DRAIN_SECONDS` ya cableadas) — el
  motor recarga solo, sin SSH ni restart manual. El frontend refleja `config.yaml` en vivo
  (`GET /models` → `chat.py:2053-2054`, lee el YAML en cada llamada). **Esto contradice
  `specs/ROADMAP-pisos.md` (líneas ~45, 51: "🔨 por construir") y
  `specs/033-engine-reload-restart-ui/tasks.md` (T001-T006 sin marcar)** — es deuda de
  documentación, no de código; se anota abajo en "Huecos de documentación", no se corrige acá.
  Pendiente real de confirmar: `litellm/Dockerfile` (el de DEV, no el compose de prod) todavía
  tiene `ENTRYPOINT ["litellm", "--config", ...]` sin supervisor — verificar si dev también migró.
- **`POST /models` no admite precio manual hoy**: `ModelCreateSchema`
  (`backend/src/api/chat.py:2046-2052`) solo tiene `model_name`, `provider`, `model_id`,
  `api_key`, `api_base` — sin `input_cost_per_token`/`output_cost_per_token`. Un modelo dado de
  alta por la UI nace sin precio manual, dependiendo 100% de la resolución automática de LiteLLM.
- **Cómo resuelve LiteLLM el precio por defecto** (paquete instalado, litellm 1.95.1,
  `backend/.venv/lib/python3.12/site-packages/litellm/`): por defecto **intenta traer el mapa de
  precios desde GitHub en cada arranque del proceso** —
  `litellm/__init__.py:402-405` (`model_cost_map_url`, default
  `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`),
  ejecutado en el import (`litellm/__init__.py:518`). Si falla la red o la validación de
  integridad, cae al JSON local embebido en el paquete
  (`model_prices_and_context_window_backup.json`, 2979 entradas, ya incluye `azure/gpt-5.5` y
  `azure/gpt-4.1-mini`). El modo 100% offline se activa con `LITELLM_LOCAL_MODEL_COST_MAP=true`
  (`litellm/litellm_core_utils/get_model_cost_map.py:1-9, 250-283`) — **confirmado que ninguna de
  las dos env vars (`LITELLM_LOCAL_MODEL_COST_MAP`, `LITELLM_MODEL_COST_MAP_URL`) está seteada en
  ningún compose/Dockerfile/.env del repo**: el mecanismo remoto está activo por comportamiento de
  fábrica, nadie lo decidió a propósito.
- **El motor está pineado por digest de imagen Docker**: `litellm/Dockerfile:8`,
  `FROM ghcr.io/berriai/litellm:main-latest@sha256:...` con comentario propio ("al actualizar,
  correr la suite de contract tests antes de commitear el digest nuevo") — solo avanza cuando
  alguien lo hace a mano. En una instalación on-prem/air-gapped (el modo típico de despliegue de
  este producto, ver `deploy/clients/*`), el fetch remoto de precios puede fallar silenciosamente
  y caer al JSON congelado del build de esa imagen.
- **Consecuencia combinada**: un modelo verdaderamente nuevo que ni el remoto ni el backup local
  conozcan, dado de alta sin precio manual (porque `POST /models` no lo permite), cae directo en
  el `default` genérico de `budget_service.py` — el mismo mecanismo del defecto #3 de la User
  Story 1. Este hallazgo es la causa raíz de fondo, no un hallazgo separado.
- **Punto D del roadmap de la spec 050** ("tarifario centralizado... conectar una fuente pública de
  precios de modelos para actualización sin mantenimiento manual", `specs/ROADMAP-pisos.md`
  sección de Control de costos) ya apuntaba en esta dirección — esta User Story lo concreta.

#### Investigado a pedido del dueño (17-sep): el mecanismo de actualización de LiteLLM, y qué NO construir

El dueño vio en el repo de LiteLLM algo sobre actualización de modelos "en tiempo real" y pidió
entender si ya está resuelto, para no construir una capa propia si el motor ya lo hace.
Investigado contra la documentación oficial de LiteLLM (docs.litellm.ai) — cambia el diseño de
esta User Story respecto a la primera versión de esta spec:

- **El fetch remoto de precios NO es tiempo real — es "mejor esfuerzo", sin SLA.** El archivo
  `model_prices_and_context_window.json` lo actualiza el equipo de LiteLLM a mano vía pull
  requests, sin bot ni scraping automatizado de precios de proveedores; puede tardar horas o días
  en reflejar un modelo recién lanzado. Si el fetch falla, el proceso cae **en silencio** al JSON
  embebido del paquete, sin marcar error ni fallar el healthcheck.
- **Hay un mecanismo que no habíamos visto y sí conviene usar**: LiteLLM expone
  `POST /schedule/model_cost_map_reload?hours={n}` para programar un re-fetch periódico **sin
  reiniciar el contenedor** (además de `POST /reload/model_cost_map` para forzarlo a mano). Dado
  que nuestro motor corre en un contenedor de larga vida con la imagen pineada por digest
  (`litellm/Dockerfile:8`), programar este reload (por ejemplo cada 6-12h) mitiga la mayor parte
  del riesgo de precios desactualizados **sin tocar el pipeline de build de la imagen**. Bajo
  costo, alto impacto — se agrega como FR-006 revisado abajo.
- **Existe auto-descubrimiento de modelos ("Model Discovery") + wildcard routing**
  (`check_provider_endpoint: true` + una entrada `azure/*`/`openai/*` en `model_list`) que
  eliminaría la necesidad de dar de alta cada modelo a mano — confirmado para OpenAI, Anthropic,
  Gemini y otros proveedores en la documentación; **Azure no aparece confirmado explícitamente**,
  y tampoco está confirmado que el precio se resuelva automáticamente para un modelo descubierto
  por wildcard (sigue dependiendo del cost map del punto anterior). Como nuestro catálogo de
  producción es 100% Azure, esto queda como **spike a probar antes de comprometer alcance**, no
  como solución ya confirmada — ver FR-006 revisado.
- **Hallazgo importante — nuestro plan original de agregar un campo de precio a `POST /models`
  reinventaba algo que LiteLLM ya tiene.** LiteLLM soporta nativamente precio manual por modelo
  vía `model_info` (`input_cost_per_token`/`output_cost_per_token`, y más granular
  `cache_creation_input_token_cost`, etc.) — es exactamente el mecanismo que **ya usamos a mano**
  hoy para `azure-gpt-5.1-chat`/`azure-gpt-5.4-mini` en `litellm/config.yaml`. Nuestro
  `POST /models` (`chat.py:2151`, spec 033) ya escribe entradas nuevas en `model_list` de ese mismo
  `config.yaml` — **no hace falta inventar un esquema de precios propio**, alcanza con que el
  endpoint que ya existe acepte también los dos campos nativos de `model_info` y los escriba en el
  mismo YAML, tal como ya está el patrón manual. Es reusar un campo nativo de LiteLLM a través de
  nuestro propio endpoint de alta, no construir un sistema de pricing paralelo.
  Existe también un camino nativo alternativo (`STORE_MODEL_IN_DB=true` + `POST /model/new` +
  Admin UI, con auto-completado de precio desde el cost map) — **no se adopta en esta spec**
  porque implicaría migrar de nuestro mecanismo file-based (`config.yaml` + supervisor, ya
  funcionando desde la spec 033) al mecanismo de base de datos nativo de LiteLLM, un cambio de
  arquitectura mayor que no está justificado solo para resolver el campo de precio faltante.

---

### User Story 3 - Restricción de `.csv`/`.xlsx` en el chat RAG, motor tabular como única vía (Priority: P2) — 🟢 IMPLEMENTADA (17-sep)

Un administrador quiere evitar que las personas suban planillas al espacio de trabajo del chat
general, para que las consultas sobre `.csv`/`.xlsx` pasen siempre por el motor tabular (cálculo
exacto vía SQL), no por el RAG vectorial (búsqueda semántica aproximada), reduciendo el riesgo de
mal uso y de respuestas incorrectas sobre datos tabulares.

**Por qué esta prioridad**: pedido explícito del cliente, pero no bloquea el arranque del piloto
del lunes 21/9 de la misma forma que la User Story 1 — es una restricción preventiva, no una
corrección de un número que ya está mal hoy.

**Independent Test**: puede probarse subiendo un archivo `.csv` al panel "Documentos del Espacio"
del chat normal y verificando que se rechaza con un mensaje que dirige al flujo tabular, sin tocar
el flujo de "Planillas del Espacio" (tabular), que debe seguir aceptando esos mismos archivos sin
cambios.

**Acceptance Scenarios**:

1. **Given** un usuario en la pestaña de chat normal (Espacio de Trabajo / RAG), **When** intenta
   subir un archivo `.csv` o `.xlsx` en "Documentos del Espacio", **Then** el selector de archivos
   del navegador no lo ofrece como opción seleccionable.
2. **Given** un usuario que de todos modos consigue seleccionar un `.csv`/`.xlsx` (navegador que
   ignora `accept`, o un script), **When** intenta subirlo, **Then** el cliente lo rechaza antes de
   llamar al servidor, con un mensaje que sugiere usar "Planillas del Espacio".
3. **Given** una petición directa al servidor que se salta el cliente (bypass del front),
   **When** llega `POST /api/workspaces/upload` con un archivo `.csv`/`.xlsx`, **Then** el
   servidor responde 415 y no indexa el archivo.
4. **Given** el flujo tabular ("Planillas del Espacio"), **When** se sube un `.csv`/`.xlsx` ahí,
   **Then** el comportamiento no cambia respecto a hoy.

#### Diagnóstico verificado (file:line)

- **El chat normal corre sobre AnythingLLM** (motor de RAG vectorial): `client/server.js:20`
  (`ANYTHINGLLM_URL`), wrapper `anythingllmFetch()` (`client/server.js:144-152`). Endpoint de
  subida: `POST /api/workspaces/upload` (`client/server.js:798-849`) — extrae texto con
  `extractText()` (`client/extract_text.py`) y lo indexa en AnythingLLM. **Sin ninguna validación
  de extensión hoy**, ni en el input del navegador (`client/public/index.html:603`, sin `accept`)
  ni en el handler (`handleWsFileUpload`, `client/public/index.html:1485-1502`) ni en el servidor
  (`multer`, `client/server.js:56-63`, sin `fileFilter`).
- **El motor tabular es un servicio propio con DuckDB**, separado del RAG
  (`elea/tabular/README.md`; decisión sellada en `specs/050-ia-hub-conector-motores/spec.md:34-
  35`, "Excel = servicio propio tabular con DuckDB, reemplaza a DB-GPT"). Su endpoint ya valida
  correctamente: `POST /api/tabular/workspaces/:id/files` (`client/server.js:1099-1122`),
  `if (!['csv', 'xlsx'].includes(ext)) return res.status(415)...` con mensaje "Este modo solo
  acepta planillas .csv y .xlsx — para otro tipo de documento, usá el chat normal." Este endpoint
  **no se toca** en esta spec.
- **Dos secciones de UI ya visibles y separadas**: "Documentos del Espacio" (chat normal,
  `client/public/index.html:594-603`) vs. "Planillas del Espacio" / "Espacio de Planillas"
  (tabular, `client/public/index.html:822-861`, botón "⬆ Subir planilla", input con
  `accept=".csv,.xlsx"` ya puesto, texto de ayuda explícito sobre respuesta exacta vs.
  aproximación).
- **Efecto colateral real, decisión consciente del dueño (17-sep)**: subir `.xlsx`/`.csv` al RAG
  general hoy es una función intencional y ya reparada de un bug real el 31-ago
  (`client/extract_text.py:38-58`, rama explícita para `.xlsx`/`.xls` vía `pandas`, hasta 5000
  filas, comentario propio: "cualquier pregunta sobre el resto de una planilla real quedaba sin
  respuesta"; comentario también aclara el límite de alcance: "si hace falta más, es un caso para
  DB-GPT [ahora tabular]... no para el RAG vectorial"). Es decir: hoy hay un uso legítimo y ya
  construido de subir planillas al RAG — búsqueda semántica aproximada sobre su contenido (ej.
  "¿qué dice la fila donde menciona tal cliente?"), distinto del cálculo/agregación exacta del
  motor tabular. **Bloquear esas extensiones en el flujo AnythingLLM elimina esa capacidad**,
  dejando el motor tabular como única vía para `.csv`/`.xlsx`. El dueño decidió proceder así,
  priorizando el pedido explícito del cliente sobre conservar la búsqueda aproximada.

#### Implementación (17-sep) — FR-009 a FR-011

- **FR-009 (servidor)**: `client/server.js`, `POST /api/workspaces/upload` — rechazo con 415
  apenas llega el archivo (antes de chequear membresía del espacio, para no gastar esa llamada al
  backend en un archivo que se va a rechazar igual), si `req.file.originalname` termina en
  `.csv`/`.xlsx`. Borra el archivo temporal que `multer` ya había guardado en disco, para no dejar
  huérfanos.
- **FR-009 (cliente)**: `client/public/index.html`, `handleWsFileUpload()` — mismo chequeo de
  extensión ANTES de llamar a `fetch`, por si el navegador ignora el `accept` del input.
  `ws-file-input` ahora tiene `accept=".pdf,.doc,.docx,.ppt,.pptx,.txt,.md,image/*"` (positivo, no
  negativo — más robusto que enumerar lo prohibido).
- **FR-010**: el mensaje de rechazo, igual en cliente y servidor, dirige explícitamente a
  "Planillas del Espacio" ("las planillas .csv y .xlsx no se suben acá — usá 'Planillas del
  Espacio' para consultarlas con cálculo exacto").
- **FR-011**: cero líneas tocadas del endpoint tabular
  (`POST /api/tabular/workspaces/:id/files`) — confirmado por diff y por prueba en vivo.
- **Verificación EN VIVO (17-sep)**, contra el stack real levantado con `docker compose up`, no
  solo contra tests: login real como `admin` vía `POST /api/auth/login`, después tres subidas
  reales por HTTP a `POST /api/workspaces/upload` con un `.csv`, un `.xlsx` y un `.txt` de
  prueba — los dos primeros devolvieron 415 con el mensaje esperado, el `.txt` devolvió 200 y quedó
  indexado igual que antes del cambio. Confirmado además con JavaScript en la página real que
  `document.getElementById('ws-file-input').accept` ya trae la whitelist nueva. El endpoint
  tabular se probó aparte y devolvió 403 por control de acceso normal (workspace de otro tipo),
  no por nada relacionado a esta spec — confirma que ese código no se tocó.
- **Verificación automatizada**: `client/tests/unit/workspace-upload-restriccion-tabular-053.test.js`
  (3 tests: rechaza `.csv` sin llegar a pedirle nada al motor de documentos, rechaza `.xlsx`, no
  rompe un `.txt` normal). Suite completa del cliente corrida: 43 tests, 0 fallos.

### Edge Cases

- Tráfico que pasa por el motor con una identidad que no resuelve a ningún usuario real (por
  ejemplo, una integración externa por API key sin `acted_for_user_id` asociable): ¿debe seguir
  cayendo en "sin grupo"/cuenta de servicio, o el panel necesita una categoría explícita para
  "tráfico de integración" distinta de "sin atribuir por bug"? No se resuelve en esta spec, queda
  como pregunta para quien implemente US1.
  - Un modelo dado de alta con precio manual (US2) que luego SÍ aparece en el mapa remoto de
    LiteLLM con un precio distinto: ¿gana el precio manual o el remoto? Definir la precedencia al
    implementar; se sugiere que el precio manual, si está seteado, siempre gane (evita que un
    fetch remoto pise una decisión deliberada del administrador).
- Un usuario que ya tenía archivos `.csv`/`.xlsx` indexados en el RAG antes de este cambio (US3):
  el bloqueo es solo sobre subidas nuevas, no se especifica limpieza retroactiva de lo ya indexado
  — a decidir si hace falta.

## Requirements *(mandatory)*

### Functional Requirements

**US1 — Atribución y precisión de costos**

- **FR-001**: El sistema DEBE incluir la identidad de la persona real (`acted_for_user_id`) en
  toda fila de auditoría de una petición exitosa servida por el motor, no solo en las filas de
  bloqueo.
- **FR-002**: La consulta de gasto por grupo DEBE resolver el grupo a través del usuario real
  detrás de la petición, con el mismo criterio que ya usa la consulta de gasto por usuario.
- **FR-003**: El cálculo de costo de respaldo (cuando el header nativo del motor no informa el
  costo) DEBE usar el precio real de cada modelo de producción vigente, no un valor genérico
  desalineado del catálogo actual.
- **FR-004**: Toda vez que se use el precio de respaldo genérico (no el precio específico de un
  modelo conocido), el sistema DEBE dejar traza auditable de que ocurrió.
- **FR-012** (hallazgo en vivo, segunda ronda): el gasto de una petición servida por el chat de
  documentos (motor de terceros que no puede transportar identidad de Guardian) DEBE atribuirse a
  la persona real y a su grupo, y DEBE descontarse de su presupuesto — sin depender de que ese
  motor externo coopere.

**US2 — Tarifario**

- **FR-005**: El alta de un modelo nuevo (`POST /models`) DEBE permitir fijar opcionalmente su
  precio de entrada y de salida por token, escribiéndolo en los campos nativos de `model_info` de
  LiteLLM (`input_cost_per_token`/`output_cost_per_token`) dentro de `config.yaml` — mismo patrón
  ya usado a mano para los dos modelos de producción actuales, sin esquema de precios propio.
- **FR-006**: El motor DEBE tener programado un re-fetch periódico del mapa de precios de LiteLLM
  (`POST /schedule/model_cost_map_reload`) para reducir la ventana de desactualización sin
  depender de reconstruir la imagen Docker.
- **FR-007**: La política de actualización del catálogo de precios (remoto con reload periódico
  vs. local, y el proceso para instalaciones sin salida a internet) DEBE quedar documentada
  explícitamente, no heredada implícitamente del comportamiento de fábrica de LiteLLM.
- **FR-008 (spike, no comprometido)**: Evaluar `check_provider_endpoint: true` + wildcard routing
  (`azure/*`) contra el Azure real de producción, para confirmar si elimina la necesidad de dar de
  alta cada modelo a mano y si resuelve también su precio automáticamente. Si funciona, reduce el
  alcance de FR-005 a un caso de respaldo en vez de un flujo principal.

**US3 — Restricción de archivos**

- **FR-009**: El sistema DEBE rechazar la subida de archivos `.csv`/`.xlsx` al flujo de RAG
  general (Documentos del Espacio), tanto en el cliente como en el servidor.
- **FR-010**: El mensaje de rechazo DEBE dirigir al usuario al flujo tabular ("Planillas del
  Espacio") como alternativa correcta.
- **FR-011**: El flujo tabular existente NO DEBE modificarse por esta spec.

### Key Entities

- **Audit log entry (`audit_logs`)**: fila que representa una petición al motor; hoy le falta
  `acted_for_user_id` en el camino de éxito. Ya tiene la columna, no requiere migración.
- **Modelo (entrada de `model_list` en `config.yaml`)**: catálogo de modelos elegibles; hoy no
  tiene campo de precio manual en su alta por API.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Después del fix, el gasto por usuario de una cuenta real que hace N peticiones
  nuevas vía el motor sube en N, verificable comparando el conteo de peticiones del panel contra
  peticiones reales hechas en una prueba controlada.
- **SC-002**: El gasto por grupo de un usuario con grupo asignado deja de caer bajo "sin grupo"
  para tráfico nuevo.
- **SC-003**: Cero peticiones a `azure-gpt-5.1-chat` o `azure-gpt-5.4-mini` facturadas al precio
  genérico por defecto, medido sobre una muestra de auditoría posterior al fix.
- **SC-004**: Un archivo `.csv`/`.xlsx` no puede terminar indexado en el RAG general después del
  cambio, ni por el flujo normal del navegador ni por una petición directa al servidor.
- **SC-005**: El flujo tabular sigue aceptando y procesando `.csv`/`.xlsx` sin regresión, verificado
  con una prueba manual sobre "Planillas del Espacio" después del cambio.

## Assumptions

- El fix de US1 (atribución + precio de los dos modelos de producción) es el que se prioriza para
  el viernes 18/9; US2 (tarifario general) y US3 (restricción de archivos) pueden entregarse
  después sin bloquear el piloto del lunes 21/9, salvo que el dueño decida lo contrario.
- Para US3, el dueño ya decidió (17-sep) proceder con el bloqueo total pese al efecto colateral
  identificado (pérdida de búsqueda semántica aproximada sobre planillas en el RAG); no se vuelve
  a preguntar al implementar.
- El hallazgo de los dos sistemas de tracking que pueden divergir (Bloque A #4 / hallazgo bajo
  US1) queda fuera de alcance de implementación en esta spec; solo se documenta.
- La corrección de `specs/ROADMAP-pisos.md` y `specs/033-engine-reload-restart-ui/tasks.md`
  (desactualizados respecto al código real de la spec 033) no es tarea de esta spec — queda
  anotada en `specs/README.md`, sección de huecos de documentación, para que se corrija aparte.
