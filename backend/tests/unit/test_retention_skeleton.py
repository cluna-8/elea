"""T001 (spec 018): el esqueleto de retención IMPORTA y respeta las formas selladas.

Qué muerde este test, y por qué vale la pena antes de que haya una línea de lógica:

1. **Las firmas del Contrato 1** (`contracts/clasificador-identidad-tier.md`). El clasificador
   tiene DOS consumidores que deben contar lo mismo —el purgador y la vitrina del officer—,
   así que su superficie es un contrato entre tareas, no un detalle de implementación. Si
   T003 implementa `clase_de(row)` o le agrega un parámetro para «incluir también license»,
   esto se pone rojo acá y no en el refactor de la vitrina.
2. **Los nombres y defaults de las 7 perillas de FR-001** (las 6 de la tabla del plan más
   `BASA_PURGE_DRY_RUN`, que entró el 13-ago con la red de H7). Son superficie publicada:
   viajan al `.env.example`, de ahí a la referencia de configuración del sitio
   (`docs/gen_config_reference.py`) y de ahí al operador. Un rename silencioso en el código
   deja la doc prometiendo una perilla que ya no existe; el gate de drift lo cazaría en CI,
   pero este test lo caza antes y dice exactamente cuál.
3. **Los campos del rastro de corrida** (data-model.md). SC-002 pide que un auditor
   reconstruya qué se borró SOLO con el registro: si un campo desaparece, la evidencia deja
   de alcanzar.

Lo que este test NO hace, a propósito: no verifica que los cuerpos levanten
`NotImplementedError`. Eso ataría el test al estado «sin implementar» y lo volvería un
estorbo el día que T003/T008/T011 escriban la lógica — un test que hay que borrar para
avanzar es un test que se borra sin leer.
"""
import dataclasses
import inspect

from src.services import retention_scheduler
from src.services.retention import classifier, purger


# ── Contrato 1 · clasificador ────────────────────────────────────────────────────────
def test_clasificador_expone_las_tres_firmas_del_contrato():
    assert inspect.signature(classifier.clases).parameters == {}

    # El parámetro se llama `clase` y es el ÚNICO: la regla 2 del contrato es que no exista
    # forma de pedir las filas de la hash-chain de licencias, ni siquiera un flag opcional.
    predicado = inspect.signature(classifier.predicado)
    assert list(predicado.parameters) == ["clase"]

    clase_de = inspect.signature(classifier.clase_de)
    assert list(clase_de.parameters) == ["fila"]


# ── Perillas de FR-001 (las 6 de la tabla sellada del plan + `BASA_PURGE_DRY_RUN`) ───
def test_nombres_de_env_de_purga_son_los_publicados():
    assert purger.ENV_WINDOW == "BASA_PURGE_WINDOW"
    assert purger.ENV_WINDOW_TZ == "BASA_PURGE_WINDOW_TZ"
    assert purger.ENV_BATCH_SIZE == "BASA_PURGE_BATCH_SIZE"
    assert purger.ENV_BATCH_PAUSE_MS == "BASA_PURGE_BATCH_PAUSE_MS"
    assert purger.ENV_DRY_RUN == "BASA_PURGE_DRY_RUN"
    assert retention_scheduler.ENV_ENABLED == "BASA_PURGE_ENABLED"
    assert retention_scheduler.ENV_INTERVAL_SECONDS == "BASA_PURGE_INTERVAL_SECONDS"


def test_defaults_de_purga_son_los_del_plan():
    # Estos valores son los que la doc del producto promete. Cambiar uno es cambiar el
    # contrato publicado: se cambia acá, en `.env.example` y en los dos composes, o no se
    # cambia. (La ventana en hora local y de madrugada es lo que sostiene SC-003: la purga
    # no le cuesta el examen de carga a nadie.)
    assert purger.DEFAULT_WINDOW == "02:00-05:00"
    assert purger.DEFAULT_WINDOW_TZ == "Europe/Madrid"
    assert purger.DEFAULT_BATCH_SIZE == 5000
    assert purger.DEFAULT_BATCH_PAUSE_MS == 200
    assert retention_scheduler.DEFAULT_INTERVAL_SECONDS == 3600.0

    # Las dos mitades de la red de H7, ambas en el código y no sólo en el `.env` de cada
    # sede: el interruptor maestro apagado y el simulacro puesto. Un job que hace DELETE
    # retroactivo no se enciende con un pull de imagen, y la primera corrida CUENTA lo que
    # se llevaría antes de llevárselo. Estos defaults son los que mandan en todo arranque
    # que no pase por los composes —`uvicorn` a mano, un manifiesto k8s/Zarf sin la
    # variable—; si alguno se diera vuelta acá, el seguro pasaría a depender de que nadie
    # se olvide una línea de env. Se cambian en los tres lugares (código, `.env.example`,
    # composes) o no se cambian.
    assert retention_scheduler.DEFAULT_ENABLED is False
    assert purger.DEFAULT_DRY_RUN is True


# ── Rastro de corrida (data-model.md · FR-005/SC-002) ────────────────────────────────
def test_resultado_de_purga_lleva_los_campos_que_el_auditor_necesita():
    campos = {f.name for f in dataclasses.fields(purger.ResultadoPurga)}
    assert {"run_id", "started_at", "finished_at", "cutoff",
            "rows_deleted", "batches", "window", "result", "dry_run"} <= campos

    # `dry_run` es el campo que le da sentido a `rows_deleted`: en simulacro ese número es lo
    # que se HABRÍA borrado y la tabla no cambió. Sin él, simulacro y corrida real dejan un
    # rastro idéntico y el registro afirma borrados que nunca pasaron — el papel con el que el
    # DPO responde una reclamación tiene que decir cuál de las dos cosas fue.
    # Y va sin default: obligatorio en el constructor es lo que impide que una rama nueva se
    # olvide de setearlo y quede clasificada en el modo equivocado en silencio.
    dry_run = next(f for f in dataclasses.fields(purger.ResultadoPurga) if f.name == "dry_run")
    assert dry_run.default is dataclasses.MISSING
    assert dry_run.default_factory is dataclasses.MISSING

    # Metadata-only (Security Constraint 1 + 6): el rastro de una purga no puede
    # reintroducir lo que la purga vino a borrar. Ningún campo de contenido, ni de sujeto.
    prohibidos = {"prompt", "prompt_content", "response_text", "content",
                  "user_email", "subject_identifier", "masked_entities"}
    assert not (campos & prohibidos)


def test_resultados_posibles_de_una_corrida():
    # `partial` existe porque la ventana puede cerrarse con backlog pendiente: sin ese
    # estado, una corrida cortada se vería igual que una que terminó y el auditor leería
    # «al día» sobre una clase que no lo está.
    assert (purger.RESULTADO_OK, purger.RESULTADO_PARCIAL, purger.RESULTADO_ERROR) == \
        ("ok", "partial", "error")


# ── Scheduler: mismo vocabulario que el único scheduler que ya existe ────────────────
def test_scheduler_de_purga_habla_el_idioma_de_reconcile():
    # El producto ya tiene un scheduler (`licensing/reconcile.py`, spec 021) y un operador
    # no debería aprender dos vocabularios de arranque/apagado para la misma clase de cosa.
    from src.licensing import reconcile

    for nombre in ("start_scheduler", "stop_scheduler", "scheduler_running"):
        assert callable(getattr(retention_scheduler, nombre)), nombre
        assert list(inspect.signature(getattr(retention_scheduler, nombre)).parameters) == \
            list(inspect.signature(getattr(reconcile, nombre)).parameters), nombre


def test_scheduler_de_purga_ya_tiene_cuerpo():
    # T011 le puso cuerpo al trío: dejó de ser esqueleto. La suite corre con
    # `BASA_PURGE_ENABLED=false` (conftest), así que sin nadie que lo arranque el estado
    # base es «no hay thread» — un bool, no un `NotImplementedError`. El comportamiento fino
    # (arranque/apagado, fail-soft, doble compuerta) lo cubre `test_retention_scheduler.py`;
    # acá sólo se sella que las formas quedaron IMPLEMENTADAS y no como stub.
    assert retention_scheduler.scheduler_running() is False
