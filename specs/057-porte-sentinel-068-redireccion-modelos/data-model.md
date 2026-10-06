# Data model — 057 Porte de la redirección de modelos (Sentinel 068)

**Base**: se hereda **sin cambios de forma** el data-model de la 068 (Sentinel
`specs/068-politica-redireccionamiento-modelos/data-model.md`, `6a70855`) y las tablas del catálogo,
acceso y común de la 069 que trae la copia de `sentinel/` (HANDOFF §1(b)). Todas viven en la capa 2
(`sentinel/migrations/`, rama `sentinel_redirect`, colgada de `010`), con `tenant_id` y RLS con el patrón
de `010_multitenant_foundation.py`. Nada guarda contenido de pedidos, PII ni secretos en claro.

Este documento lista **solo** lo que Eleia agrega o ajusta, marcado [BASE] (genérico, vuelve a Sentinel
por HANDOFF) o [ELEIA] (dato propio de la instalación). Las decisiones están en [research.md](./research.md).

## 0. Cadena de migraciones resultante

```text
backend (una sola cabeza, sin cambios):      … → 7a6fee614cfd → 199fe429762a
extensión (rama sentinel_redirect, de 010):  0615e56e8251 → … → f7a3c1d9e508 → <hash nuevo de Eleia>
```

Orden exacto de la rama de la extensión (HANDOFF §1(c)), más la migración nueva de Eleia:

| # | Revisión | Contenido | Origen |
|---|---|---|---|
| 1 | `0615e56e8251` | tablas de la 068 (política, posturas, publicados, reglas, destinos) | Sentinel |
| 2 | `7b2d4f8a9c10` | catálogo 069 (`ext_catalog_entry`, credenciales, ofertas, fichas) | Sentinel |
| 3 | `c3f1a7d9e204` | informe de fidelidad (068 US5) | Sentinel |
| 4 | `e4a9c15b7d30` | catálogo, pantalla única | Sentinel |
| 5 | `a7d2f9c4b816` | acceso por perfiles | Sentinel |
| 6 | `d5b8e3a1c742` | estrategia por regla (`order` · `cheapest`) | Sentinel |
| 7 | `f7a3c1d9e508` | parámetros no soportados del catálogo | Sentinel |
| 8 | `<hash>` (por `alembic revision`, T026) | **región del perfil y reglas de habilitación explícita** (§1, §2) | **Eleia [BASE]**, vuelve por HANDOFF |

- Sin `ALEMBIC_EXTRA_VERSION_LOCATIONS`: `heads = ['199fe429762a']`.
- Con la variable: `heads = ['199fe429762a', '<hash>']` y arranque con `upgrade heads` (S4).
- Ninguna migración de la extensión crea, altera ni borra tablas `LiteLLM_*` ni `_prisma_migrations`;
  sus FKs apuntan solo a `tenants`, `groups` y tablas propias (research R5; test T016).

## 1. Región del perfil (`sentinel_redirect_region`) [BASE] — FR-021, FR-030, FR-031, R13, R23

Reemplaza como fuente de verdad a `_ZONES`/`_REGION_PREFIX`/`region_codes` fijos
(`sentinel:sentinel/redirect/residency.py:22-48`); esa tabla fija queda como respaldo cuando no hay fila.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | uuid | |
| `level` | enum `installation` · `tenant` | `tenant` ⇒ `tenant_id` NOT NULL |
| `tenant_id` | fk nullable | la fila de empresa gana sobre la de instalación |
| `name` | texto | único por nivel/tenant; mayúsculas, sin espacios (p. ej. `AMERICAS`) |
| `jurisdictions` | lista de códigos | zonas o países ISO-3166 alfa-2; no vacía |
| `region_profiles` | lista de textos | regiones del perfil de país que resuelven a esta fila (p. ej. `latam_ar`, `latam`, `us`); un perfil aparece en una sola fila por nivel |
| `offregion_default` | enum `reject` · `masked` · `allow` | default de postura para pedidos **redirigidos** sin ninguna fila de postura (R23); de fábrica `reject` |
| `is_zone` | bool | si es verdadero, `name` se puede usar como código de zona en listas de jurisdicciones y en fichas (un país de `jurisdictions` satisface a la zona) |
| `created_by` / `updated_by` / timestamps | | |

Reglas:

- **Resolución de «mi región»**: `resolve_region` (tenant > instalación,
  `litellm/extensions/sentinel_guardian_policy.py:510`) → región del perfil (`latam_ar`) → fila cuya
  `region_profiles` la contiene (empresa > instalación) → `jurisdictions`. Sin fila: respaldo fijo de
  `region_codes` (comportamiento de Sentinel hoy).
- **Postura efectiva sin filas** (cambia `effective_posture`, `sentinel:…/residency.py:90-120`): no
  redirigido ⇒ `off` (igual que hoy); redirigido ⇒ según `offregion_default`: `reject` ⇒ `allowlist`
  con las jurisdicciones de la región (comportamiento de hoy); `masked` ⇒ `offregion_masked` con
  `home` = jurisdicciones de la región; `allow` ⇒ `off`. Una fila explícita siempre gana.
- **Pre-completado del panel**: la postura *solo jurisdicciones permitidas* nueva se pre-completa con la
  lista de la región (FR-030).
- Escriben cumplimiento (nivel empresa) y super-admin (nivel instalación) (FR-023); cambios registrados
  en `sentinel_redirect_config_audit` con `entity = region` (FR-008).

**Dato [ELEIA]** (`deploy/redirect-seeds/regions.americas.yaml`, sembrado por T064):

```yaml
regions:
  - name: AMERICAS
    level: installation
    is_zone: true
    region_profiles: [latam_ar, latam, us]
    offregion_default: reject        # PENDIENTE del análisis legal (R23); reject = default de fábrica
    jurisdictions: [US, CA, MX,                                   # Norte
                    BZ, CR, SV, GT, HN, NI, PA,                   # Centro
                    AG, BS, BB, CU, DM, DO, GD, HT, JM, KN, LC, VC, TT, PR,   # Caribe
                    AR, BO, BR, CL, CO, EC, GY, PY, PE, SR, UY, VE,           # Sur
                    LATAM]                                        # zona existente: la cubre
```

La lista es editable; agregar o quitar un país es un cambio de dato registrado, no de código.

## 2. Reglas de habilitación explícita (`ext_catalog_enablement_rule`) [BASE] — FR-029, R14

Reemplaza el `provider == "deepseek"` fijo (`sentinel:sentinel/catalog/api/admin.py:503`, `seed.py:86`,
`api/legacy.py:157`, `migrate.py:101`).

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | uuid | |
| `level` / `tenant_id` | como §1 | la empresa solo puede **agregar** reglas (endurecer) |
| `kind` | enum `provider` · `api_host` · `jurisdiction` | |
| `value` | texto | `provider`: un valor de `PROVIDERS`; `api_host`: host exacto o comodín de un solo nivel a la izquierda (`dashscope*.aliyuncs.com`); `jurisdiction`: código ISO o zona |
| `reason` / `created_by` / `created_by_role` / timestamps | | obligatorios |

Reglas:

- Una entrada del catálogo nace (o pasa a) `blocked_by_default = true` si **alguna** regla aplicable
  coincide con su `provider`, con el host de su `api_base` o con su `inference_jurisdiction` /
  `entity_jurisdiction` de la ficha. Cambiar `provider`, `api_base` o la ficha re-evalúa la regla y,
  si pasa a bloqueada, borra una habilitación previa (queda registrado).
- **Listas vacías ⇒ ninguna entrada bloqueada por defecto**, y todo el resto funciona igual (test T025).
- La habilitación sigue siendo la de la 068/069: `enabled_at`, `enabled_by`, `enable_reason`
  (obligatorio) en `ext_catalog_entry`, solo con rol permitido (compliance_officer o super_admin; en
  nivel instalación, super_admin), registrada en el registro de cambios. Habilitar **no** relaja la
  residencia: la postura se evalúa igual.
- Paridad: el seed de Sentinel equivalente a su comportamiento actual es `provider: deepseek`.

**Dato [ELEIA]** (`deploy/redirect-seeds/habilitacion-explicita.yaml`, sembrado por T028): **pendiente
del análisis legal** que pidió el owner (R14). Hasta tenerlo, el archivo queda con las tres listas
vacías y la anotación «pendiente del análisis legal»; las opciones (a)–(d) están en research R14.

## 3. Destino = entrada del catálogo (`ext_catalog_entry`) — deltas

Sin columnas nuevas; ajustes de uso:

| Campo | Ajuste en Eleia |
|---|---|
| `provider` / `api_base` / credencial | Azure: credencial **adoptada** `AZURE_API_KEY` (`allow_any_env`) + `api_version`; sin duplicar el secreto (FR-020, R9) |
| `status` | una entrada `azure` cuyo `real_model` no corresponde a un despliegue queda `inactive` con el motivo `deployment_not_found` hasta pasar la verificación (R9) |
| `provider_options` (OpenRouter) | `providers_allowlist` **obligatoria y no vacía**; `zdr` y `data_collection = deny` los fuerza el guard en cada pedido, no son editables a `false` (FR-032, R19) |
| `features` | se suma `session_affinity` (T-F, FR-043) a las existentes (`cache_control` ya está en `FEATURES`, `sentinel:sentinel/catalog/models.py:43`) |
| `price_cache_read` / `price_cache_write` | ya existen (`sentinel:…/models.py:110-111`); los usa T-F (FR-046) |
| `blocked_by_default` | derivado de §2, no del proveedor fijo |

## 4. Evento de redirección — campos agregados a `routing_decision.extensions.redirect`

Se escriben por S7 (`9c7bf08`, `8ceab22`) en `audit_logs.routing_decision` (`backend/src/models/audit.py:47`);
solo metadata, acotada por S7:

| Campo | Tipo | Cuándo |
|---|---|---|
| `dropped_fields` | lista de **nombres** de campo | T139: campos quitados hacia un traducido |
| `betas_dropped` | entero | T094: cantidad de cabeceras beta descartadas |
| `count_tokens_mode` | `forwarded` · `estimated` · `not_found` | T093 |
| `adjusted_params` | lista (ya existe en Sentinel) | piso de 16 tokens, `max_completion_tokens` |
| `offregion_default_applied` | `reject` · `masked` · `allow` · null | R23: solo si no hubo postura explícita |
| `openrouter_zdr` | bool | R19 |
| `cache_read_tokens` / `cache_write_tokens` | entero | T-F, FR-046 |
| `price_cache_missing` | bool | T-F: se cobró a precio de entrada |
| `nonce_scope` | `conversation` · `request` | T-F (S13); nunca el valor del sufijo ni el identificador |

## 5. Contrato de metadata interna de S13 [BASE] — FR-045, R18

| Clave (metadata interna del pedido al motor) | Quién la escribe | Qué contiene |
|---|---|---|
| `sentinel_conversation_ref` | solo la pasarela (`pre_engine` de la extensión); la que mande el cliente se descarta | identificador de conversación ya derivado: `HMAC(clave del servidor, id de sesión de la herramienta)`, nunca el original |

El guardrail, con esa clave presente y `MASKING_NONCE_KEY` configurada, deriva
`nonce = HMAC(MASKING_NONCE_KEY, tenant | llave | conversation_ref)[:4]` y los índices por valor con la
misma clave; sin alguna de las dos, `PlaceholderMap()` aleatorio como hoy. Detalle en
[contracts/costuras-base.md §S13](./contracts/costuras-base.md).

## Transiciones nuevas

- Región: `offregion_default` `reject ⇄ masked ⇄ allow` (cada cambio auditado con motivo).
- Regla de habilitación: alta/baja (la empresa solo alta); cada cambio re-evalúa
  `blocked_by_default` de las entradas afectadas.
- Entrada `azure`: `inactive (deployment_not_found) → active` al pasar la verificación.
