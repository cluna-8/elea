# Data model — 057 Porte de la redirección de modelos (Sentinel 068)

**Base**: se hereda **sin cambios de forma** el data-model de la 068 (Sentinel
`specs/068-politica-redireccionamiento-modelos/data-model.md`, `6a70855`) y las tablas del catálogo,
acceso y común de la 069 que trae la copia de `sentinel/` (HANDOFF §1(b)). Todas viven en la capa 2
(`sentinel/migrations/`, rama `sentinel_redirect`, que depende de `010` con `depends_on="010"`,
`sentinel:sentinel/migrations/0615e56e8251_redirect_tablas.py:23-25`), con `tenant_id` y RLS con el
patrón de `010_multitenant_foundation.py`. Nada guarda contenido de pedidos, PII ni secretos en claro.

Este documento lista **solo** lo que Eleia agrega o ajusta, marcado [BASE] (genérico, vuelve a Sentinel
por HANDOFF) o [ELEIA] (dato propio de la instalación). Las decisiones están en [research.md](./research.md);
las del owner del 2026-10-06 sobre el análisis legal (D1, D2, D5, D12, D3/D10) están en la spec
(Clarifications, Session 2026-10-06, decisiones legales) y en research R14, R23, R24 y R25.

## 0. Cadena de migraciones resultante

```text
backend (una sola cabeza, sin cambios):      … → 7a6fee614cfd → 199fe429762a
extensión (rama sentinel_redirect, depends_on 010):  0615e56e8251 → … → f7a3c1d9e508 → <hash nuevo de Eleia>
```

Orden exacto de la rama de la extensión (HANDOFF §1(c); `down_revision` verificado en `6a70855`), más
la migración nueva de Eleia:

| # | Revisión | Contenido | Origen |
|---|---|---|---|
| 1 | `0615e56e8251` | tablas de la 068 (política, posturas, publicados, reglas, destinos); `branch_labels = ("sentinel_redirect",)` | Sentinel |
| 2 | `7b2d4f8a9c10` | catálogo 069 (`ext_catalog_entry`, `ext_credential`, `ext_catalog_offer`, `ext_compliance_sheet`) | Sentinel |
| 3 | `c3f1a7d9e204` | informe de fidelidad (068 US5) | Sentinel |
| 4 | `e4a9c15b7d30` | catálogo, pantalla única | Sentinel |
| 5 | `a7d2f9c4b816` | acceso por perfiles | Sentinel |
| 6 | `d5b8e3a1c742` | estrategia por regla (`order` · `cheapest`) | Sentinel |
| 7 | `f7a3c1d9e508` | parámetros no soportados del catálogo | Sentinel |
| 8 | `<hash>` (por `alembic revision`, T026) | **región del perfil con postura por defecto (§1), reglas de habilitación explícita (§2), relajaciones del enmascarado forzado (§3) y jurisdicción de control en la ficha (§4)** | **Eleia [BASE]**, vuelve por HANDOFF |

- Sin `ALEMBIC_EXTRA_VERSION_LOCATIONS`: `heads = ['199fe429762a']`.
- Con la variable: `heads = ['199fe429762a', '<hash>']` y arranque con `upgrade heads` (S4).
- Ninguna migración de la extensión crea, altera ni borra tablas `LiteLLM_*` ni `_prisma_migrations`;
  sus FKs apuntan solo a `tenants`, `groups` y tablas propias (research R5; test T016).

## 1. Región del perfil (`sentinel_redirect_region`) [BASE] — FR-021, FR-030, FR-031, R13, R23

Reemplaza como fuente de verdad a `_ZONES`/`_REGION_PREFIX`/`region_codes` fijos
(`sentinel:sentinel/redirect/residency.py:26-49`); esa tabla fija queda como respaldo cuando no hay fila.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | uuid | |
| `level` | enum `installation` · `tenant` | `tenant` ⇒ `tenant_id` NOT NULL |
| `tenant_id` | fk nullable | la fila de empresa gana sobre la de instalación |
| `name` | texto | único por nivel/tenant; mayúsculas, sin espacios (p. ej. `AMERICAS`) |
| `jurisdictions` | lista de códigos | zonas o países ISO-3166 alfa-2; no vacía |
| `region_profiles` | lista de textos | regiones del perfil de país que resuelven a esta fila (p. ej. `latam_ar`, `latam`, `us`); un perfil aparece en una sola fila por nivel |
| `default_posture` | enum `reject_offregion` · `masked_offregion` · `masked_all` · `allow` | postura por defecto para pedidos **redirigidos** sin ninguna fila de postura (FR-031, R23); de fábrica `reject_offregion` (paridad con Sentinel) |
| `is_zone` | bool | si es verdadero, `name` se puede usar como código de zona en listas de jurisdicciones y en fichas (un país de `jurisdictions` satisface a la zona) |
| `created_by` / `updated_by` / timestamps | | |

Reglas:

- **Resolución de «mi región»**: `resolve_region` (tenant > instalación,
  `litellm/extensions/sentinel_guardian_policy.py:510`) → región del perfil (`latam_ar`) → fila cuya
  `region_profiles` la contiene (empresa > instalación) → `jurisdictions`. Sin fila: `region_codes` fijo
  da las jurisdicciones (comportamiento de Sentinel hoy), pero la **postura** del redirigido es la de
  respaldo en código (abajo). `tenant_region` sin valor en la identidad ni en `SENTINEL_ENTITY_REGION`
  ⇒ región **sin resolver** (no cae a `eu`; R28).
- **Respaldo en código** (FR-031, R28; QA B2): pedido redirigido sin fila de región que lo resuelva ⇒
  `offregion_masked` con `home = ∅` (forzado y fail-closed en todo destino) **y** alcance limitado a
  `region_codes(región)` (los destinos fuera se rechazan con 403); región sin resolver ⇒ 403
  `region_not_allowed` a todo lo redirigido. `default_posture_applied = code_fallback` en la auditoría y
  `GET /api/v1/redirect/health` responde 503 `region_row_missing`/`region_unresolved`.
- **Postura efectiva sin filas** (cambia `effective_posture`,
  `sentinel:sentinel/redirect/residency.py:90-120`, que hoy devuelve `allowlist[región]` para redirigido,
  `:95-98`): no redirigido ⇒ `off` (igual que hoy); redirigido ⇒ según `default_posture`:

  | `default_posture` | Postura efectiva | Destino en región (FR-028a) | Destino fuera de región |
  |---|---|---|---|
  | `reject_offregion` (fábrica) | `allowlist` con las jurisdicciones de la región (hoy) | sin forzado | rechazo 403 |
  | `masked_offregion` | `offregion_masked` con `home` = jurisdicciones de la región | sin forzado | enmascarado forzado, fail-closed |
  | `masked_all` (**Eleia**, D2) | `offregion_masked` con `home` = ∅ | enmascarado forzado, fail-closed | enmascarado forzado, fail-closed |
  | `allow` | `off` | sin forzado | sin forzado |

  Con **cualquier** valor, con cualquier fila de postura y con cualquier relajación, un pedido
  redirigido a un destino sin `inference_jurisdiction` cargada (`unknown` o vacía) se rechaza con 403
  (FR-028, FR-031; QA A8).

  **Glosario** (no confundir valores con modos): los valores de `default_posture` son de la región;
  los **modos** de postura de la 068 son `off`, `offregion_masked` y `allowlist`
  (`sentinel:sentinel/redirect/residency.py:19`). `reject_offregion` ⇒ modo `allowlist`;
  `masked_offregion` y `masked_all` ⇒ modo `offregion_masked` (con `home` = región o ∅); `allow` ⇒ modo
  `off`.
- **Postura efectiva con filas** (FR-023, FR-024, FR-031; R30; QA A8). Las filas de postura de la 068
  (`sentinel_redirect_posture`) ya guardan `created_by_role` (`sentinel:sentinel/redirect/models.py:79`):
  1. **Base** = la más estricta entre las filas de `compliance_officer`/`super_admin` aplicables (068
     FR-024); si no hay ninguna, la postura que da `default_posture` (o el respaldo en código).
  2. **Efectiva** = la más estricta entre la base y las filas de `tenant_admin` aplicables (las del admin
     de empresa solo restringen: una `off` suya no tiene efecto; una `allowlist` suya interseca).
  3. **Piso de enmascarado**: si `default_posture` es `masked_all` o `masked_offregion`, el forzado que
     esa postura impondría a un destino **se mantiene** aunque las filas no lo pidan
     (`forced = forced_por_base OR forced_por_filas_admin OR forced_por_piso`, donde `forced_por_base` es el
     forzado que la base del paso 1 le impone al destino —p. ej. una fila de cumplimiento
     `offregion_masked` con `home` = [AR]— y se calcula **antes** de combinar con las filas del admin: una
     `allowlist` del admin de empresa restringe el alcance pero nunca quita el forzado que impone la base;
     QA re-análisis U5). Si rige el **respaldo en código** (sin fila de
     región), el piso es forzado en **todo** destino y ninguna fila, de ningún rol, lo quita (QA re-análisis
     U1) ni una relajación por destino (§3; QA re-análisis M2); el alcance del respaldo (`region_codes`)
     tampoco lo amplía una fila.
  4. **Sin jurisdicción de inferencia** ⇒ 403, siempre.
  La API rechaza con 422 `posture_less_strict` una fila de `tenant_admin` **menos estricta** que la
  efectiva de su alcance; una igual o más estricta se acepta (FR-023: endurecer). Orden (QA re-análisis
  C2): entre modos, el de la 068 (`off < offregion_masked < allowlist`); dentro del mismo modo,
  `allowlist` A es al menos tan estricta como B si `jurisdicciones(A) ⊆ jurisdicciones(B)`, y
  `offregion_masked` A es al menos tan estricta como B si `home(A) ⊆ home(B)` (menos jurisdicciones «en
  casa» = más destinos forzados; `masked_all` equivale a `home = ∅`). Se compara siempre el `home`
  **resuelto**: una fila `offregion_masked` sin jurisdicciones resuelve `home` a las de la región, como en
  la 068 (QA re-análisis A1). Entre dos filas de cumplimiento rige el orden de la 068 tal cual (una
  `allowlist` de grupo gana sobre un `offregion_masked` de empresa y su forzado no se conserva): es paridad
  intencional, y en Eleia el piso de `masked_all` lo cubre. Dos filas no comparables (p. ej.
  listas que se solapan sin inclusión) se tratan como menos estricta ⇒ 422. Con `default_posture = allow`
  (efectiva `off`), cualquier fila del admin es más estricta y se acepta. Una fila de cumplimiento o super-admin puede ampliar el alcance respecto
  del default (068 FR-014a), pero nunca quita el piso: el piso solo lo quitan una relajación por destino
  (§3) o un cambio de `default_posture` (relajación por región, FR-031a).
- **Pre-completado del panel**: la postura *solo jurisdicciones permitidas* nueva se pre-completa con la
  lista de la región (FR-030).
- **Relajación por región** (FR-031a): cumplimiento (fila de nivel empresa, que gana sobre la de
  instalación) o super-admin (nivel instalación) cambia `default_posture` de `masked_all` a
  `masked_offregion` (o a otro valor), con motivo; queda registrada.
- **Quién escribe**: cumplimiento (nivel empresa) y super-admin (nivel instalación) **por rol real**
  (FR-023; R30): la autoridad de instalación derivada de `REDIRECT_OPERATOR_TENANT`
  (`sentinel:sentinel/redirect/api/admin.py:83-100`) no alcanza para escribir regiones, `default_posture`
  ni relajaciones, y Eleia no define esa variable; el admin de empresa solo lee; cambios registrados en
  `sentinel_redirect_config_audit` con `entity = region` (FR-008).

**Dato [ELEIA]** (`deploy/redirect-seeds/regions.americas.yaml`, sembrado por T064; decisión del owner
D2 del 2026-10-06):

```yaml
regions:
  - name: AMERICAS
    level: installation
    is_zone: true
    region_profiles: [latam_ar, latam, us]
    default_posture: masked_all      # D2: enmascarado forzado con analizador fail-closed, dentro y fuera de AMERICAS
    # AMERICAS es criterio de riesgo, no de legalidad (D3)
    jurisdictions: [US, CA, MX,                                   # Norte
                    BZ, CR, SV, GT, HN, NI, PA,                   # Centro
                    AG, BS, BB, CU, DM, DO, GD, HT, JM, KN, LC, VC, TT, PR,   # Caribe
                    AR, BO, BR, CL, CO, EC, GY, PY, PE, SR, UY, VE,           # Sur
                    LATAM]                                        # zona existente: la cubre
```

La lista y la postura por defecto son editables; cambiarlas es un cambio de dato registrado, no de
código.

## 2. Reglas de habilitación explícita (`ext_catalog_enablement_rule`) [BASE] — FR-029, R14

Reemplaza el `provider == "deepseek"` fijo (`sentinel:sentinel/catalog/api/admin.py:503`,
`sentinel:sentinel/catalog/seed.py:86`, `sentinel:sentinel/catalog/api/legacy.py:157`);
`sentinel:sentinel/catalog/migrate.py:101` copia el valor de origen y no cambia.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | uuid | |
| `level` / `tenant_id` | como §1 | la empresa solo puede **agregar** reglas (endurecer) |
| `kind` | enum `provider` · `api_host` · `jurisdiction` | |
| `value` | texto | `provider`: un valor de `PROVIDERS` (`sentinel:sentinel/catalog/models.py:31-33`); `api_host`: host exacto o comodín de un solo nivel a la izquierda (`dashscope*.aliyuncs.com`); `jurisdiction`: código ISO o zona |
| `reason` / `created_by` / `created_by_role` / timestamps | | obligatorios |

Reglas:

- Una entrada del catálogo nace (o pasa a) `blocked_by_default = true` si **alguna** regla aplicable
  coincide con su `provider`, con el host de su `api_base` o, para `jurisdiction`, con la
  `inference_jurisdiction`, la `entity_jurisdiction` o la `control_jurisdiction` (§4) de su ficha.
  Cambiar `provider`, `api_base` o la ficha re-evalúa la regla y, si pasa a bloqueada, borra una
  habilitación previa (queda registrado).
- **Listas vacías ⇒ ninguna entrada bloqueada por defecto**, y todo el resto funciona igual (test T025).
- La habilitación sigue siendo la de la 068/069: `enabled_at`, `enabled_by`, `enable_reason`
  (obligatorio) en `ext_catalog_entry` (`sentinel:sentinel/catalog/models.py:120-123`), con los roles
  de `require_role("admin", "compliance_officer")` (`sentinel:sentinel/catalog/api/admin.py:608-609`),
  registrada en el registro de cambios. Habilitar **no** relaja la residencia: la postura se evalúa igual.
- Paridad: el seed de Sentinel equivalente a su comportamiento actual es `provider: deepseek`.

**Dato [ELEIA]** (`deploy/redirect-seeds/habilitacion-explicita.yaml`, sembrado por T028; decisión del
owner D1 del 2026-10-06): las tres listas **vacías**. Ningún destino nace bloqueado; las jurisdicciones de
preocupación, si el cliente quiere tenerlas, se cargan como reglas `jurisdiction` desde el panel.

```yaml
# D1 (2026-10-06): sin bloqueo por defecto en Eleia; todo configurable desde el panel.
providers: []
api_hosts: []
jurisdictions: []
```

## 3. Relajación del enmascarado forzado por destino (`sentinel_redirect_masking_relaxation`) [BASE] — FR-031a, R24

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | uuid | |
| `level` / `tenant_id` | como §1 | nivel instalación solo super-admin; nivel empresa, cumplimiento de esa empresa |
| `entry_id` | fk `ext_catalog_entry.id` (`ondelete CASCADE`) | única por (`level`, `tenant_id`, `entry_id`) |
| `reason` | texto | obligatorio |
| `created_by` / `created_by_role` / timestamps | | obligatorios; rol `compliance_officer` o `super_admin` |
| `revoked_at` / `revoked_by` / `revoke_reason` | | la baja no borra la fila (historial) |

Reglas:

- **Precondiciones al crear** (si falla alguna ⇒ 422 con el motivo, sin crear): la ficha de la entrada
  (`ext_compliance_sheet`) tiene `inference_jurisdiction`, `entity_jurisdiction` y `control_jurisdiction`
  cargadas (ninguna `unknown`/vacía), `zero_data_retention = true`
  (`sentinel:sentinel/catalog/models.py:155`) y, si la entrada es de un agregador (`openrouter`),
  `provider_options.providers_allowlist` no vacía. Nunca hay relajaciones sembradas: no es un default
  (D5).
- **Efecto**: con una relajación vigente para la empresa del pedido (empresa > instalación), ese
  destino sale **sin enmascarado forzado**, venga el forzado del piso de `default_posture` o de una fila
  `offregion_masked`. No vuelve alcanzable un destino fuera de una `allowlist` ni habilita un destino sin
  `inference_jurisdiction` (sigue rechazado). **Mientras rige el respaldo en código** (sin fila de región,
  §1), ninguna relajación tiene efecto: el pedido sale enmascarado y fail-closed (QA re-análisis M2).
- **Re-evaluación**: (a) al resolver cada pedido, una relajación cuya ficha ya no cumple las
  precondiciones no tiene efecto (T060, desde la instantánea); (b) al guardar la ficha, la API del
  catálogo marca `revoked_at` con `revoke_reason = precondicion_incumplida` y lo registra (FR-008; T087).
- Cambios en `sentinel_redirect_config_audit` con `entity = masking_relaxation`.

## 4. Destino = entrada del catálogo (`ext_catalog_entry`) y su ficha (`ext_compliance_sheet`) — deltas

**Ficha** (`sentinel:sentinel/catalog/models.py:146-163`, 1:1 con la entrada): **una columna nueva**
[BASE] (FR-028a, D12, R25):

| Campo | Estado | Uso en Eleia |
|---|---|---|
| `provider_legal_entity` | ya existe (`:151`) | **entidad responsable** de FR-028a (quien opera la inferencia) |
| `entity_jurisdiction` | ya existe (`:152`) | jurisdicción de la entidad |
| `control_jurisdiction` | **nueva**, `String(8)` (mismo tipo que `entity_jurisdiction`, `sentinel:sentinel/catalog/models.py:152`; QA B-1), nullable | jurisdicción de quien posee el 50 % o más de la entidad o la controla; NULL = sin cargar |
| `inference_jurisdiction` | ya existe (`:153`, default `unknown`) | jurisdicción de inferencia |
| `zero_data_retention` | ya existe (`:155`, NULL = desconocido) | precondición de la relajación por destino (§3) |

**Quién escribe la ficha** [BASE] (FR-023; R30; QA A7): `provider_legal_entity`, `entity_jurisdiction`,
`control_jurisdiction`, `inference_jurisdiction` y `zero_data_retention` solo `compliance_officer` y
`super_admin` (hoy `SHEET_WRITERS = ("admin","compliance_officer")`, `sentinel:sentinel/catalog/api/admin.py:41`);
el admin de empresa edita el resto de la ficha y recibe 403 si el cuerpo cambia alguno de esos campos.

**Regla «en región»** [BASE] (cambia `evaluate`, `sentinel:sentinel/redirect/residency.py:122-135`, que
hoy mira solo inferencia y entidad): un destino está dentro de un conjunto de jurisdicciones solo si
`inference_jurisdiction`, `entity_jurisdiction` **y** `control_jurisdiction` lo satisfacen. Con
`control_jurisdiction` NULL o fuera: bajo `allowlist` se trata como entidad ajena (`foreign_entity`,
solo con `accept_foreign_entity`); bajo `offregion_masked`, como fuera de región (forzado). El semáforo
del catálogo (FR-030a, R16) usa la misma regla. Es un cambio de comportamiento para Sentinel (fichas sin
control cargado dejan de contar como en región): va explicado en el HANDOFF.

**Entrada** — ajustes de uso:

| Campo | Ajuste en Eleia |
|---|---|
| `provider` / `api_base` / credencial | Azure: credencial **adoptada** `AZURE_API_KEY` (`allow_any_env`, `sentinel:sentinel/catalog/credentials.py:56-68`) + `api_version`; sin duplicar el secreto (FR-020, R9) |
| `status` | una entrada `azure` cuyo `real_model` no corresponde a un despliegue queda `inactive` con el motivo `deployment_not_found` hasta pasar la verificación (R9) |
| `provider_options` (OpenRouter) | `providers_allowlist` **obligatoria y no vacía**; `zdr` y `data_collection = deny` los fuerza el guard en cada pedido, no son editables a `false` (FR-032, R19) |
| `features` | se suma `session_affinity` (T-F, FR-043) a las existentes (`cache_control` ya está en `FEATURES`, `sentinel:sentinel/catalog/models.py:43`) |
| `price_cache_read` / `price_cache_write` | ya existen (`sentinel:sentinel/catalog/models.py:108-109`); los usa T-F (FR-046) |
| `blocked_by_default` | derivado de §2, no del proveedor fijo |

## 5. Evento de redirección — campos agregados a `routing_decision.extensions.redirect`

Se escriben por S7 (`9c7bf08`, `8ceab22`) en `audit_logs.routing_decision` (`backend/src/models/audit.py:47`);
solo metadata, acotada por S7:

| Campo | Tipo | Cuándo |
|---|---|---|
| `dropped_fields` | lista de **nombres** de campo | T139 de Sentinel: campos quitados hacia un traducido |
| `betas_dropped` | entero | T094 de Sentinel: cantidad de cabeceras beta descartadas |
| `count_tokens_mode` | `forwarded` · `estimated` · `not_found` | T093 de Sentinel |
| `adjusted_params` | lista (ya existe en Sentinel) | piso de 16 tokens, `max_completion_tokens` |
| `default_posture_applied` | `reject_offregion` · `masked_offregion` · `masked_all` · `allow` · `code_fallback` · null | R23: solo si no hubo postura explícita; `code_fallback` = respaldo en código sin fila de región (R28; nombre distinto de los fallbacks de las reglas de mapeo) |
| `masking_scope` | `full` · `user` · null | R29: alcance del enmascarado del pedido (S14) |
| `unanalyzable_kinds` | lista de **nombres de tipo** (`image`, `pdf_no_text`, `pdf_timeout`, `pdf_resource_limit`, `pdf_error`, `structural_entity`, `redacted_thinking`, …; QA v2 N4, N8) | R29: solo cuando hubo bloqueo por no analizable; nunca contenido |
| `masking_relaxation` | `region` · `destination` · null | R24: `destination` si una relajación por destino quitó el forzado; `region` siempre que el destino está en región y la fila de región efectiva tiene `default_posture = masked_offregion` (decidible en el pedido, sin historial; QA re-análisis L1) |
| `in_region` | bool | FR-028a: resultado de la regla «en región» (sin nombres de entidad) |
| `openrouter_zdr` | bool | R19 |
| `cache_read_tokens` / `cache_write_tokens` | entero | T-F, FR-046 |
| `price_cache_missing` | bool | T-F: se cobró a precio de entrada |
| `nonce_scope` | `conversation` · `request` | T-F (S13); nunca el valor del sufijo ni el identificador |

## 6. Contrato de metadata interna de S13 [BASE] — FR-045, R18

| Clave (metadata interna del pedido al motor) | Quién la escribe | Qué contiene |
|---|---|---|
| `sentinel_conversation_ref` | solo la pasarela (`pre_engine` de la extensión); la que mande el cliente se descarta | identificador de conversación ya derivado: `HMAC(MASKING_NONCE_KEY, "conv" \| tenant \| id de sesión de la herramienta)` (research R18), nunca el original; sin la clave, no se escribe |

El guardrail, con esa clave presente y `MASKING_NONCE_KEY` configurada, deriva
`nonce = HMAC(MASKING_NONCE_KEY, "nonce" | tenant | llave | conversation_ref)` truncado a **4 caracteres
hexadecimales** (`hexdigest()[:4]`, el mismo ancho que el sufijo aleatorio de hoy; QA re-análisis A1) y los
índices por valor con la misma clave; sin alguna de las dos, `PlaceholderMap()` aleatorio como hoy
(`litellm/extensions/sentinel_guardian_policy.py:784`). Detalle en
[contracts/costuras-base.md §S13](./contracts/costuras-base.md).

## Transiciones nuevas

- Región: `default_posture` entre `reject_offregion`, `masked_offregion`, `masked_all` y `allow` (cada
  cambio auditado con motivo; solo cumplimiento o super-admin).
- Regla de habilitación: alta/baja (la empresa solo alta); cada cambio re-evalúa
  `blocked_by_default` de las entradas afectadas.
- Relajación por destino: `vigente → revocada` (por cumplimiento, o automática si la ficha deja de
  cumplir las precondiciones).
- Entrada `azure`: `inactive (deployment_not_found) → active` al pasar la verificación.
