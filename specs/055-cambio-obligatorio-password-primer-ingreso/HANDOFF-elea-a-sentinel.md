# Handoff — spec 055 (Elea) para llevar a Sentinel

**Fecha**: 21-sep-2026. **Origen**: `github.com/cluna-8/elea`, rama `main`. **Destino**:
`cluna-8/sentinel` (producto base, "Guardian").

Es código de base, no de la localización argentina: que la contraseña que fija un admin en un
alta o un reseteo quede vigente indefinidamente, sin forzar su cambio, es un hueco del producto
genérico — el mismo criterio ya aplicado a otros hallazgos de esta línea (paracaídas `latam_ar`,
atribución de gasto de la spec 053, baja de equipos de la spec 054). Nada de esto depende de
nombres de marca, región, ni de `latam_ar`.

## 1. Qué se hizo

`User` no tenía ningún campo para distinguir "contraseña que definió el propio dueño" de
"contraseña que le fijó un admin (alta o reseteo) y todavía no validó". Se agregó
`must_change_password` (bool, default `false`) y la lógica que lo prende/apaga, más el modal
obligatorio en las dos superficies de acceso de usuarios.

| Pieza | Dónde | ¿Genérica (base) o de Eleia? |
|---|---|---|
| Migración (agrega `must_change_password` a `users`) | `backend/alembic/versions/199fe429762a_users_must_change_password.py` | Base |
| Modelo | `backend/src/models/user.py`, clase `User` | Base |
| Se prende en alta y en reseteo admin | `backend/src/api/users.py`: `_insertar_usuario` (dentro de `create_user`), `reset_user_password` | Base |
| Se apaga al cambiar la propia contraseña | `backend/src/api/users.py`, `change_own_password` | Base |
| Expuesto en el login | `backend/src/api/users.py`: `_LoginSnapshot`, `_instantanea`, respuesta de `POST /users/login` | Base |
| Modal obligatorio — panel Guardian (admin/compliance/lectura) | `frontend/src/App.tsx`, `frontend/src/pages/UserPortal.tsx`, `frontend/src/components/CambiarMiPasswordModal.tsx`, `frontend/src/services/auth.ts` | Base — es el mismo `frontend/` que ya comparten las dos líneas |
| Modal obligatorio + botón voluntario — **Eleia Hub** | `client/server.js` (`POST /api/auth/change-password`), `client/public/index.html` | **Específico de esta línea — ver §3** |

**Ojo con el id de la migración**: generado con `alembic revision` (hash `199fe429762a`), **no**
un número secuencial — mismo criterio que la 054, por el choque de numeración de migraciones
entre Base/Sentinel/Eleia ya documentado en `specs/README.md`. Confirmar el head real de Sentinel
antes de portar y generar la revisión de nuevo ahí con su propio hash si el árbol ya divergió
(`down_revision` de esta migración es `7a6fee614cfd`, el head de Eleia al momento de escribirla —
casi seguro no coincide con el head de Sentinel).

## 2. Qué es portable a Sentinel tal cual

Todo lo marcado "Base" en la tabla de arriba — no depende de nada específico de Eleia:
1. La migración (con id propio generado en el árbol de Sentinel).
2. Los cambios de `User`, `_LoginSnapshot`/`_instantanea`, `create_user`, `reset_user_password`,
   `change_own_password`, y la respuesta de `POST /users/login` — es aditivo puro, no rompe
   contrato existente.
3. `App.tsx`/`UserPortal.tsx`/`CambiarMiPasswordModal.tsx`/`auth.ts` de `frontend/`, si Sentinel
   usa el mismo panel Guardian sin haber divergido demasiado (confirmar el diff antes de portarlo
   tal cual — mismo caveat que la 054 con `UsersPage.tsx`).

## 3. Qué NO portar sin confirmar antes

**El Hub (`client/`) es la pieza dudosa.** En Elea, los usuarios reales (rol `client`) **no**
entran al panel Guardian — entran exclusivamente por Eleia Hub, un servicio Node/Express +
HTML/JS vanilla completamente aparte (`client/server.js` + `client/public/index.html`), que
reusa el mismo backend/JWT pero tiene su propia UI, sin nada compartido con `frontend/`. Sin la
implementación específica ahí (§1, última fila), el flag llega en la respuesta de login pero
nadie lo lee — la protección queda sin efecto práctico para el usuario real (así se encontró en
esta misma spec, ver `spec.md` §Diagnóstico punto 3).

Antes de portar esa parte a Sentinel, confirmar:
- Si Sentinel tiene un equivalente al Hub (mismo patrón: backend compartido + frontend propio
  para usuarios finales) o si en esa línea los usuarios reales sí entran por el panel Guardian
  directamente — en ese caso la ronda 1 (solo `frontend/`) ya alcanzaría ahí y la ronda 2 de esta
  spec no aplicaría tal cual.
- Si existe un Hub equivalente pero con una base de código distinta a `client/` de este repo, el
  patrón a portar es el **enfoque** (endpoint proxy de cambio de contraseña + modal obligatorio
  no descartable en el primer login), no el diff línea por línea.

## 4. Cómo verificar después de portar

```bash
cd backend
export POSTGRES_HOST=... POSTGRES_PORT=... POSTGRES_USER=... POSTGRES_PASSWORD=... POSTGRES_DB=...
PYTHONPATH="$PWD/..:$PWD/../litellm:$PYTHONPATH" .venv/bin/python -m pytest -q
cd ../frontend && npx tsc --noEmit
node -c client/server.js   # si el Hub existe en esa línea con la misma base
```

Manual, imprescindible (esta spec se rompió en la práctica por no probarla en la superficie real
de acceso — no alcanza con typecheck/tests):
1. Usuario preexistente hace login → sin modal, en las dos superficies de acceso.
2. Alta o reseteo de un usuario de prueba → login → modal obligatorio, sin cerrar, en la
   superficie por la que entra el usuario real (confirmar primero cuál es esa superficie en
   Sentinel antes de asumir que es el panel Guardian).
3. Completar el cambio → refresh → no se repite.

Verificado en Elea el 21-sep: contra un stack local reconstruido desde cero (17 usuarios
preexistentes intactos tras la migración) y **en vivo contra el servidor real de producción del
cliente** — alta desde Guardian, login en el Hub, modal obligatorio con el branding real de
Eleia, cambio completado, sin volver a pedirse. Usuarios de verificación dados de baja después
(el producto no tiene borrado físico de usuarios, solo baja lógica — `DELETE /users/{id}`).
