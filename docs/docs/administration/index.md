# Administración

Guía para el **operador** de una instancia del producto: cómo se organiza un despliegue
(tenants), quién puede hacer qué (roles), cómo se gobierna el contenido que atraviesa el
gateway (políticas de seguridad), cómo se controla el gasto (budgets) y cómo funciona el
licenciamiento offline por seats.

!!! note "Leyenda de estado"
    🟢 **HOY** — funciona y está verificado · 🟡 **PARCIAL** — existe con límites
    documentados · 🔵 **OBJETIVO** — roadmap explícito, no implementado. Nada marcado
    🔵 se describe como si existiera.

---

## Multi-tenant

### Qué es un tenant

Un **tenant** es la organización compradora: la raíz de toda la jerarquía de datos de la
plataforma.

```text
Tenant (organización)
 └── Grupo (equipo / departamento)
      └── Cliente (usuario final)
           └── Connection (credencial de una herramienta: una virtual key sk-basa-…)
```

Todo objeto administrable (grupos, usuarios, Connections, políticas, presupuestos,
auditoría) pertenece a un tenant. El aislamiento efectivo entre tenants se aplica hoy
**a nivel de aplicación**: todas las consultas están acotadas al tenant. Las tablas
tienen además row-level security (RLS) habilitado y forzado en la base de datos, pero el
contexto de tenant por request todavía no se establece, así que RLS como defensa activa
está pendiente de activarse. 🟡

### Modelo de entrega: una instancia por cliente

El modelo de entrega del producto es **una instancia por cliente** (on-premise /
air-gapped): cada despliegue opera con exactamente **un tenant activo**, anclado por
configuración con la variable `BASA_DEPLOYMENT_TENANT_ID`. La licencia del despliegue
está emitida para ese tenant y no habilita ningún otro (fail-closed). 🟢

El modelo de datos soporta además un modo *cloud* con varios tenants conviviendo en una
misma instancia; la **operación SaaS multi-tenant** como servicio gestionado es
🔵 **OBJETIVO** de roadmap, no una modalidad ofrecida hoy.

---

## Roles y permisos (RBAC)

La plataforma define cuatro roles canónicos:

| Rol | Alcance | Qué puede hacer |
|---|---|---|
| **Super admin** | Cross-tenant | Operación por encima de los tenants (solo tiene sentido en modo cloud multi-tenant). No se crea automáticamente: se siembra de forma explícita. Dentro de un tenant equivale a un tenant admin. |
| **Tenant admin** | Su tenant (= la instancia) | Administración completa: usuarios y grupos, Connections, presupuestos, políticas de seguridad, compliance, auditoría y salud de la licencia. Es el rol del operador. |
| **Compliance officer** | Su tenant | Ver y editar políticas de seguridad y configuración de compliance, ver auditoría, exportar reportes, aprobar revisiones humanas y consultar el detalle de salud de la licencia. **No** gestiona usuarios ni presupuestos. |
| **Client** | Su propio uso | Usuario final que consume IA a través de sus Connections. El rol en sí no consume seat: los seats los consumen sus **Connections activas** (ver [Licencias y seats](#licencias-y-seats)). |

Los usuarios *client* pueden llevar una **etiqueta de perfil** (`display_label`, p. ej.
`clinician`, `developer`) que refina permisos puntuales heredados: un client con perfil
`developer` puede gestionar las Connections **del tenant** (hoy sin acotación por dueño);
uno con perfil `clinician` participa en la aprobación de revisiones humanas. 🟢

Matriz de permisos vigente en la instancia:

| Acción | Tenant admin | Compliance officer | Client |
|---|:---:|:---:|:---:|
| Crear / desactivar usuarios y grupos | ✅ | ❌ | ❌ |
| Crear / revocar Connections (virtual keys) | ✅ | ❌ | solo perfil `developer` (las del tenant) |
| Crear / editar presupuestos | ✅ | ❌ | ❌ |
| Editar políticas de seguridad | ✅ | ✅ | ❌ |
| Ver / editar compliance | ✅ | ✅ | ❌ |
| Ver auditoría / exportar reportes | ✅ | ✅ | ❌ |
| Aprobar revisión humana | ✅ | ✅ | solo perfil `clinician` |
| Usar la IA por el gateway | ✅ | ✅ | ✅ |
| Detalle de salud de licencia | ✅ | ✅ | ❌ |

!!! warning "Fail-closed en la administración"
    Todos los endpoints de administración exigen una **sesión JWT válida** de un usuario
    activo; sin token (o con token vencido) la respuesta es `401`. Las **virtual keys**
    (`sk-basa-…`) sirven exclusivamente para inferencia: **jamás** resuelven a una sesión
    de administración, por diseño.

!!! tip "Bootstrap del primer administrador"
    En el primer login de la instancia, entrar como `admin` con la contraseña elegida la
    fija y crea la cuenta como tenant admin. Hacé ese primer login apenas termine el
    deploy, antes de exponer el panel.

Una matriz de permisos **granular y scopeada por tenant** (permisos finos por recurso) es
🔵 **OBJETIVO** de roadmap; la matriz de arriba es la vigente hoy.

---

## Guardrails y políticas de seguridad

Toda petición que atraviesa el gateway pasa por la **política de seguridad activa** antes
de llegar a cualquier proveedor LLM. La política es provider-agnóstica: aplica igual sea
cual sea el modelo de destino y la superficie de entrada (CLI, IDE, extensión de
navegador). 🟢

### Acciones por entidad

El motor NLP del gateway detecta entidades sensibles (PII/PHI) y la política decide qué
hacer con **cada tipo de entidad**:

| Acción | Efecto |
|---|---|
| `MASK` | La entidad se reemplaza por un placeholder (`[PERSON_0]`, `[DNI_0]`, …) antes de salir hacia el LLM y se **restaura el valor real** en la respuesta que ve el usuario. El dato nunca sale; la experiencia no se rompe. |
| `BLOCK` | La petición se rechaza por completo: el contenido no sale de la instancia. |
| `ALLOW` | La entidad pasa sin transformación (para tipos que la organización considera no sensibles). |

Configuración por defecto de una instancia nueva:

```json
{
  "PERSON": "MASK",
  "PHONE_NUMBER": "MASK",
  "EMAIL_ADDRESS": "MASK",
  "US_SSN": "BLOCK",
  "MEDICAL_LICENSE": "BLOCK",
  "DNI": "MASK",
  "CUIL": "MASK"
}
```

### Modos de la política

Además del mapa entidad→acción, cada política tiene tres interruptores:

- **`gdpr_mode`** — activa el tratamiento GDPR (minimización y registro asociado).
- **`ai_act_mode`** — activa el bloqueo por categorías del AI Act (usos prohibidos).
- **`headroom_mode`** — habilita la optimización de contexto para reducir tokens.

### Gestión

- Hay **una sola política activa** a la vez; activar otra desactiva la anterior. Se
  pueden mantener varias políticas guardadas y alternar entre ellas.
- La última política existente **no puede borrarse** (la instancia nunca queda sin
  política: fail-closed).
- Se administran desde el panel o por API (`GET/PUT /api/v1/security/policy` para la
  activa, `GET/POST/PUT/DELETE /api/v1/security/policies` para el catálogo), con rol
  tenant admin o compliance officer.

La detección de **secretos** (API keys, tokens, credenciales en prompts) y el bloqueo por
AI Act se aplican en el mismo punto de paso, junto con la auditoría *metadata-only*: el
registro de auditoría guarda qué se detectó y qué acción se tomó, **nunca** el contenido.
🟢

---

## Budgets y control de costes

El control de gasto se define en el panel y lo aplica el motor del gateway en cada
petición. 🟢

**Por Connection (virtual key)** — al crear una Connection se fijan:

| Campo | Descripción | Default |
|---|---|---|
| `max_budget` | Tope de gasto (USD) de la key | sin tope |
| `budget_duration` | Ventana de reinicio del tope | `30d` |
| `models` | Lista blanca de modelos que la key puede usar | todos |
| `rpm_limit` / `tpm_limit` | Rate limit (requests y tokens por minuto) | `60` / `100000` |
| `expires_at` | Expiración de la key | sin expiración |

**Por usuario o por grupo** — un presupuesto (`/api/v1/budgets`, solo tenant admin) se
asigna a *un* usuario **o** a *un* grupo (nunca ambos, y a lo sumo uno por
usuario/grupo), con:

- `max_spend_usd` — tope de gasto en la ventana,
- `max_tokens` — tope de tokens,
- `reset_period` — período de reinicio.

**Consulta de gasto** — el gasto acumulado contra su tope se consulta por key
(`GET /api/v1/keys/{id}/spend`), por usuario (`GET /api/v1/users/{id}/spend`) y por grupo
(`GET /api/v1/users/groups/{id}/spend`).

**A nivel tenant** — como el despliegue opera con un tenant único, el agregado del tenant
es la suma de la instancia y se observa en el panel de analítica y costes; no existe hoy
un tope de gasto *tenant-wide* como objeto propio (los topes se definen por key, usuario
y grupo).

---

## SSO

**Estado honesto: 🔵 OBJETIVO.** La autenticación de la instancia es hoy con **cuentas
locales** (usuario y contraseña, administradas por el tenant admin) y sesiones JWT. 🟢

El panel muestra una vista de "Autenticación & SSO" con los métodos disponibles y los
planificados, para que el operador pueda planificar la integración — pero la federación
real de identidad (OIDC / SAML, p. ej. Azure AD o Google Workspace) **no está
implementada**: es roadmap explícito. No la comprometas en un despliegue como si
existiera.

---

## Licencias y seats

El licenciamiento es **100% offline**: un archivo de licencia firmado (Ed25519) que la
instancia verifica localmente con la clave pública embebida (o provista por archivo).
**La verificación jamás llama a casa**: no hay egress, no hay servidor de licencias, no
hay telemetría. Funciona igual en un despliegue air-gapped. 🟢

### El archivo de licencia

La licencia se emite para **un tenant** e incluye, entre otros campos, `max_seats`,
`expiry` y `grace_days`. Se inyecta por configuración — el mismo binario/imagen sirve
para cualquier cliente cambiando solo estas variables:

| Variable | Rol |
|---|---|
| `BASA_LICENSE_TOKEN_FILE` (o `BASA_LICENSE_TOKEN` inline) | El archivo de licencia (`.lic`) |
| `BASA_LICENSE_PUBLIC_KEYS_FILE` | Keyset público de verificación (default: el embebido) |
| `BASA_DEPLOYMENT_TENANT_ID` | Tenant del despliegue — debe coincidir con el de la licencia |
| `BASA_LICENSE_RECONCILE_INTERVAL_SECONDS` | Intervalo del job de reconciliación de seats (`<=0` lo desactiva) |
| `BASA_LICENSE_HARD_BLOCK` | `true` = endurecer el modo degradado a bloqueo total (ver abajo) |
| `BASA_DEPLOYMENT_KEY_FILE` | Clave de despliegue para los reportes de true-up (volumen persistente) |

### Qué consume un seat

Un seat es una **Connection activa** del tenant: una virtual key activa y no expirada.
El conteo no es por usuario — desactivar un usuario client **no** libera seats; lo que
libera un seat es **revocar sus Connections**. El propio error al agotar la licencia lo
indica: "Revocá una Connection o ampliá la licencia".

### Qué pasa al agotar los seats

Con los seats agotados, las altas gateadas por licencia (crear un usuario client o una
Connection) se **bloquean antes de provisionar nada**, con un error claro:

```text
HTTP 402
license_seat_limit_exceeded: 50/50 seats activos — la licencia no permite
crear más. Revocá una Connection o ampliá la licencia.
```

El tráfico de los usuarios existentes **no se corta**: solo se bloquea el alta. Una
instancia **sin licencia válida** arranca igual, pero rechaza toda creación de seats con
`403 license_creation_blocked` — fail-closed: "sin token" jamás significa "ilimitado".

### Estados de la licencia y modo degradado

El ciclo de vida se evalúa con el reloj local: `active → grace → expired`.

| Estado | Crear seats | Tráfico existente | Notas |
|---|:---:|:---:|---|
| `active` | ✅ | ✅ | Único estado que permite altas |
| `grace` | ❌ | ✅ **siempre** | Vencida dentro de los `grace_days`: urge renovar, pero el cliente opera |
| `expired` | ❌ | ✅ (default) / ❌ con hard block | Vencida más allá del grace |
| `missing` / `invalid` / `mismatch` | ❌ | ✅ | Sin token, firma inválida, o licencia de otro tenant |

El **modo degradado** por defecto es *read-only para creación*: en `grace`, `expired` u
`over_seat` (ver reconciliación) las altas se bloquean y el servicio sigue. Con
`BASA_LICENSE_HARD_BLOCK=true`, los estados `expired` y `over_seat` cortan **todo** el
tráfico del gateway (`/api/v1/gw`) con un `403` de mensaje genérico — el detalle del motivo va a
los logs del servidor, nunca al cliente sin autenticar. `grace` **jamás** corta tráfico,
con o sin hard block.

Dos guardas adicionales operan en segundo plano:

- **Reconciliación de seats** — un job periódico recuenta seats contra `max_seats` y
  publica el estado por tenant; si detecta `over_seat` (drift), las altas quedan
  bloqueadas hasta que una corrida vuelva a `ok`. Toda transición queda auditada.
- **Anti-rollback de reloj** — si el reloj local aparece *detrás* de la marca monotónica
  registrada, la evidencia de expiración deja de ser confiable y la creación se degrada
  hasta que el reloj la supere. El episodio queda auditado.

### Salud de la licencia para monitoreo

`GET /api/v1/health/license` expone la salud en **dos niveles**:

=== "Sin autenticación (probe de monitoreo)"

    Solo metadata mínima — apto para un health check externo sin filtrar
    dimensionamiento:

    ```bash
    curl -s https://<host>/api/v1/health/license
    ```

    ```json
    {"status": "active", "clock_rollback_suspected": false}
    ```

=== "Autenticado (tenant admin / compliance officer)"

    Con sesión JWT de un rol de operación, la respuesta agrega el detalle:
    `reason`, `expiry`, `grace_days`, `max_seats`, `seats_used`, el resumen de la
    última reconciliación y la identidad de la cadena de auditoría (`chain`, con la
    génesis que el emisor registró en el onboarding).

El endpoint nunca devuelve el token crudo ni material de claves — solo metadata.

### Renovación sin phone-home

La renovación (true-up) también es offline: la instancia genera un reporte firmado con la
clave de despliegue y el operador lo envía al emisor **fuera de banda**. En ningún punto
del ciclo de vida la instancia inicia conexiones salientes por licenciamiento.

Detalle completo del flujo (emisión, rotación de claves, true-up y postura de propiedad
intelectual): [Licenciamiento offline](../install-deploy/licensing.md).
