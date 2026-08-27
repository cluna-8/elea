# Códigos de error

**Para quién**: el dev que integra una herramienta contra el gateway y necesita decidir,
por código, si reintenta, si le muestra el error a su usuario, o si escala al admin.

Esta página es el contrato de wire completo — HTTP status, cuándo lo emite cada motivo,
y qué se espera del que integra. Si programaste un `try/except` que solo mira el status
code, seguí primero la tabla de decisión (§1); el resto son los detalles por caso.

## 1 · Tabla de decisión — antes que nada

| Código | ¿Reintentar? | Con qué backoff |
|---|---|---|
| **429** — límite de ritmo | Sí | El de la cabecera `Retry-After` |
| **503** — capacidad saturada | Sí | El de la cabecera `Retry-After` |
| **503** — residencia de datos / auditoría degradada | **No** — es config de la instalación, no transitorio | — |
| **402** — presupuesto o seats agotados | No hasta que el admin actúe | — |
| **403** — bloqueado por política o licencia | No — corregí el pedido o la licencia | — |
| **400** — bloqueado por AI Act, secreto detectado, o guardián de política | No con el mismo body | — |

**El discriminador de los cuatro 503 es la cabecera, no el body.** Un 503 de saturación
trae `X-Basa-Rejected: saturated` + `Retry-After`; los otros tres 503 no traen ninguna de
las dos. Mirá la cabecera antes de decidir si reintentar — el body por sí solo no alcanza,
y en el camino `byok` de `/gw` la forma del error es la de Anthropic (sin espacio para un
código propio en el body).

## 2 · 400 — la política bloqueó el pedido antes de salir

Tres motivos distintos comparten el mismo status. `compliance_status` (visible en la
auditoría, no en la respuesta al cliente) los distingue:

| `compliance_status` | Motivo | Dónde se decide |
|---|---|---|
| `blocked_prohibited` | Práctica prohibida por el AI Act (Art. 5) | Evaluación de riesgo, antes que cualquier otra capa |
| `blocked_secret` | Se detectó una credencial o secreto en el prompt | Detector de secretos |
| `blocked_by_policy` | Un guardián de política (secreto o PII) bloqueó | Motor de guardianes del tenant |

No hay reintento útil con el mismo body: el pedido no cambia de veredicto salvo que se
edite el contenido.

## 3 · 402 — pago o cupo agotado

| `compliance_status` | Motivo | Qué hace el admin |
|---|---|---|
| `rejected_budget` | Presupuesto mensual agotado para la llave o el usuario/equipo | Ampliar presupuesto o esperar al ciclo siguiente |
| `license_seat_limit_exceeded` | No quedan seats libres en la licencia | Revocar una Connection o ampliar la licencia |

Sin cabeceras especiales — ninguno de los dos tiene contrato de wire acordado más allá
del status code.

## 4 · 403 — la licencia no lo permite

| `detail` (prefijo) | Motivo |
|---|---|
| `license_creation_blocked` | La licencia está degradada, ausente o es de otro tenant — no se puede crear el recurso |
| — | Bloqueo total (`BASA_LICENSE_HARD_BLOCK=true`) con la licencia en `expired` u `over_seat`: corta también las rutas de servicio, no solo las altas — ver [licenciamiento](../install-deploy/licensing.md) |

El mensaje al cliente en el bloqueo total es genérico a propósito (`license_degraded:
acceso bloqueado por el estado de la licencia del deployment`): el corte corre antes de
resolver identidad, así que no se filtra estado interno a quien no se autenticó.

## 5 · 429 — límite de ritmo

Tope de `rpm`/`tpm` de la llave. Trae **`Retry-After`** con los segundos exactos —
reintentá con ese valor, no con backoff propio.

## 6 · 503 — los cuatro casos, uno por uno

### Saturación de capacidad (`rejected_saturated`)

El motor no tuvo turno libre dentro del timeout de admisión. **Reintentable.**

- Cabecera `X-Basa-Rejected: saturated` — el único de los cuatro 503 que la trae. Distingue
  este rechazo de un 503 genérico de proxy o del propio motor.
- Cabecera `Retry-After`.
- Queda auditado igual que un bloqueo: la fila se escribe antes de responder.

### Residencia de datos (`blocked_residency`)

El proyecto de compliance exige procesamiento en la UE y el modelo pedido no cumple.
**No reintentable** — es una decisión de config del tenant, no una condición transitoria.
Sin cabecera especial.

### Auditoría no disponible en modo `closed`

La instalación exige registro durable de todo pedido (`BASA_AUDIT_FAIL=closed`) y el
registro falló. **No reintentable** hasta que la base de auditoría vuelva. Mismo texto
tanto si el fallo ocurrió en el camino feliz como en un bloqueo — para quien opera son el
mismo hecho: *"esta instalación no sirve tráfico que no puede registrar"*. Sin cabecera
especial.

Texto exacto del `message`:

> `[Basa Gateway] auditoría no disponible — la instalación exige registro (audit_fail=closed)`

### Auditoría no disponible **para este pedido** en modo `policy`

`policy` no es un override global: es una matriz por nivel de riesgo del pedido. Con la base
de auditoría caída, un pedido de riesgo `minimal`/`limited` **se sirve igual** (la pérdida
queda contada y visible en `/health`), y uno de riesgo `high_risk_annex1`/`high_risk_annex3`
recibe este 503. **No reintentable** hasta que la base vuelva.

!!! warning "El modo EFECTIVO lo fija el deployment, no esta página"

    `policy` es el default del producto cuando `BASA_AUDIT_FAIL` **no llega seteada**. Pero un
    `docker compose` puede pasarla igual con un valor por defecto propio, y en ese caso ese
    valor gana — el backend sólo ve la variable que le llega. **Un deployment que pinea `open`
    nunca alcanza este modo**, y ninguna prueba contra ese stack va a mostrar este 503.

    Antes de concluir que la matriz «no funciona», comprobá el valor efectivo dentro del
    contenedor del backend (`docker compose exec backend env | grep BASA_AUDIT_FAIL`) y
    contrastalo con el `environment:` del servicio en tu compose. Es el mismo par de planos de
    siempre: el código dice qué hace con lo que llega, el compose dice qué llega.

El texto es distinto del de `closed` a propósito, y conviene distinguirlos al integrar: acá
el servicio sigue en pie y es *este* pedido el que no se sirve.

> `[Basa Gateway] auditoría no disponible — este pedido no se sirve sin registro por su nivel de riesgo (audit_fail=policy)`

**Lo que hay que saber si integrás contra `/gw`, y es la consecuencia menos obvia de este
modo:** el nivel de riesgo se resuelve desde la credencial del pedido, con la cascada
`llave → usuario → equipo`. En `/gw` el header `X-Basa-Key` es **opcional** (la ruta se
autentica con el OAuth), así que un pedido sin ese header **no tiene de dónde resolver un
riesgo**, y un pedido sin riesgo resuelto no demostró ser de riesgo bajo: cuenta como alto.

En consecuencia, en `policy` y con la auditoría caída, **todo el tráfico de `/gw` que no
mande `X-Basa-Key` recibe este 503** — y ése es el camino habitual de las herramientas de
código. No es un caso de borde: es el volumen normal de esa ruta. Es una decisión de
diseño, no una condición transitoria.

Las dos perillas del admin, en orden de preferencia:

1. **Poblar el nivel de riesgo** de los equipos (`default_risk_level` en el equipo, o
   `risk_level` en cada usuario) y hacer que las herramientas manden su `X-Basa-Key`. Es la
   salida buena: el tráfico pasa a decidirse por su riesgo real en vez de por el default
   conservador. `GET /health` avisa **antes** de la caída, con un `degraded` que cuenta los
   usuarios activos que hoy resolverían "sin riesgo".
2. **`BASA_AUDIT_FAIL=open` explícito**, si la instalación prefiere continuidad con pérdida
   contada. Es un override global: desactiva la matriz para todo el tráfico, no sólo para el
   anónimo.

El contador de `/health` **no ve el tráfico anónimo de `/gw`**: cuenta usuarios en la base,
y un pedido sin credencial no tiene fila de usuario que contar. O sea que un `/health`
limpio no garantiza que este 503 no vaya a aparecer por esa vía.

**El camino `byok` todavía no participa de la matriz, y conviene no inferir uniformidad.**
Un pedido que llega con una virtual key `sk-basa-…` en el header de autorización o en la URL
se enruta a byok, y ahí el registro lo escribe el motor, no la pasarela. Por eso hoy ese
camino se corta **sólo bajo el override global `BASA_AUDIT_FAIL=closed`**: en `policy`, con
la auditoría caída, un pedido byok de riesgo alto **no** recibe este 503 desde la pasarela.
Hacer que la matriz gobierne también a byok requiere que la decisión viaje con el contexto
de la credencial hasta el motor; está en el mismo plan que este modo y no es una omisión
silenciosa.

## 6b · Lo que esta página NO cubre

El estado de la licencia (`active`/`grace`/`expired`/…) que devuelve `GET
/health/license` está en [licenciamiento](../install-deploy/licensing.md). Aparte de
ese vocabulario corto, el sistema registra siete nombres de evento más largos en la
tabla de auditoría de licencia — `license_expired`, `license_grace`, `license_invalid`,
`license_missing`, `license_over_seat`, `license_tenant_mismatch`,
`license_clock_rollback_suspected` — que son nombres de fila para quien revisa el
histórico, no un código que un integrador reciba en una respuesta HTTP. Quedan **fuera
de esta página a propósito** (su audiencia es el DPO/admin, no el dev de la
integración); documentarlos es una página aparte, todavía sin dueño.

## 7 · Estructura, para lo que venga

Esta tabla crece por fila, no por reescritura: un motivo nuevo con el mismo status entra
como fila nueva en la sección que le toca. Dos que ya se sabe que llegan: un
`blocked_content_filter` (guardián de contenido, en desarrollo) y los estados que sume la
018 de licenciamiento. Verificá con `python3 docs/tools/drift_gate.py` antes de publicar
un motivo nuevo — si el código no lo emite todavía, no va en esta página.

## Relacionado

- [Configuración](configuration.md) — variables que afectan estos umbrales (`BASA_ENGINE_MAX_CONCURRENCY`, `BASA_AUDIT_FAIL`)
- [Licenciamiento](../install-deploy/licensing.md) — el ciclo de vida completo detrás del 402/403 de licencia
- [Integraciones & matriz](../integrations/index.md) — qué herramienta ve cada código
