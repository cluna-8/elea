# Quickstart — validar la 018 de punta a punta

Prerrequisitos: stack Docker Compose local (`docker compose -p <tuequipo> up`), suite backend verde en main.

## 1 · SC-001: la purga borra lo vencido y solo lo vencido

> **Siembra — pendiente (T013).** El seed sintético `tests/seeds/seed_retention_dataset.py` **todavía no existe** (el directorio `backend/tests/seeds/` no está creado): entra con el PR de US1, junto a T012. Tiene que sembrar 200 días con blocked%, rejected%, config_change_*, tráfico normal, `human_reviews` con `response_text` viejo y las TRES formas de fila `license` que el Contrato 1 distingue — eslabón US5+ (`seq`+`prev_hash`+`event_type`), licencia pre-US5 (`event_type` sin `seq`) y spoof (`model='license'` con `guardian_events=[]`). Las dos primeras tienen que sobrevivir a la purga; la tercera tiene que morir. Hasta que exista, este §1 se ensaya sobre los datos que ya tenga la instalación y el simulacro devuelve los conteos reales de esa base.

> **Cómo se invoca la corrida.** `purger.py` **no tiene entrypoint de CLI** —no hay `__main__` ni `argparse`—, así que `python -m src.services.retention.purger --run-now` **no ejecuta nada**. El punto de entrada es `run_once(run_now=True)`, y `--run-now`/`run_now` dice CUÁNDO, no SI BORRA. El comando de abajo está verificado en vivo el 14-ago sobre el stack de compose. Si el PR de US1 le agrega el CLI, esta sección se actualiza con él.

> ⚠️ **Estos comandos necesitan `purger.py`, que llega en el PR de US1.** En el árbol del PR
> Foundational el módulo no existe todavía y la invocación falla con `ImportError`. La salida
> que se transcribe abajo se midió sobre la rama de trabajo con T008 aplicado, no sobre `main`.

```bash
# SIMULACRO — es el default (BASA_PURGE_DRY_RUN=true): cuenta lo que se iría y no borra nada.
# Es el paso que el DPO firma antes de la corrida real.
docker compose exec backend python -c \
  "from src.services.retention import purger; print(purger.run_once(run_now=True))"

# Recién después, la corrida REAL. El simulacro es el default, así que hay que pedir
# explícitamente que borre — y en una instalación de cliente, además, encender el maestro:
docker compose exec -e BASA_PURGE_DRY_RUN=false backend python -c \
  "from src.services.retention import purger; print(purger.run_once(run_now=True))"
```

Salida medida del simulacro sobre el compose (14-ago, base de desarrollo sin backlog), para que se sepa qué forma tiene la respuesta antes de leerla en la sede: `ResultadoCorrida(run_id=…, dry_run=True, clases=(…4 `ResultadoPurga`, una por clase, con `cutoff`, `rows_deleted`, `batches`, `window` y `result`…), filas_no_clasificadas=0, cutoff_no_clasificadas=…)`.

*(enmienda aprobada por el manager 13-ago — Contrato 4.)* `--run-now` dice CUÁNDO, no SI BORRA: son ejes ortogonales, y sin `BASA_PURGE_DRY_RUN=false` esta verificación cuenta filas y no borra ninguna. Con la corrida en simulacro, `result: ok` significa «terminé de contar», no «la clase quedó al día». Que el default sea el simulacro es deliberado: la primera corrida de una instalación arrastra el backlog de toda la vida de la caja y lo borrado no vuelve.

**Si una clase vuelve con `result: error` y `cutoff: None`, mirá primero su `retention_days`.** El purgador tiene un piso propio en el punto de destrucción —`PLAZO_MINIMO_DIAS = 1` (`purger.py:536`), aplicado en `_plazo_en_dias` (`:554`, chequeo en `:579`)— y un plazo `< 1` **aborta esa clase sin borrar ni contar nada**; las otras tres siguen purgando y el mensaje trae la clase y el valor. El endpoint de hoy acepta `0` y `-30` con **200** (sólo valida `config_audit ≥ 365`, `api/compliance.py:334`), así que ese error es el síntoma normal de una política mal tecleada, no un bug del purgador: se corrige el número en `retention_policies` y se vuelve a correr — la corrida es idempotente y no hay cursor que reponer. Rige igual en simulacro, a propósito: un ensayo bajo un plazo inválido devolvería un conteo con el cutoff parado en AHORA, o sea el número que el DPO firmaría sin que salga de ninguna frontera.

> ⚠ **Lo que el piso NO tapa**: `1` es un plazo válido. Con `retention_days=1` el cutoff cae en `ahora − 1 día` y la corrida real se lleva la clase entera salvo las últimas 24 h — el purgador no puede distinguir un `1` tecleado de un `1` querido. Los mínimos por clase son FR-007/T015 y **todavía no están**: hasta entonces, el simulacro es la única red antes del `DELETE`. Léelo antes de poner `BASA_PURGE_DRY_RUN=false`.

*(enmienda del manager 14-ago — Contrato 1 regla 6.)* El simulacro tiene que reportar además `filas_no_clasificadas`: las filas que el portón no pudo demostrar que fueran tráfico y que por eso nadie va a borrar. Es el residuo del fail-closed, y sale **antes** de la corrida real justamente para que el DPO firme sabiendo qué se queda, no sólo qué se va.

Verificación de la corrida real (SQL puro, sin conocer implementación): cero filas vencidas de clases purgables; cero no vencidas afectadas; **toda la evidencia de licencias intacta**; `response_text` NULL en reviews > 90 d con la fila de review presente; `verify_chain` y export true-up en verde.

*(enmienda del manager 14-ago, DEROGA la del 13-ago — Contrato 1 regla 2.)* «Evidencia de licencias» se comprueba por la **FORMA de `guardian_events`**, no por `model`: sobreviven las filas cuyo primer evento trae `seq`, `prev_hash` o `event_type` — o sea los eslabones de la 021 US5 en adelante **y** las licencias legítimas pre-US5 (`event_type`, sin `seq`, ventana 16→20-jul-2026), que la letra anterior mandaba a morir. En cambio, una fila que sólo *dice* `license` con `guardian_events` de tráfico (`[]`) **DEBE haber muerto con su clase**: es un spoof, y desde el 14-ago la columna `model` no le compra nada. SQL de verificación:

```sql
-- 1 · nada de lo que el portón protege por marca en el [0] se movió: este conteo tiene que dar
--     EXACTAMENTE lo mismo antes y después de la corrida real. Cubre los eslabones US5+, las
--     licencias pre-US5 y también el tráfico con blob forjado, que es el precio del
--     fail-closed y sobrevive a propósito (Contrato 1, regla 6).
SELECT count(*) FROM audit_logs
WHERE jsonb_typeof(guardian_events) = 'array'
  AND jsonb_typeof(guardian_events -> 0) = 'object'
  AND (jsonb_exists(guardian_events -> 0, 'seq')
       OR jsonb_exists(guardian_events -> 0, 'prev_hash')
       OR jsonb_exists(guardian_events -> 0, 'event_type'));

-- 2 · el spoof SÍ pasa el portón — el literal no le compra nada. Sobre la fila sembrada con
--     model='license' y guardian_events='[]' esto debe devolver `true`, y una vez vencido el
--     plazo de la clase que le toque por su compliance_status, la corrida real la borra.
--     (Es el predicado que emite `classifier._es_purgable()`, transcripto.)
SELECT id, guardian_events IS NOT NULL
       AND jsonb_typeof(guardian_events) = 'array'
       AND (guardian_events = '[]'::jsonb
            OR jsonb_typeof(guardian_events -> 0) = 'object'
               AND NOT jsonb_exists(guardian_events -> 0, 'seq')
               AND NOT jsonb_exists(guardian_events -> 0, 'prev_hash')
               AND NOT jsonb_exists(guardian_events -> 0, 'event_type')) AS purgable
FROM audit_logs WHERE model = 'license' AND guardian_events = '[]'::jsonb;
```

Se usa `jsonb_exists(x, 'k')` y no el operador `x ? 'k'` a propósito: es la MISMA función que emite el clasificador, y además el `?` viaja mal por los drivers que lo leen como placeholder de parámetro.

## 2 · SC-002: rastro reconstructible

`SELECT purge_log FROM retention_policies;` + filas `config_audit` de resumen — reconstruir qué se borró, cuándo y bajo qué política usando SOLO ese registro.

> **No verificable todavía (T010).** El purgador **no escribe** hoy ni el `purge_log` ni la fila resumen: el rastro de una corrida es el `ResultadoCorrida` que devuelve `run_once` más la línea de log. La forma de la entrada ya está fijada por los dataclasses `ResultadoPurga` y `ResultadoCorrida` de `purger.py`, así que T010 no la reinventa — la persiste. Este §2 se ejecuta con el PR de US1.

## 3 · SC-004: el mundo post-017

```bash
docker compose exec backend pytest tests/integration/test_identidad_batch_post017.py -v
```

La fixture (`tests/post017_harness.py`) dropea `tenant_isolation_bootstrap` y conecta con rol NOSUPERUSER; el emisor de la cadena y el reconciliador pasan bajo ese mundo. La mitad del purgador (T014, `test_purge_post017.py`) todavía NO está escrita — T008 ya está implementado y `run_once` corre, pero sus tests bajo esta fixture entran con el PR de US1.

## 4 · Tier: pisos y auditoría

> **No ejecutable todavía (T016 y T015 sin marcar), y la letra anterior mentía dos veces.** (1) El tier **no existe en el código**: `enforcement_tier_estricto` no aparece el 14-ago en ninguna línea de `backend/`, `frontend/` ni `litellm/` — sólo en la prosa de estas specs. Sin tier no hay pisos de tier que violar, y el único mínimo por clase VIVO en el handler es `config_audit < 365 → 422` (`api/compliance.py:334`), así que el `retention_days: 400` que la letra anterior prometía como 422 **devuelve 200 y persiste el cambio** (400 no es menor que 365). (2) El body documentado era un OBJETO y el endpoint recibe una **LISTA**: la firma es `update_retention(policies: List[RetentionPolicySchema], …)` (`api/compliance.py:328`). Un objeto suelto se cae con 422 **de schema**, antes de llegar a ningún piso — un 422 que parece «el piso funcionó» y no lo es. Esta sección se ejecuta de verdad con el PR de US2.

```bash
# Forma REAL del body: lista, aunque se mande una sola política. Rol requerido:
# admin o compliance_officer (`api/compliance.py:327`).
# Con el árbol de HOY esto responde 200 y deja config_audit en 400 — no 422.
curl -X PUT https://<host>/api/v1/compliance/retention \
  -H "Authorization: Bearer <token admin|compliance_officer>" \
  -H "Content-Type: application/json" \
  -d '[{"log_type":"config_audit","retention_days":400,
        "justification":"prueba del piso","updated_by":"quickstart"}]'

# El único piso que HOY contesta 422, y por eso el que sirve para ver que el camino existe:
curl -X PUT https://<host>/api/v1/compliance/retention \
  -H "Authorization: Bearer <token admin|compliance_officer>" \
  -H "Content-Type: application/json" \
  -d '[{"log_type":"config_audit","retention_days":364}]'      # → 422

# Cambiar tier → verificar fila de auditoría con valor anterior/nuevo   ← T016/T017: no hay tier que cambiar todavía
```

Dos avisos de operación que valen ya, con este endpoint tal como está:

- `justification` y `updated_by` se **pisan** con lo que traiga el body (`api/compliance.py:337-338`): un PUT que no los manda los deja en `null`. El texto del seed («No reducible por debajo de 365 días», `alembic/versions/004_compliance_tables.py:107`) es prosa editable por el operador, no un mínimo legible por código;
- las clases que no van en la lista no se tocan, y un `log_type` inexistente se ignora **en silencio** (`if not row: continue`, `:332-333`): el 200 no prueba que se haya actualizado nada. Verificá con `GET /api/v1/compliance/retention`.

Invariante: con cualquier tier, un request que dispara la capa de piso AI-Act sigue siendo evaluado (test de regresión de la 027).

## 5 · SC-003: el examen no se entera (con La ITV)

Bajo el perfil de carga del gate 125 (instrumento 035), disparar purga concurrente con backlog real → los 4 SLOs de oro se mantienen. Este paso lo corre La ITV con su harness; el criterio y el disparador ya están en su contrato de gates.
