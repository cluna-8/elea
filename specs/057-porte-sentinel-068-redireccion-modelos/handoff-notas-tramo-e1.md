# Notas del tramo T-E (E1) para el HANDOFF a Sentinel (insumo de T085)

> Insumo, no el HANDOFF: lo que el tramo T-E (parte E1) escribió **genérico** y tiene que volver a Sentinel
> (`cluna-8/sentinel`). Cambia comportamiento de la base de Sentinel en los puntos marcados «⚠ cambia».

## Costura de base `backend/` (retrocompatible) — S16

| Qué | Dónde | Prueba |
|---|---|---|
| `run_plugin_startup()`: corre el `on_startup()` opcional de cada paquete de `PLUGIN_PACKAGES` (síncrono con `asyncio.to_thread`, corrutina con `await`), en el orden de la variable, antes del `yield` del `_lifespan` y después de arrancar los schedulers; un fallo se registra con el nombre del paquete y no tira el arranque | `backend/src/plugins.py`, `backend/src/main.py` (`_lifespan`), `.env.example` (comentario de `PLUGIN_PACKAGES`) | `backend/tests/unit/test_plugin_startup.py` (contra `src.main:app` con su `lifespan` real; incluye el canario del `APIRouter(on_startup=…)`) |

## Extensión `sentinel/`

- **Región como dato** (`redirect/residency.py`): `resolve_region` (empresa > instalación > respaldo fijo `region_codes`), zonas de
  datos (`is_zone`), `default_posture` con sus cuatro valores (`masked_all` = `offregion_masked` con casa vacía), **piso de
  enmascarado** que las filas no quitan, postura efectiva en dos niveles (filas de `compliance_officer`/`super_admin` = base; filas
  del `tenant_admin` solo restringen), respaldo en código sin fila de región, relajaciones por destino.
  - ⚠ cambia: sin fila de región, el redirigido sale forzado y limitado a `region_codes(región)` (antes: `allowlist[región]` sin
    forzado). **Sentinel debe sembrar su fila `reject_offregion`** (paridad) con `regions_seed`.
  - ⚠ cambia: la regla «en región» exige también la **jurisdicción de control** (`control_jurisdiction` sin cargar ⇒ entidad ajena
    bajo allowlist, fuera de región bajo `offregion_masked`).
  - ⚠ cambia: destino sin jurisdicción de inferencia ⇒ rechazado con **cualquier** postura, fila o relajación (antes, `off` lo dejaba pasar).
  - ⚠ cambia: `tenant_region`/`list_postures`/`run_fidelity` no caen a `eu`: una sola función, `residency.resolve_profile`.
- **API** (`redirect/api/admin.py`): `GET/POST/PATCH/DELETE /regions`, `GET /regions/effective`, `GET/POST/DELETE /masking-relaxations`,
  `GET /health` (sin sesión; 200 o 503 `region_row_missing` / `region_unresolved`), 422 `posture_less_strict`, `GET /capabilities` suma
  `manages_regions`, escritura por **rol real** (`REDIRECT_OPERATOR_TENANT` no da autoridad sobre regiones, `default_posture` ni relajaciones;
  sí sigue valiendo para filas de postura, que quedan como autoridad de instalación), id publicado de la cara Claude con prefijo `claude`.
- **Seeds**: `redirect/regions_seed.py` (`python -m sentinel.redirect.regions_seed <archivo>`; crea, **no pisa** lo que un administrador cambió;
  todo o nada) y `redirect/seed_on_startup.py` (`REDIRECT_SEED_FILES`, cerrojo consultivo de Postgres, un archivo inválido no frena a los demás),
  expuesto como `on_startup()` de `sentinel.redirect.api`.
- **Guard y autorización** (`engine/`): `masking_ok(report, forced=True)` exige `scope == "full"` y `unanalyzable == 0` (informe viejo ⇒ bloqueo,
  ⚠ cambia); OpenRouter con cero retención (`zdr`, `data_collection = deny`, `only` = lista firmada en la autorización, `provider` del cliente
  descartado, sin lista ⇒ 503 `destination_misconfigured`, `openrouter_zdr` en la auditoría); `provider` en `CLIENT_CREDENTIAL_FIELDS`;
  `Grant.provider_options` firmado.
- **Catálogo**: H1 (`catalog/api_base.py`: https y hosts públicos para entradas de empresa; `CATALOG_ALLOW_PRIVATE_API_BASE` para on-prem),
  H2 (`catalog/relaxation.py`: la relajación por destino se revoca si cambian `provider`, `api_base`, `real_model`, `is_aggregator` o la lista
  de proveedores; también al archivar), alta/PATCH de `openrouter` sin `providers_allowlist` ⇒ 422, semáforo contra la región efectiva
  (`region_label`).
- **Plugin** (`redirect/plugin.py`): el forzado enciende `pii_masking` y `nlp_fail_mode = block` de la pasarela; `default_posture_applied`,
  `in_region` y `masking_relaxation` en `routing_decision.extensions.redirect`; la lista de proveedores de OpenRouter viaja firmada.
- **Panel** (`sentinel/frontend/**`): Residencia con postura por defecto, relajaciones y pre-completado; etiqueta «Dentro de <región>»; el
  texto de `EntryForm` ya no nombra a Sentinel (H7).

## Pendiente que no es de este tramo (E2: S14)

- El guardrail del motor aún no emite `scope`, `unanalyzable` ni `unanalyzable_kinds` ni lee `sentinel_forced_masking`: **mientras E2 no se
  integre, todo pedido forzado se bloquea con `masking_required`** (falla cerrado). La señal en `pre_engine` y `masking_scope` en el camino de
  suscripción son de T097; `masking_scope` del guard ya sale en la decisión cuando el forzado se verificó.
- El enmascarado se enciende en el plano de la pasarela por `governance_overrides` al resolver; si una sustitución por capacidad en
  `pre_engine` pasa a un destino forzado que el primero no era, el guard igual verifica el informe (fail-closed) pero no lo enciende: lo cubre la
  señal de S14.
- Las migraciones de la base y de la extensión por `upgrade heads`, la RLS real y la corrida con dos workers son de la suite 🐳 (T065).
- `catalog/migrate.py` (migración única de la 068) copia `api_base` de filas existentes sin validarla (H1 no la cubre).
