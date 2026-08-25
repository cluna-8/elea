# Contrato — API REST de gobernanza (027)

Interfaz pública del router nuevo `backend/src/api/governance.py`, montado bajo
`/api/v1/governance` (el frontend habla rutas relativas, `api.ts:6`). El detalle de shapes
puede refinarse en implementación; **los invariantes numerados no**. Entidades, enums y
columnas: [data-model.md](../data-model.md). Decisiones de diseño: research D2/D4/D7.

## Invariantes globales

1. **Admin-only en el router, no en la UI**: `dependencies=[Depends(require_role("admin"))]`
   en el `APIRouter`, espejo de `guardians.py:17`. El gating del nav (`visibleNav`,
   `App.tsx:49-51`) es cosmético; la protección real es esta. Rol insuficiente → **403**.
2. **White-label (Principio VII)**: ninguna respuesta expone `engine_guardrail_name` ni el
   payload crudo de la sonda `GET /guardrails/list`. Se mantiene el patrón
   `engine_guardrail_name=None` de `guardians.py:57`; la sonda se consume SOLO en el
   backend, cacheada (TTL ~30 s) — nunca una llamada autenticada al motor por pageview.
3. **Fail-closed en estado**: motor inalcanzable o sonda sin refresco ⇒
   `estado_efectivo: no_disponible` con `motivo` que distinga "no lo aplicamos nosotros"
   de "estás desprotegido" (FR-013). JAMÁS `aplicandose` sin sonda confirmante (D4).
4. **Estados cerrados y calculados**: `estado_efectivo ∈ {no_disponible,
   requiere_credencial, delegada, aplicandose, degradada}`; se computa por request y
   **nunca se persiste** (D4).
5. **401 uniforme en el frontend**: TODAS las funciones del bloque Governance de `api.ts`
   llaman `handleExpiredSession(res)` (`api.ts:17-22`) antes de evaluar `res.ok` — no
   repetir el olvido del bloque Security Policy (`api.ts:253-267`, que no lo llama) y usar
   `jsonHeaders()` en las mutaciones.
6. **Errores tipados con `detail` útil**: 401 sesión · 403 rol · 404 recurso · 422
   semántica (piso, valores fuera de enum). El `detail` del backend es el mensaje que la
   UI muestra en el rollback (patrón `testGuardian`, `api.ts:483-495`).

## `GET /api/v1/governance/status?mode=&surface=`

Vista de estado honesto (FR-001) + resumen por modo (FR-010/SC-002).

- **Sin params**: resumen por modo de conexión — para cada modo, todas las capas con su
  decisión resuelta y su estado efectivo. Responde "qué protege hoy al tráfico de
  Suscripción y qué al de Modelo propio" en **una** respuesta (SC-002).
- **Con `mode`** (y opcional `surface`): la resolución concreta para ese alcance.

Por capa:

```json
{
  "layer_key": "pii_masking",
  "tier": "floor | optional",
  "planes": ["gateway", "engine", "backend"],
  "decision_resuelta": "on | off",
  "origen": "floor | connection | surface | connection_mode | tenant_default | product_default",
  "estado_efectivo": "aplicandose | requiere_credencial | delegada | no_disponible | degradada",
  "motivo": "texto humano; obligatorio si estado_efectivo != aplicandose"
}
```

`planes` es **lista** (subconjunto de los 3), no escalar: las capas de piso corren en los
tres call-sites a la vez (data-model §2.1) y un escalar no puede representarlas.

**Garantías**:

- (a) `origen` hace **consultable la precedencia** (FR-006): siempre presente, siempre uno
  de los valores de la cascada del [resolutor](./resolutor-perfil.md) (incluido
  `connection` cuando la decisión vino del override por-key absorbido, D8).
- (b) las capas de piso aparecen siempre, con `tier=floor`, `decision_resuelta=on`,
  `origen=floor` — no hay representación de piso apagado (SC-004).
- (c) decisión y estado son **ejes independientes**: una capa `on` puede estar
  `no_disponible` o `requiere_credencial` — el deseo no fabrica ejecución (FR-007, D4).
- (d) para capas `delegada`, `motivo` lleva la explicación de la delegación del registry
  (FR-013): "la protege el proveedor upstream porque X", nunca un estado pelado.
- (e) `mode`/`surface` fuera de enum → 422 nombrando el valor recibido.
- (f) **`motivo` sale de un catálogo cerrado**: exclusivamente del copy del registry
  (`delegation_reason`) y de un catálogo de razones por estado definido en código — **jamás**
  del mensaje de una excepción del motor o de la sonda (que naturalmente contiene nombres de
  proveedor, hosts internos o stack traces). Test negativo obligatorio: ninguna respuesta del
  router contiene nombres de proveedor (Principio VII) ni fragmentos de traceback.
- (g) **`tenant_id` opcional, con gate honesto sobre el RBAC vigente**: el tier super-admin de
  la constitución III es forward-looking ([D9] = roadmap), y hoy `require_role("admin")` no
  distingue el admin de un tenant del de la instalación. Regla para 027: `tenant_id` se acepta
  **solo en instalaciones single-tenant** (donde admin == admin de la instalación; SC-007 lo
  usa ahí); en un despliegue con más de un tenant → **403 siempre**, hasta que exista el RBAC
  de [D9] — jamás una lectura cross-tenant apoyada en un tier que aún no existe. Tenant
  inexistente → 404.

## `GET /api/v1/governance/profile`

Lista las filas de decisión del tenant resuelto: `{scope_type, scope_value, layer_key,
decision, updated_by, updated_at}`. **La ausencia de fila es "heredar"** (D2): el endpoint
no fabrica filas implícitas ni "completa" el catálogo — lo no configurado simplemente no
está.

## `PUT /api/v1/governance/profile`

Upsert de **una** decisión por la clave natural `(scope_type, scope_value, layer_key)`
(UNIQUE de `governance_profiles`). Body: `{scope_type, scope_value, layer_key, decision}`.

**Garantías**:

- (a) **422 piso + auditoría del intento**: `layer_key` con `tier=floor` en el registry →
  422, y el intento queda **registrado** (quién, qué capa, qué alcance) — FR-003/SC-004.
  El rechazo jamás es silencioso.
- (b) **Superficie que relaja: legal, con honestidad de alcance** (D5 refinada): una fila
  `scope_type='surface'` con `decision='off'` sobre capa opcional **se acepta** — es el caso
  insignia de D8 (masking off para coding tools). El resolutor la aplica **solo a tráfico con
  superficie confiable** (`tool_type` de la Connection); al tráfico con superficie derivada de
  User-Agent no lo relaja jamás ([resolutor #5](./resolutor-perfil.md)). La respuesta del PUT
  lo hace explícito en `motivo` ("aplica solo a Connections con esta herramienta declarada"),
  para que la configuración nunca prometa más alcance del que tiene.
- (c) **422 enum**: `layer_key` fuera del registry, `scope_type`/`decision` fuera de sus
  CHECKs, o `scope_value` fuera del enum del eje → 422 nombrando el campo inválido. Los
  valores canónicos de `scope_value` por `scope_type` los fija data-model.md.
- (d) **La respuesta es la verdad recalculada, no un eco**: incluye la fila persistida
  **y** el `estado_efectivo` recomputado de esa capa para ese alcance. Activar una capa
  cuyo guardrail no está en la sonda **no devuelve 200-verde**: acepta el deseo y responde
  `estado_efectivo: no_disponible` con motivo (D4, punto 4). La UI setea su estado desde
  ESTA respuesta, nunca desde el valor optimista (D7).
- (e) **Invalidación del cache de identidad del motor**: antes de responder, la escritura
  invalida las entradas del cache por key afectadas por el tenant (cache de 60 s por
  `key_hash`, `custom_auth.py:64-66`). Garantía observable: el siguiente request por el
  motor resuelve con el perfil nuevo — sin esto, SC-006 es falso durante un minuto.
- (f) **Todo cambio se audita** como cambio de configuración (con `updated_by`), sin
  contenido sensible.

## `DELETE /api/v1/governance/profile/{scope_type}/{scope_value}/{layer_key}`

Volver a **heredar**: borra la fila de decisión.

**Garantías**: (a) **idempotente** — fila inexistente → 204 igual: "heredar" ya es el
estado resultante; (b) misma invalidación de cache que PUT (e); (c) se audita como cambio
de configuración. El piso no tiene filas, así que no hay DELETE que lo afecte.

## Bloqueo en `/gw/inspect` (superficie browser) — contrato para la extensión MV3

El fix P4 (research) mete `gw_inspect` bajo el mismo `Profile`: hoy enmascara pero no corre
AI-Act ni bloqueo de secretos ([inspect.py:50-91](../../backend/src/api/inspect.py#L50)) —
el contraejemplo del piso. Al pasar por `apply_layers`, la extensión **empezará a recibir
bloqueos** y necesita un contrato estable:

- **La respuesta de bloqueo DEBE disparar la rama fail-closed de las extensiones ya
  desplegadas**: la MV3 actual solo bloquea con `!res.ok`
  (el fail-closed del hook de `window.fetch` en `extension/guardia-main.js`) — un bloqueo con `ok: true` + `replacements: []` haría
  que una extensión vieja **envíe el texto original en claro** al proveedor (skew de
  versiones = fail-open). Por eso el bloqueo responde `ok: false` **más** los campos nuevos:
  `{"ok": false, "blocked": true, "blocked_by_layer": "<layer_key>", "motivo": "<copy del
  catálogo cerrado>"}`. Extensiones viejas bloquean por su propio fail-closed (mostrando el
  error genérico); las nuevas distinguen `blocked` y muestran `motivo`.
- `motivo` cumple la garantía (f) del status: catálogo cerrado, sin nombres de proveedor, sin
  contenido del texto inspeccionado (C1).
- El shape de wire exacto es refinable en implementación; **`blocked` + `blocked_by_layer` +
  la prohibición de texto sensible no**.

## Lo que este contrato prohíbe

- Un endpoint que devuelva "activo" leyendo `is_active` de `guardians` (la mentira actual,
  D4): `is_active` es **deseo**, jamás estado.
- Reenviar al frontend nombres de guardrail del motor o el JSON de la sonda.
- Escrituras que respondan antes de invalidar el cache del motor.
