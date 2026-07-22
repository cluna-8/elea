# Research (Fase 0): Governance configurable y enforcement honesto del firewall

**Feature**: 027 | **Fecha**: 2026-07-22 | **Spec**: [spec.md](./spec.md)

Investigación paralela sobre el código real (5 lectores, 159 lecturas). Cada decisión cita
`archivo:línea` verificable. Lo que sigue son **decisiones de diseño**, no requisitos: los
requisitos están en la spec y no cambian salvo donde se indica explícitamente (ver D8).

---

## Resumen de decisiones

| # | Incógnita | Decisión |
|---|---|---|
| D1 | Catálogo de capas | **En código** (registry inmutable), no en DB |
| D2 | Dónde vive la configuración | **Entidad nueva** `GovernanceProfile`, fila por decisión |
| D3 | Cómo se resuelve el perfil | **Resolutor puro compartido** en `basa_guardian_policy`, un solo lugar para los 3 planos |
| D4 | Cómo se computa el estado real | **Declarativo + sonda al motor + evidencia por pedido**, fail-closed, nunca persistido |
| D5 | Ejes de alcance | Modo con **función de mapeo explícita**; superficie anclada en `tool_type`, jamás en User-Agent; relajar solo con **superficie confiable** |
| D6 | Atribución por pedido | Campos **nuevos** `applied_layers` + `blocked_by_layer`; `guardian_events` congelado |
| D7 | Superficie Admin | **Página propia** "Gobernanza" + autosave con rollback (no botón global) |
| D8 | Piso vs. toggle existente | El piso es **detectar/evaluar/registrar**; el enmascarado se gobierna. **Confirmada por el owner (2026-07-22)** |

---

## D1 — El catálogo de capas vive en código, no en la base

**Decisión**: un registry inmutable (`GOVERNANCE_LAYERS`) declara cada capa con
`layer_key` estable, `tier` (`floor` \| `optional`), `plane` (`gateway` \| `engine` \| `backend`),
`requires_credential` y `delegable_to_upstream`. La tabla `guardians` sigue siendo la
**instancia configurable** de las capas opcionales (credencial, `fail_mode`, `apply_on`),
enlazada por `layer_key` — **nunca por FK**.

**Por qué**:
- Hace **SC-004 estructuralmente cierto**: si el piso es una constante de código, no existe
  columna que lo apague, así que no hay "camino de configuración" que auditar. Un piso definido
  como fila de DB es un piso que alguien puede borrar con un `UPDATE`.
- La FK es una bomba: `get_or_create_default_guardians` hace `db.query(Guardian).delete()` de
  **toda la tabla** y re-siembra cuando hay menos de 9 filas
  ([guardian_service.py:33-36](../../backend/src/services/guardian_service.py#L33)), sin filtrar
  por tenant. Cualquier configuración colgada de `guardians.id` se pierde en cascada en el
  próximo arranque.
- La DB ya demostró que se desincroniza del runtime: los 5 `engine_guardrail_name` sembrados
  ([guardian_service.py:74-121](../../backend/src/services/guardian_service.py#L74), y de nuevo en
  `alembic/versions/002_guardian_engine_fields.py:29-65`) apuntan a guardrails que **no existen
  en el motor**.

**Alternativas descartadas**:
- *Catálogo en DB con `tier`*: reintroduce el piso apagable y hereda el seed destructivo.
- *Usar `Guardian.is_active` como decisión por alcance*: es un booleano **global** sin alcance
  ([guardian.py:15](../../backend/src/models/guardian.py#L15)); no puede expresar "activo para
  modelos de la pasarela, inactivo para suscripción".

**Riesgo**: cambiar la cardinalidad del catálogo dispara el re-seed destructivo. **Neutralizar esa
rama es prerrequisito de la primera tarea**, antes de tocar nada del catálogo.

---

## D2 — Entidad nueva `GovernanceProfile`, sin tocar `SecurityPolicy`

**Decisión**: tabla nueva, **una fila por decisión**:

```
governance_profiles(
  id, tenant_id FK tenants.id DEFAULT DEFAULT_TENANT_ID (index),
  scope_type, scope_value, layer_key, decision,
  updated_by, created_at, updated_at
)
UNIQUE (tenant_id, scope_type, scope_value, layer_key)
CHECK  scope_type IN ('tenant_default','connection_mode','surface')
CHECK  decision   IN ('on','off')
```

La **ausencia de fila es "heredar"** — el mismo idioma `NULL=heredar` que ya usa el producto
([budget.py:71-73](../../backend/src/models/budget.py#L71)). Escribir una fila con un `layer_key`
de `tier=floor` devuelve **422 y se audita** (FR-003).

**Por qué no `SecurityPolicy`**:
- No es multi-tenant en la práctica pese a tener `tenant_id`: el lector real es
  `db.query(SecurityPolicy).first()` **sin filtrar tenant ni `is_active`**
  ([policy.py:34](../../backend/src/api/policy.py#L34), repetido en :59, :66, :141, y clonado en
  `costs.py:277-279`). Colgar gobernanza de ahí hereda el bug: la postura de un tenant se
  resolvería con datos de otro.
- Mantiene **un solo activo global** apagando el resto en cada escritura
  ([policy.py:88-90, 111-113](../../backend/src/api/policy.py#L88)); el eje modo×superficie exige
  N filas activas a la vez, lo que rompe ese invariante ya codificado.
- Su eje es *"qué entidades PII y con qué acción"*, no *"qué capas corren para este alcance"*, y su
  propio comentario reserva la cascada a la spec 015
  ([policy.py:12-13](../../backend/src/models/policy.py#L12)).

**Precedente que sí se copia**: `ComplianceProject`
([compliance.py:13-34](../../backend/src/models/compliance.py#L13)) — perfil nombrado por tenant,
referenciado por clave, sin columnas espejo en `Tenant`.

**Alternativas descartadas**: columnas nuevas en `Tenant` (repetiría el antipatrón de las 5
columnas espejo de compresión, `tenant.py:46-50`, multiplicado por capas×modos); un JSONB único
(pierde UNIQUE, CHECKs y granularidad de auditoría por cambio).

**Límite con 015 — deliberado**: el enum de `scope_type` queda **cerrado** a
`tenant_default|connection_mode|surface`. Agregar `group`/`client` "porque es barato" sería
apropiarse del mecanismo que la 015 debe definir. Queda documentado como punto de enganche.

---

## D3 — Un solo resolutor, en la librería que los planos ya comparten

**Decisión**: `resolve_profile(mode, surface, config) -> Profile` + `apply_layers(profile, …)` como
**funciones puras** en `litellm/extensions/basa_guardian_policy.py` — el único archivo que los dos
planos ya importan ([gateway.py:76](../../backend/src/api/gateway.py#L76),
[basa_guardrail.py:40](../../litellm/extensions/basa_guardrail.py#L40)). El piso se **construye
dentro del `Profile`** y no es representable como apagado.

**Precedencia determinista** (FR-006), de mayor a menor:

```
piso (siempre, no participa de la cascada)
  └── Connection (override por-key existente, solo capas que lo declaran: pii_masking vía redact_enabled)
        >  superficie confiable  >  modo de conexión  >  default de tenant  >  default de producto
```

Con `_first_not_none` y `NULL=heredar`, exactamente el contrato ya vigente
([context_resolution.py:23-27](../../backend/src/services/context_resolution.py#L23), espejado en
[custom_auth.py:86-90](../../litellm/extensions/custom_auth.py#L86)). La 015 se enchufa después
insertando dos niveles más en la **misma** lista, sin cambiar el contrato.

**Por qué ahí y no en un servicio del backend**: hay **tres** planos que aplican política y hoy no
comparten resolución — el guardrail del motor
([basa_guardrail.py:74-101](../../litellm/extensions/basa_guardrail.py#L74)), el proxy propio `/gw`
([gateway.py:479-482](../../backend/src/api/gateway.py#L479)) y el chat UI vía
`GuardianService.process_prompt` ([guardian_service.py:149-357](../../backend/src/services/guardian_service.py#L149)).
Si el resolutor no es único, **027 se implementa tres veces y SC-003 se vuelve infalsificable**.
Es el mismo mecanismo con el que la 014 garantizó paridad, con su contract test
(`tests/contract/test_route_parity.py`).

**Modo y superficie NO hay que propagarlos desde afuera** — ya están en cada punto:
- El modo es **constante del plano**: `_detect_mode_and_key` retorna byok antes de la política
  ([gateway.py:473-475](../../backend/src/api/gateway.py#L473)), así que al gateway solo llega
  suscripción; y todo lo que llega al motor es modelo-de-pasarela.
- La superficie ya está resuelta en el call-site: `tool` en
  [gateway.py:478](../../backend/src/api/gateway.py#L478) y `ident['tool_type']` en :246; y en el
  motor viene en `metadata['basa']` ([custom_auth.py:146-147](../../litellm/extensions/custom_auth.py#L146)).

Falta **propagar un argumento**, no información.

**Alternativas descartadas**:
- *Resolver en el gateway y pasarlo al motor por header*: el motor es alcanzable directamente
  (puerto 4010, `docker-compose.yml:44`) → un perfil inyectado sería **bypasseable**.
- *Leer `Guardian` desde el guardrail del motor*: imposible por topología (ver Prerrequisito P1) y
  acopla el marco al catálogo, que es de otro módulo.
- *Resolver dentro del propio hook*: metería I/O de DB en el camino caliente por request.

**Consumo en el motor**: se agrega el perfil resuelto al SQL de identidad y al dict `basa` de
`custom_auth` ([custom_auth.py:49-62, 137-157](../../litellm/extensions/custom_auth.py#L137)),
aprovechando el cache existente. **Gotcha**: ese cache es de 60 s por `key_hash`
([custom_auth.py:64-66](../../litellm/extensions/custom_auth.py#L64)) → un cambio de gobernanza
tarda hasta un minuto en aplicarse. Se invalida la entrada por key al escribir; si no, SC-006 se
lee como falso.

---

## D4 — El estado real se **calcula**, con tres fuentes y default inseguro

**Decisión**: `estado_efectivo` nunca se persiste. Se computa como el join de tres fuentes que
responden preguntas distintas:

| Fuente | Pregunta | Implementación |
|---|---|---|
| **A. Declarativo** (código) | ¿Qué *es* la capa? | El registry de D1 |
| **B. Sonda al motor** | ¿Está *cargada*? | `GET /guardrails/list`, cacheada ~30 s |
| **C. Evidencia por pedido** | ¿*Corrió* en este pedido? | header `x-litellm-applied-guardrails` |

**Función de estado, con default inseguro**:

```
NO_DISPONIBLE            (default)
→ REQUIERE_CREDENCIAL    si deseada ∧ requires_credential y no hay credencial
                         (una capa apagada por decisión reporta NO_DISPONIBLE, no un
                          falso "te falta credencial")
→ DELEGADA               solo si el registry declara delegación para ese modo (con motivo)
→ APLICANDOSE            solo si  deseado ∧ sonda confirma ∧ (evidencia reciente ∨ capa de piso)
→ DEGRADADA              si estuvo presente y dejó de estarlo
```

`is_active` deja de ser "estado" y pasa a llamarse explícitamente **"deseado"**.

**Verificado en vivo** contra el contenedor `basa-litellm`: `GET /guardrails/list` con la master key
devuelve **una sola** entrada, `basa-guardian`. Los 5 nombres de proveedor del seed no existen.

**El hallazgo que justifica el default inseguro**: LiteLLM **ignora en silencio** los nombres de
guardrail desconocidos — no hay validación en `move_guardrails_to_metadata`, y cada guardrail decide
con `should_run_guardrail` comparando contra *su propio* nombre. Un nombre inexistente no matchea,
no rompe y **no deja rastro**. Activar "Filtro de Contenido Inapropiado" en la UI hoy es literalmente
un no-op silencioso.

**Las 6 cosas concretas para que nunca se reporte activa una capa que no corre**:
1. Matar las derivaciones falsas de `is_active` en
   [SecurityPage.tsx:204](../../frontend/src/pages/SecurityPage.tsx#L204) (y :183/:199/:215) y
   [DashboardPage.tsx:71](../../frontend/src/pages/DashboardPage.tsx#L71).
2. `GET /guardians` computa y devuelve `status`/`reason`/`plane`. Mantiene
   `engine_guardrail_name=None` ([guardians.py:57](../../backend/src/api/guardians.py#L57)) —
   el estado se expone, el nombre de proveedor **no** (Principio VII).
3. **Borrar el trigger fabricado** de
   [guardian_service.py:334-347](../../backend/src/services/guardian_service.py#L334): hoy sintetiza
   `{"guardian": "Motor de IA", "action": "DELEGATED", "detail": "Guardianes activos en motor: …"}`
   leyendo **solo la DB**, y eso se persiste como evidencia de auditoría
   ([chat.py:562](../../backend/src/api/chat.py#L562)). Es la mentira, con nombre y línea.
4. Gate en escritura: activar una capa cuyo `engine_guardrail_name` no está en la sonda no puede
   devolver 200-verde; acepta el deseo y responde `status: no_disponible` con motivo.
5. Fail-closed real: motor inalcanzable → `no_disponible`, **jamás** `aplicándose`, con copy que
   distinga "no lo aplicamos nosotros" de "estás desprotegido" (FR-013).
6. **Test de contrato** que da SC-001: para toda capa con `status == aplicándose ∧ plane == engine`,
   su nombre ∈ `set(/guardrails/list)`. Corre contra la imagen pineada por digest
   (`docker-compose.yml:40`), así un upgrade del motor falla el gate en vez de fallar en producción.

**Alternativas descartadas**:
- *Parsear `litellm/config.yaml` desde el backend* (tentador: ya está montado, `docker-compose.yml:114`,
  y `gateway.py:68-76` lee de ahí). El archivo en disco **no es** lo que el proceso cargó: hay
  interpolación `os.environ/…` y el motor admite guardrails en DB. Leer un YAML y afirmar "corre"
  reproduce exactamente la clase de mentira que 027 viene a eliminar.
- *`test_guardrail` como sonda de salud* ([ai_engine_client.py:196-212](../../backend/src/services/ai_engine_client.py#L196)):
  hace una llamada LLM real **facturable** con modelo hardcodeado y mapea "cualquier 400 ⇒ blocked".
  Como los nombres desconocidos no producen 400 sino silencio, devuelve `blocked: False` —
  indistinguible de "la capa corrió y no bloqueó".
- *Solo la evidencia por pedido*: una capa sin tráfico reciente quedaría "no disponible" por ausencia
  de datos.
- *Reconciliación por escritura* (que el backend registre guardrails en el motor): eso es **cablear
  capas**, explícitamente Out of Scope (módulo de seguridad).

**El estado se reporta por (plano, superficie), no global** (FR-010): `/v1/responses` está excluido
por `_TEXT_CALL_TYPES` ([basa_guardrail.py:43](../../litellm/extensions/basa_guardrail.py#L43)) y
corre con **cero** política — debe reportarse "no gobernada" explícitamente (issue #28). Un estado
global escalar volvería a mentir, solo que más fino.

---

## D5 — Los ejes de alcance: mapeo explícito, y superficie que solo suma

**Modo de conexión ≠ `upstream_mode` crudo.** La columna existe con CHECK
(`subscription-passthrough|byok`, [budget.py:92-95](../../backend/src/models/budget.py#L92)) pero:
- Es la **intención declarada** de la Connection, mientras el ruteo real lo decide la presencia de
  una `sk-basa-…` en el header de auth ([gateway.py:356-366](../../backend/src/api/gateway.py#L356)).
  Una Connection marcada `subscription-passthrough` puede rutearse byok.
- `_normalize_mode` colapsa cualquier valor no-byok a subscription
  ([gateway.py:343-345](../../backend/src/api/gateway.py#L343)).
- Conceptualmente **byok ≠ modelo de la pasarela**: byok es la key del cliente contra el proveedor,
  distinto de un modelo del `model_list` o un modelo local.

**Decisión**: función de mapeo explícita y testeada, del ruteo **efectivo** al eje de la spec. Sin
ella, la gobernanza se aplica al alcance equivocado.

**Superficie: `tool_type` de la Connection, nunca el User-Agent.** Hay **tres** taxonomías conviviendo
— `tool_type` (6 valores con CHECK, [budget.py:88-91](../../backend/src/models/budget.py#L88)),
`detect_tool` por UA (14 entradas, [custom_auth.py:32-47](../../litellm/extensions/custom_auth.py#L32))
y `User.client_type` (3 valores). El UA es **spoofeable por el cliente**.

**Regla de seguridad derivada (refinada en Fase 1)**: lo que importa no es *qué* hace la decisión
sino **de dónde viene la superficie**. Una decisión que RELAJA (p.ej. `pii_masking=off` para
`claude-code` — el caso insignia de D8) solo se aplica cuando la superficie del pedido proviene de
un origen **confiable**: el `tool_type` de la Connection, dato provisionado por el admin que el
cliente no puede alterar sin otra key. Cuando la superficie es **derivada del User-Agent**
(spoofeable — p.ej. tráfico del plano gateway sin `X-Basa-Key`), las decisiones que relajan se
ignoran (heredar) y solo aplican las que **agregan** capas. Así el caso de coding tools es
expresable sin abrir ningún vector de evasión: spoofear el UA no consigue nada, y cambiar el
`tool_type` requiere al admin. Las capas de piso no se relajan en ningún alcance (422).

**Absorción de `redact_enabled` (013 FR-014) — punto de entrada**: el toggle per-Connection
existente entra a la cascada como el nivel **más específico** (una Connection es más fina que una
superficie), solo para la capa que lo absorbe (`pii_masking`), con su semántica `NULL=heredar`
intacta: `Connection > superficie confiable > modo > tenant_default > default de producto`. Las
Connections que hoy lo usan siguen funcionando sin migración — absorber sin derogar, literal.

**Riesgo asumido**: el enum de superficie nace **incompleto** — la API de Responses (#28) y la
extensión de navegador no están en el CHECK actual. Necesita fallback explícito a `tenant_default`.

---

## D6 — Atribución: campos nuevos, `guardian_events` congelado

**Decisión**: dos campos nuevos en `audit_logs` — `applied_layers` (JSONB, hermano de
`masked_entities`/`guardian_events`, [audit.py:26,32](../../backend/src/models/audit.py#L26)) y
**`blocked_by_layer`** (escalar indexable, código de capa o NULL). El escalar es lo que hace un
bloqueo atribuible con una query trivial, sin LATERAL joins.

Se separan **tres ejes hoy conflados** en el campo `action`:
`layer_code` + `status` de la capa (`applied|skipped|not_configured|requires_credential|delegated|degraded`)
+ `decision` sobre el pedido (`allow|mask|flag|block`). Hoy `DELEGATED` convive con `MASK` y `BLOCK` en
el mismo campo, mezclando "qué decidió la capa" con "qué estado tiene la capa".

**Por qué NO reusar `guardian_events`**: es una bolsa multiplexada por **tres productores con formas
incompatibles** — los triggers del pipeline, el marcador fijo `PROXY` del passthrough
([gateway.py:285-286](../../backend/src/api/gateway.py#L285)), y **la hash-chain de licencias**
([licensing/audit_events.py:178-198](../../backend/src/licensing/audit_events.py#L178)), que además
se relee **posicionalmente** (`row.guardian_events[0]`, `audit_events.py:92-93` y
`trueup_export.py:42-43`). Mezclar evidencia tamper-evident de licenciamiento con telemetría por
pedido bloquea cualquier índice o query tipada. Queda **congelada como legado, sin migración**.

**Identidad estable**: el código de capa es del registry (D1), **no** el nombre de display del
guardián — hoy los triggers usan `secret_guardian.name`
([guardian_service.py:190](../../backend/src/services/guardian_service.py#L190)), que es editable y
white-label: un rename del cliente rompería toda la atribución histórica.

**Restricción C1 (nunca PII cruda)**: `applied_layers` lleva **solo códigos y contadores**. Hoy los
`detail` de los triggers ya incluyen el nombre propio bloqueado
(`f'Nombre personalizado bloqueado: {name}'`, [guardian_service.py:268](../../backend/src/services/guardian_service.py#L268)),
y eso termina en la columna JSONB. **No copiar ese patrón** — sería repetir una fuga.

**Daño colateral ya presente**: el agregado de analytics usa `ev->>'guardrail_name'`
([analytics.py:94](../../backend/src/api/analytics.py#L94)), clave que **ningún productor escribe**,
y no filtra por `model` — así que cada evento de licencia suma como "activación de guardián". El
dashboard seguirá mintiendo (SC-001) si no se toca.

### Corte explícito con la 018 — para que SC-005 no quede falsamente verde

SC-005 dice *"todo bloqueo es atribuible"*. En el plano motor eso es **inalcanzable dentro de 027**:
un bloqueo hace `return reason` ([basa_guardrail.py:86, :91-92](../../litellm/extensions/basa_guardrail.py#L86))
→ LiteLLM levanta 400 → `async_log_success_event` **nunca se dispara** → ni fila de auditoría ni evento
de monitor. Lo mismo en el backend: los `raise HTTPException` de
[chat.py:187, :207, :306](../../backend/src/api/chat.py#L187) preceden al
`AuditService.log_transaction` de :546.

**Alcance de 027**: definir los campos, emitir la atribución en el punto de bloqueo y publicarla en el
evento de monitor. **La fila durable depende de la 018** (owner: Cristian). Se declara aquí para que
el criterio no se marque cumplido sobre una promesa que el sistema no puede sostener.

---

## D7 — Página propia, y autosave con rollback

**Decisión**: **página nueva de primer nivel "Gobernanza"**, no pestaña dentro de Seguridad.
Persistencia **inmediata por control** (optimista con rollback), **no** botón "Guardar Cambios" global.

**El bug de los toggles, con causa exacta**: `handleToggleGuardian`
([SecurityPage.tsx:59-61](../../frontend/src/pages/SecurityPage.tsx#L59)) solo hace `setGuardians(...)`
en memoria; la persistencia ocurre únicamente al pulsar el botón
([SecurityPage.tsx:150-157](../../frontend/src/pages/SecurityPage.tsx#L150)). Y `App.tsx:108-117` es
**render condicional**, no ruta cacheada: al cambiar de sección la página se **desmonta**, el estado
se pierde y al volver el `useEffect` repinta la verdad del servidor. No hay dirty flag, ni badge de
"sin guardar", ni guard de navegación.

**Por qué página propia**:
- SecurityPage no tiene shell de pestañas (553 líneas de flujo plano) y heredaría el `handleSave`
  global que **es** el bug.
- Heredaría también un gate desalineado: el nav muestra "Seguridad y Guardianes" a
  `compliance_officer` ([App.tsx:29](../../frontend/src/App.tsx#L29)) pero `/guardians` es admin-only
  ([guardians.py:17](../../backend/src/api/guardians.py#L17)) → ese rol entra y ve un grid vacío por
  el `catch { // silent }` de SecurityPage.tsx:51-53. **No copiar ese patrón.**
- Cuesta 3 ediciones mecánicas y sincronizadas en `App.tsx`: el union `Page` (:16), el item de
  `navigation` (:22-33) y el render condicional (:108-117).

**Patrón de guardado, por control**: valor optimista → `await api.updateGovernance…` → **setear el
estado desde la respuesta del servidor, no desde el valor optimista** → en `catch`, revertir y mostrar
el `err.detail` del backend (patrón de `testGuardian`,
[api.ts:483-495](../../frontend/src/services/api.ts#L483), el único que hoy extrae mensaje útil).
Campos de texto: persistir en `onBlur` o debounce ≥800 ms, **nunca por keystroke** — sobre superficie
auditada eso generaría una entrada de `config_audit` por tecla, con retención mínima de 365 días.

Esto elimina la clase de bug entera: no queda estado sin guardar que perder al desmontar.

**Gating**: `roles: ["admin"]` en el nav **en vocabulario LEGACY** (el array usa los roles
normalizados por `toLegacyRole`, [auth.ts:18-24](../../frontend/src/services/auth.ts#L18); escribir
`tenant_admin` haría que el ítem no se muestre nunca, y **falla en silencio**), y —lo que de verdad
protege— `dependencies=[Depends(require_role("admin"))]` en el router nuevo, espejo de `guardians.py:17`.
El filtro `visibleNav` (`App.tsx:49-51`) es puramente cosmético.

**Nota**: el bug de SecurityPage **sigue existiendo** después de 027 si no se arregla aparte. Tarea
separada, no scope creep.

---

## D8 — El piso y el toggle que ya lo apaga ✅ **confirmada por el owner (2026-07-22)**

**El conflicto**: FR-002 pone *"enmascarar datos personales"* en el piso no-negociable. Pero
`redact_enabled=False` **hoy apaga el enmascarado** en los dos planos
([basa_guardrail.py:95](../../litellm/extensions/basa_guardrail.py#L95),
[gateway.py:479-482](../../backend/src/api/gateway.py#L479)), y esa semántica es **FR-014 de la spec
013** ([context_resolution.py:34-38](../../backend/src/services/context_resolution.py#L34)). Tomado
al pie de la letra, FR-002 deroga un requisito ya entregado de otra spec.

**Decisión propuesta**: partir la capa en dos y quedarse con lo que de verdad es innegociable.

| | Piso (nunca apagable) | Gobernable |
|---|---|---|
| **Qué** | interceptar · evaluar AI-Act · bloquear secretos · **detectar** PII · **registrar** el pedido y su atribución | **transformar**: enmascarar o no antes de salir |
| **Control** | ninguno — constante de código | `redact_enabled`, absorbido como la decisión de la capa `pii_masking` |

**Por qué**: el valor declarado del producto es *"interceptar y registrar TODO + no dejar salir datos
sensibles"*. Apagar el enmascarado es una elección legítima y existente (en herramientas de código el
enmascarado rompe el código); apagar **la intercepción, la evaluación o el registro** no lo es nunca.

Además **mejora la honestidad**: hoy con `redact_enabled=off` la PII simplemente desaparece del
relato. Con esta decisión, el pedido queda registrado como *"PII detectada, no enmascarada por
configuración"* — visible en la vista de gobernanza, atribuible, auditable.

**Efecto secundario deseable**: `redact_enabled` deja de ser un toggle paralelo y pasa a ser la
decisión de una capa dentro del mismo modelo — un mecanismo menos, no uno más.

> **Confirmada por el owner el 2026-07-22** ("de acuerdo con vos, tal cual"). La letra de la spec
> quedó enmendada en consecuencia: FR-002 y la Assumption del piso ahora dicen *detectar* + registro
> honesto del enmascarado desactivado, absorbiendo el toggle de la 013 como decisión de capa.

---

## Prerrequisitos y hallazgos fuera de alcance

### P1 — ⚠️ En el perfil prod, el motor no puede leer la identidad (bloqueante para el plano motor)

`compose.prod.yml:79` apunta el motor a `ENGINE_DB:-basa_engine` — base **propia**, creada por
`initdb/01-engine-db.sql`, correctamente separada para que el migrador Prisma no dropee las tablas del
backend (hallazgo del ensayo del piloto). Pero `custom_auth._lookup_identity` consulta
`api_keys/users/groups/tenants` con `_IDENTITY_SQL` **contra el prisma del motor**
([custom_auth.py:100-104](../../litellm/extensions/custom_auth.py#L100)) — tablas que en
`basa_engine` **no existen**. En dev comparten `basa_gateway` (`docker-compose.yml:46`) y funciona.

**Consecuencia esperada en prod**: `query_raw` lanza → `user_api_key_auth` levanta excepción → **401**.
Es decir, **byok / herramientas de código estarían caídas en el perfil prod**, fail-closed (seguro,
pero no funcional). No se pudo verificar contra el despliegue en vivo desde acá.

Cualquier lectura de configuración de gobernanza por el motor hereda **exactamente** este problema, así
que es prerrequisito de 027 — pero es antes que nada un **bug de producto con instalación inminente**.
Se levanta aparte.

### P2 — El seed destructivo de guardianes

`db.query(Guardian).delete()` sin filtro de tenant cuando hay <9 filas
([guardian_service.py:33-36](../../backend/src/services/guardian_service.py#L33)). Bomba en
multi-tenant, independientemente de 027. Se neutraliza defensivamente en la primera tarea; el arreglo
de fondo es del módulo de seguridad.

### P3 — Auditoría histórica ya contaminada

Los `DELEGATED` fabricados **ya están persistidos** en `audit_logs.guardian_events`. Los reportes
históricos contienen afirmaciones falsas de cobertura, y un export GDPR Art.30 hoy **exporta la
mentira**. Hay que decidir si se marcan como no confiables o se purgan.

### P4 — `gw_inspect` incumple el piso

[inspect.py:50-91](../../backend/src/api/inspect.py#L50) enmascara pero **no** llama a
`evaluate_request_policy`: no corre AI-Act ni bloqueo de secretos. Es el contraejemplo del piso, y con
FR-002 en la mano es un fix **obligatorio** dentro de 027 — con la salvedad de que la extensión MV3
empezará a recibir bloqueos y necesita contrato de error.

### P5 — El guardián `presidio` no tiene rama de ejecución

No existe rama para él en `process_prompt`; `PresidioService.analyze_text_http` **no tiene ningún
llamador**. Lo que corre como "Presidio" es regex local. La respuesta honesta es *no disponible* —
lo que colisiona con cómo se presenta en la UI y con la spec **016** (PR #21). Coordinar con Cristian
antes de publicar el estado honesto.

> **Actualización (review del PR #21, head `a063c63`, 2026-07-22)**: la 016 cierra P5
> **parcialmente y por plano** — motor/byok: NLP real fail-closed ✔; chat UI: NLP con degradación
> visible ✔; gateway passthrough: sigue regex ✘; perfil prod: sin sidecar ni env → regex ✘ (bloqueante
> reportado en el review). Consecuencias para 027: (1) **orden de merge: 016 primero** — 027 aún no
> tiene código y comparte `guardian_service.py`/`basa_guardrail.py`/`custom_auth.py`/`guardians.py`;
> (2) el registry absorbe de la 016 una dependencia nueva **`requires_service`** (sidecar +
> `NLP_ANALYZER_URL` + healthcheck — distinta de `requires_credential`) y el trigger `DEGRADED`
> como evidencia per-request (fuente C de D4); (3) el estado honesto de la capa NLP es **por
> plano**, exactamente lo que FR-010 ya exige; (4) P1 sube de urgencia: también bloquea la US2 de
> la 016 en prod.

---

## Ajuste de alcance derivado de la Fase 0

La spec habla de "los dos planos". La Fase 0 encontró **tres puntos de aplicación** (gateway,
motor, chat UI) más una superficie que hoy no pasa por política (`gw_inspect`). El resolutor único de
D3 es lo que evita que ese hallazgo multiplique el trabajo por tres: la 027 entrega **un** resolutor y
**tres** call-sites, no tres implementaciones.
