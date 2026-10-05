# Orquestación con agentes — el mapa de Atlas

> **Para quién**: el coordinador (Atlas, la sesión de Claude Code en el workspace
> `<proyecto>-coordinator` de Orca) y quien le pida trabajo. Es el procedimiento que se sigue
> cuando el owner dice «resolvé este problema» o «avanzá esta spec».
>
> **Ámbito**: interno del equipo. Herramienta: [`orquestar.sh`](orquestar.sh).
> Roles: [`roles.json`](roles.json). Config del proyecto: [`config.json`](config.json).
> Plantillas de plan: [`plantillas/`](plantillas/). Instalado por el kit `atlas-coordinador`.

## En 30 segundos

```
pedido del owner
   │  0 situarse (git fetch, estado de la rama principal, PRs abiertos)
   │  1 clasificar: fix · spec existente · spec nueva · spike
   │  2 escribir el PLAN (JSON): tareas, rol de cada una, dependencias, compuerta
   │  3 orquestar.sh plan        → Run + tareas + compuertas en Orca
   │  4 orquestar.sh despachar   → un worker por tarea lista, con el perfil de su rol
   │  5 esperar worker_done · responder preguntas · validar cada entrega
   │  6 orquestar.sh verificar            → nada fuera de rutas; base protegida sin tocar (si hay)
   │  7 COMPUERTA: el owner decide · orquestar.sh compuerta / cerrar
   │  8 integrar → PR → CI verde → merge (el owner) → borrar worktrees y ramas
   ▼
reporte al owner: por tarea, resultado, evidencia y lo que quedó abierto
```

**Atlas no escribe código de producto.** Planifica, despacha, valida, integra ramas y abre
PRs. El código lo escriben los workers, cada uno en su worktree.

## 1. Clasificar el pedido

El criterio es el del proyecto (`AGENTS.md`/`CLAUDE.md`); por defecto, SDD cuando amerita: spec solo si obliga a decidir algo. La clasificación decide la plantilla:

| El pedido es… | Señal | Plantilla | Antes de despachar |
|---|---|---|---|
| **Fix** | Causa clara, decisión ya tomada en una spec vigente | `fix.json` | Ubicar la causa con `archivo:línea` |
| **Implementar una spec** | Hay `plan.md` y `tasks.md` | `implementacion.json` | Partir `tasks.md` en tramos de ≤ ~15 tareas, uno por plan |
| **Spec nueva o enmienda** | Hay que decidir algo que ninguna spec decidió | `implementacion.json` con rol `redactor-spec` | Confirmar con el owner que amerita spec (y la numeración) |
| **Spike** | Hay que averiguar si algo es viable antes de decidir | `spike.json` | Saber en qué documento quedan las conclusiones |

Si el pedido no entra en ninguna, se pregunta al owner antes de planificar.

## 2. Roles

El detalle (agente, modelo, esfuerzo, reglas que se le inyectan) vive en `roles.json`; esta
tabla es el criterio para elegir.

| Rol | Agente · modelo | Cuándo | Cuándo NO |
|---|---|---|---|
| `atlas` | — (el coordinador) | Integrar, abrir PR, cerrar una compuerta | Nunca se despacha |
| `senior` | Claude Code · Sonnet 5.5, esfuerzo alto | Lógica central, seguridad, contratos, migraciones, refactors | Trabajo mecánico (desperdicia cuota) |
| `junior` | OpenCode · modelo de su config (GLM) | Scaffolding, mocks, fixtures, cambios mecánicos con rutas acotadas | Spikes, seguridad, cualquier decisión |
| `spike` | Claude Code · Sonnet 5.5, esfuerzo alto | Investigar viabilidad con evidencia `archivo:línea` | Escribir código de producto |
| `redactor-spec` | Claude Code · Opus 5.5, esfuerzo alto | Spec, plan y tasks con los skills `speckit-*` | Decidir sin el owner: las preguntas vuelven por `ask` |
| `qa` | Antigravity · modelo de su config | Primer nivel: correr tests y linters, revisar el diff contra la aceptación | Editar código |
| `qa-critico` | Claude Code · Sonnet 5.5, esfuerzo alto | Segundo nivel cuando el cambio toca seguridad, datos sensibles, permisos o el dominio crítico | Cambios sin superficie crítica |
| `infra` | Claude Code · Opus 5.5 | **En pausa** hasta definir secretos y despliegue del proyecto | — el script se niega a despacharlo |

Regla práctica: **ante la duda entre `junior` y `senior`, `senior`**. Un junior que
improvisa cuesta más que la cuota que ahorra. Y un spike nunca va a `junior`: su valor está
en distinguir lo verificado de lo supuesto.

## 3. Escribir el plan

Un plan es un JSON. Se parte de una plantilla, se reemplaza todo `{{...}}` (el script rechaza
una plantilla sin completar; `<...>` queda libre para texto real, como `<think>`) y se guarda **junto a la spec** si la hay
(`specs/NNN-slug/orquestacion-<tramo>.json`) o en el scratchpad de la sesión si no.

```jsonc
{
  "objetivo": "una línea: qué cierra este Run",
  "rama_base": "origin/main",          // de dónde nacen los worktrees nuevos
  "tareas": [
    {
      "clave": "dev",                  // nombre corto, único en el plan
      "titulo": "...",
      "rol": "senior",                 // uno de roles.json
      "depende_de": [],                // claves que tienen que estar completed antes
      "worktree": "nuevo",             // nuevo | de:<clave> (reusa el de otra tarea; exige depender de ella)
      "rama": "NNN-slug-tramo",        // obligatoria con worktree nuevo
      "alcance": "...",                // Target: archivos, componente, tareas T de la spec
      "cambio": "...",                 // Change: el resultado observable
      "restricciones": "...",          // se SUMAN a las reglas comunes y a las del rol
      "propiedad": "...",              // Ownership: qué puede editar
      "rutas": ["src/modulo/*"],       // opcional: globs; tocar otra ruta hace fallar 'verificar'
      "aceptacion": "...",             // Acceptance: comando y evidencia que prueban que terminó
      "repo": "otro-repo",             // opcional: nombre del repo en Orca (orca-ide repo list) si el worktree va en OTRO repo
      "rama_base": "origin/main",      // opcional: pisa la del plan (útil con repo)
      "compuerta": {                   // opcional; la PRIMERA opción es la que aprueba
        "pregunta": "...", "opciones": ["aprobado", "requiere_cambios", "descartar"]
      }
    }
  ]
}
```

**Multi-repo.** Una feature que toca varios repos (p. ej. el producto y su instalador) va en
**un solo plan y un solo Run**, coordinado desde el repo que tiene la spec. Cada tarea que
trabaja en otro repo lleva `"repo"` (y `"rama_base"` si su rama principal no es la del plan):
su worktree nace en ese repo y `verificar` lo revisa contra esa base (la base protegida del
proyecto no aplica a otros repos). Las reglas del otro repo van en `restricciones`: el worker
recibe las `reglas_comunes` de este repo. Cada repo integra y abre su propio PR; la compuerta
de integración puede cubrir los dos.

Lo que hace bueno a un plan:

- **Cada spec de tarea es autocontenido.** El worker no vio esta conversación. Las reglas
  del repo (las de `reglas_comunes`, adaptadas al proyecto en el bootstrap: TDD, sin push,
  DoD...) las inyecta el script desde `roles.json`; lo propio de la tarea va en `restricciones`.
- **Dependencias solo donde hay orden real.** Las tareas independientes van en paralelo
  (dos spikes que escriben secciones distintas, por ejemplo). Cadenas de más de 3–4 pasos son una señal de que el plan hay que partirlo.
- **Una sola tarea escribe en cada archivo a la vez.** Si dos tareas paralelas tienen que
  escribir el mismo documento, cada una escribe una sección distinta y Atlas resuelve el
  conflicto al integrar.
- **Toda integración a `main` pasa por una tarea `atlas` con compuerta.** El script avisa si
  el plan no tiene ninguna.

## 4. Comandos

```bash
S=.atlas/orquestar.sh
$S plan specs/NNN/orquestacion-x.json --dry-run   # valida y muestra los specs que recibirá cada worker
$S plan specs/NNN/orquestacion-x.json             # crea el Run, las tareas y las compuertas → imprime la ruta del estado
$S estado <estado>                                # tabla: tarea, compuerta, worker, worktree
$S despachar <estado> dev                         # worker-start con el perfil del rol
$S verificar <estado> qa                          # verifica el worktree de la tarea (o el de su de:<clave>)
$S compuerta <estado> integrar aprobado           # SOLO con la respuesta literal del owner
$S cerrar <estado> integrar                       # cierra un paso de Atlas (exige compuerta aprobada y dependencias cerradas)
```

`plan` crea un Run nuevo y lo liga al terminal del coordinador; `--run <id>` reusa uno. El
archivo de estado mapea cada clave a su tarea, compuerta, despacho y worktree; es local y vive
fuera del repo (`~/.local/state/atlas-orquestar/<repo>/<carpeta>--<plan>.estado.json`, o
`$ATLAS_ORQ_ESTADO`), así que nunca se commitea por accidente.

Mientras corren los workers, el bucle es el de Orca (`orca-ide skills get orchestration`):
`orca-ide orchestration check --wait --types worker_done,escalation,question`, responder
cada pregunta con `reply`, y por cada `worker_done` validar (§6) antes de reconocerlo.

## 5. Lo que Orca no hace cumplir (verificado contra Orca el 2-oct-2026)

El script existe sobre todo por esto:

1. **Una compuerta no bloquea de verdad.** `gate-create` pone la tarea en `blocked`, pero un
   `task-update --status completed` la cierra igual con la compuerta pendiente, y las
   dependientes pasan a `ready`. → `despachar` y `cerrar` se niegan si hay compuerta pendiente.
2. **Resolver una compuerta se salta las dependencias.** Al resolverla, Orca pone la tarea en
   `ready` aunque sus dependencias sigan abiertas (y si ya estaba `completed`, la vuelve a
   `ready`). → el script comprueba `depende_de` contra `completed` por su cuenta, sin
   confiar en `ready`.
3. **`worker-release` no cierra el terminal del worker** si hay commits sin pushear: lo deja
   `retained` por `user_takeover`. Es correcto (preserva el trabajo); los worktrees se
   borran después de integrar, con `orca-ide worktree rm`, que también borra la rama local.
4. **Solo se modifica el Run ligado al terminal.** Cualquier mutación sobre otro Run falla con
   `consumer_fenced`. La bandeja del coordinador va con el Run ligado, así que el script no lo
   cambia solo: `despachar`, `compuerta` y `cerrar` se niegan y dicen qué `run-use` correr.
   Un Run a la vez por coordinador.
6. **Un agente que tarda en arrancar puede dar `terminal_handle_stale`** en `agent_readiness` aunque esté vivo
   (pasó con OpenCode). Antes de relanzar: `orca-ide terminal show --terminal <handle>` y mirar el `preview`. Si
   el agente está esperando, reintentar sobre esa terminal: `worker-start --task <id> --retry-of <dispatch>
   --terminal <handle> --worktree path:<ruta>`. Nunca lanzar un segundo agente en un worktree nuevo.
7. **En Linux, `orca` a secas es el lector de pantalla de GNOME.** El script resuelve
   `ORCA_CLI_COMMAND` → `orca-ide`; nunca cae a `orca`.

Quien decide una compuerta es el **owner**. Atlas le hace la pregunta, y solo con su
respuesta corre `compuerta`. Que Atlas resuelva su propia compuerta la vacía de sentido.

## 6. Validar un `worker_done`

Antes de reconocer la entrega (`check --ack`) y liberar el worker:

1. ¿El `worker_done` es del despacho esperado (Task y Dispatch del estado)? ¿`--outcome`
   explícito?
2. `orquestar.sh verificar <estado> <clave>`: ¿nada fuera de `rutas`? Si el proyecto declara
   base protegida: ¿sin tocar, o con su registro en el mismo diff?
3. ¿El commit existe y contiene lo que el resumen dice? (`git log`, `git show --stat`).
4. ¿La evidencia de la aceptación está (salida de tests, archivo:línea)? Lo que el worker
   marcó «no verificado» se reporta como tal, no se sube de estado.
5. Si algo falla: no se libera, se le manda la corrección por `orchestration send` o se
   replanifica. Nunca se relanza un worker sin prueba de que el anterior terminó.

## 7. Integrar y limpiar

- Los workers commitean **local**, sin push ni PR. Atlas integra las ramas en un worktree
  temporal propio (nunca en el del owner ni en el de otro agente), resuelve conflictos,
  pushea y abre el PR.
- Antes de pedir merge: el gate del proyecto en verde (sus tests y linters, ver `AGENTS.md`), y CI verde
  en el PR.
- El merge a la rama principal lo decide el owner.
- Después del merge: `orca-ide worktree rm --worktree path:<ruta>` por cada worktree de
  worker, borrar la rama remota si no se borró sola, y reportar.

## 8. Límites conocidos

- **OpenCode funciona como worker** (verificado el 2-oct-2026, GLM-5.2): su primer despacho falló en
  `agent_readiness` con `terminal_handle_stale` aunque el agente SÍ arrancó; se recupera reintentando sobre esa
  misma terminal viva (ver §5, trampa 6). La tarea mecánica se cumplió al pie de la letra.
- **Antigravity funciona como worker** (verificado el 2-oct-2026, prueba de humo): mismo tropiezo de arranque
  que OpenCode en el primer intento; se recupera igual.
- `verificar` detecta «archivo de la base protegida» por existencia en `base_protegida.ref`: un
  archivo de la base renombrado en el proyecto no se detecta.
- El rol `infra` está en pausa: el script se niega a despacharlo hasta que se defina el manejo
  de secretos.

### Propios de `elea` (bootstrap del 5-oct-2026)

- **Hook de secretos en worktrees.** `.claude/settings.local.json` del checkout principal (no
  versionado; Claude Code lo aplica también a los worktrees) corre `secret-scanner.py` antes
  de cada Bash. Apuntaba a `$CLAUDE_PROJECT_DIR`, que en un worktree no tiene el script, y
  bloqueaba TODO Bash del worker. Se fijó a la ruta absoluta del checkout principal. Si un
  worker no puede correr Bash, mirar eso primero.
- **Multi-repo.** El instalador (`elea-installer`, registrado en Orca con ese nombre) no tiene
  Spec-Kit ni `.atlas/`: sus cambios salen de las specs de este repo y se despachan desde acá
  con `"repo": "elea-installer"`. Su gate no es el de este repo: `bash -n install.sh`,
  `docker compose config -q` con su `.env.example`, y la prueba de instalación desde cero
  cuando la tarea lo pida.
- **Sentinel.** Lo que es base Guardian se porta a `cluna-8/sentinel` (repo `SENTINEL` en
  Orca) por handoff: la spec espejo la lleva su propio coordinador; acá solo se deja el
  `HANDOFF-elea-a-sentinel.md` y se separan los commits de base de los del Hub.
- **Gate pesado.** `make -C deploy check` y la suite de backend en Docker son lentos y comparten
  puertos/volúmenes: no correrlos en paralelo desde dos workers; QA los corre una vez sobre la
  rama integrada.
