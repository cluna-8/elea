# HANDOFF elea → Sentinel — fix del CI de `main` (oct-2026)

**De**: Atlas, coordinador de `cluna-8/elea`. **Para**: el coordinador de `cluna-8/sentinel`.
**Fecha**: 6-oct-2026. **PR de origen**: cluna-8/elea#5 (merge `8999e27`).
**Detalle completo**: [`DIAGNOSTICO-CI-main-2026-10.md`](DIAGNOSTICO-CI-main-2026-10.md) (§13) y
[`QA-CI-main-2026-10.md`](QA-CI-main-2026-10.md).

## Qué pasó

El CI de `main` de elea estuvo en rojo del 31-ago al 6-oct-2026 con cinco causas apiladas. Dos son
bugs de **base** que Sentinel puede tener igual o recibir con las specs 054 y 055: migraciones que no
se pueden re-ejecutar y un endpoint que publicaba el nombre de un motor en el OpenAPI. El resto son
tests de base que asumían datos propios de una línea.

## Qué portar (base), en este orden

| # | Archivo | Commit en elea | Qué cambia | ¿Obligatorio? |
|---|---|---|---|---|
| 1 | `backend/alembic/versions/7a6fee614cfd_groups_deactivation.py` | `05511a9` | `ADD COLUMN IF NOT EXISTS` / `DROP COLUMN IF EXISTS`; mismo id y mismo `down_revision`; no-op en bases ya migradas | **Sí**, si se trae la 054. No importar la versión anterior |
| 2 | `backend/alembic/versions/199fe429762a_users_must_change_password.py` | `05511a9` | Igual que la anterior | **Sí**, si se trae la 055 |
| 3 | `backend/tests/test_policy_unit.py` | `f71ccd6` | `latam_ar` se compara con `⊇` en vez de igualdad: la tabla de Sentinel no trae CBU y tiene que seguir en verde | Recomendado |
| 4 | `backend/tests/integration/test_chat_auto_router.py` | `2975234` | Fixture `catalogo_temporal` (autouse, autocontenida, con deployments sintéticos): el test deja de depender del catálogo de dev | Recomendado |
| 5 | `backend/tests/contract/test_catalogo_motor_paralelismo.py` | `2975234` | `skip` con motivo si el catálogo de dev no declara un `ollama_chat/`; apunta a `test_engine_local_limits.sh` | Recomendado |
| 6 | `backend/src/api/chat.py` (`POST /chat/rag-usage`) | `266b644` | `description=` neutro en el decorador; el docstring pasa a comentario | Solo si Sentinel adopta el endpoint (spec 053) |
| 7 | `deploy/Makefile` (`check-docs`) | `34fba21` | Ya no corta en el primer fallo: corre todos los pasos y lista todos los fallos | Opcional (proceso) |

## Qué NO portar (propio de Eleia)

- `.env.example` (sección «Eleia Hub y motores») y `docs/docs/api-reference/*` (`openapi.json`, `configuration.md`), commit `82f56b1`.
- Las decisiones de producto de esta línea que explican los tests: catálogo de dev solo con Azure y CBU en `latam_ar`.

## Cómo verificarlo del lado de Sentinel

`docker compose run --rm --no-deps backend alembic upgrade head` dos veces seguidas sin error, y
`pytest tests/test_migration_0*.py tests/test_policy_unit.py tests/integration/test_chat_auto_router.py -q`
en verde con la tabla de Sentinel, sin CBU.

## Proceso (D8)

En elea se propone proteger `main` con la suite de backend como check requerido. Lo decide el owner de
cada repo.
