# Handoff — spec 054 (Elea) para llevar a Sentinel

**Fecha**: 17-sep-2026. **Origen**: `github.com/cluna-8/elea`, rama `main`. **Destino**:
`cluna-8/sentinel` (producto base, "Guardian").

Es código de base, no de la localización argentina: `Group` sin ciclo de vida es un hueco del
producto genérico, no algo específico de Eleia. Se implementó acá porque acá se reportó
(probando la spec 053 en vivo), no porque sea un problema propio de esta localización — mismo
criterio ya aplicado al fix del paracaídas `latam_ar` y a la atribución de gasto de la spec 053.

## 1. Qué se hizo

Hasta esta spec, `Group` (equipos) no tenía ningún campo de ciclo de vida — se podía crear pero
nunca dar de baja, a diferencia de `User`, que ya tiene `is_active`/`deactivated_at` desde hace
tiempo (spec 043 US5). Se replicó el mismo patrón para equipos:

| Pieza | Dónde |
|---|---|
| Migración (agrega `is_active`/`deactivated_at` a `groups`) | `backend/alembic/versions/7a6fee614cfd_groups_deactivation.py` |
| Modelo | `backend/src/models/user.py`, clase `Group` |
| Schema de respuesta | `backend/src/schemas/user.py`, `GroupResponse` |
| Listado filtrado | `backend/src/api/users.py`, `list_groups` (`GET /users/groups?include_inactive=`) |
| Endpoint de baja | `backend/src/api/users.py`, `deactivate_group` (`DELETE /users/groups/{id}`) |
| Botón + modal de confirmación | `frontend/src/pages/UsersPage.tsx` |
| Cliente API | `frontend/src/services/api.ts`, `deactivateGroup` |

**Ojo con el id de la migración**: se generó con `alembic revision` (hash `7a6fee614cfd`), **no**
un número secuencial (`021`) — ver la advertencia ya documentada en `specs/README.md` de Eleia
sobre el choque de numeración de migraciones entre Base/Sentinel/Eleia. Confirmar el head real de
Sentinel antes de portar y generar la migración de nuevo ahí con su propio hash si el árbol de
revisiones ya divergió (probable, dado que las tres líneas consumen el mismo contador por
separado).

**Gotcha de Alembic encontrado al probar** (no específico de esta migración, pero real): generar
una revisión con `alembic revision` y correr `alembic upgrade head` en la MISMA sesión de shell
puede levantar una versión cacheada en bytecode (`alembic/versions/__pycache__`) del archivo
ANTES de que se termine de escribir su contenido — el upgrade corre "en blanco" (los `pass` del
template) pero igual queda estampado como aplicado. Se detectó porque las columnas no aparecían
pese a que `alembic current` decía estar al head; se resolvió limpiando el `__pycache__` y
reseteando `alembic_version` a mano. Vale la pena que quien porte esta migración a Sentinel corra
`find . -path '*/alembic/versions/__pycache__*' -delete` antes de aplicarla si edita el archivo
después de generarlo, para no repetir el mismo susto.

## 2. Qué es portable a Sentinel tal cual

Todo el patrón es genérico — no depende de nada específico de Eleia (nombres de marca, región,
`latam_ar`, etc.). Portar:
1. La migración (con id propio generado en el árbol de Sentinel, no reusar el hash de acá).
2. Los cambios de `Group`, `GroupResponse`, `list_groups`, `deactivate_group`.
3. El botón y modal del frontend, si Sentinel usa el mismo `UsersPage.tsx` (confirmar que no
   divergió respecto al de Eleia antes de portar el diff tal cual).

## 3. Qué NO portar / verificar antes

- Si Sentinel ya tiene algún mecanismo propio de "equipo inactivo" (no se investigó del lado de
  Sentinel, solo se confirmó el estado de este repo) — revisar antes de aplicar para no duplicar.

## 4. Cómo verificar después de portar

```bash
cd backend
export POSTGRES_HOST=... POSTGRES_PORT=... POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=...
PYTHONPATH="$PWD/..:$PWD/../litellm:$PYTHONPATH" .venv/bin/python -m pytest -q \
  tests/integration/test_group_deactivation_054.py
cd ../frontend && npx tsc --noEmit
```

Verificado en Elea el 17-sep: migración corrida y confirmada contra Postgres real (columnas
presentes tras corregir el gotcha de caché), 2 tests de integración nuevos en verde, 1234 tests
unitarios + toda la suite de integración sin regresiones, TypeScript del frontend compila limpio.
