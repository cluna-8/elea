"""El piso del plazo en el PURGADOR: la segunda red (spec 018, dictamen del manager 14-ago).

## Qué decisión defiende este archivo

«El endpoint valida para dar buen error, el purgador valida para no destruir» (dictamen del
manager, 14-ago, textual). La validación de rangos del `PUT /api/v1/compliance/retention` es
FR-007 (T015, US2) y llega después; lo que se mide acá es la red del punto de destrucción, que
va a seguir existiendo cuando aquélla entre.

Por qué hace falta, MEDIDO el 14-ago contra la app real y no heredado de un resumen: el
`PUT /api/v1/compliance/retention` contesta **HTTP 200** a `retention_days: 0` y a `-30` y los
persiste, en toda clase que no sea `config_audit` —`RetentionPolicySchema.retention_days` es un
`int` pelado sin `ge=` (`api/compliance.py:107`) y la única validación de rango es
`config_audit >= 365` (`api/compliance.py:334`, que sí contesta 422)—. Y sin el piso del
purgador, una corrida con esa política borra una fila escrita ESE MISMO DÍA: es lo que muestra
el primer mutante de la tabla de abajo, que muere justo en el assert de la fila de hoy. Por eso
el dataset de este archivo la tiene: no es un borde inventado, es el daño exacto.

## Las cuatro cosas que se miden, y por qué las cuatro

1. **no borra** — plazo `0` y plazo `-30` no se llevan ni la fila de 800 días ni la de hoy. Es lo
   único irreversible que hay en juego, así que es el primer assert de cada test;
2. **dice por qué** — la corrida deja `PlazoDeRetencionInvalido` con la CLASE y el VALOR adentro.
   Una corrida que se para en silencio es retención apagada sin que nadie se entere, que es el
   modo de falla que la 018 vino a cerrar;
3. **aborta la clase, no la corrida** — con `usage_metadata` en 0, las otras tres siguen
   purgando. La decisión y su porqué están en §«El piso del plazo» de `purger.py`: un número mal
   tecleado en una clase no puede apagar la retención del producto entero en un job que corre de
   madrugada;
4. **una configuración válida sigue funcionando igual que antes** — incluido el borde exacto
   (`PLAZO_MINIMO_DIAS`, hoy 1 día), que es lo que impide que la red se convierta en un piso
   inventado más alto que el de la fuente.

El simulacro está medido en los mismos términos y por su propio motivo: un ensayo que reporta
«se van N filas» con un plazo inválido le hace firmar al DPO un número que no sale de ninguna
frontera — y el ensayo es exactamente lo que existe para que firme antes de que pase.

## El piso es `> 0` y no un mínimo por clase, y eso también se mide acá

Verificado en la fuente el 14-ago: no hay mínimos por clase legibles por código. `classifier.py`
no define ninguno; el seed 004 crea `retention_policies` sin CHECK de rango (medido contra el
Postgres del compose: sólo PK, `UNIQUE (log_type)` y la FK de tenant) y su único «mínimo» es
prosa dentro de un `justification` que cualquier PUT pisa —medido: un PUT sin ese campo lo deja
en `null`— (`004_compliance_tables.py:107` / `api/compliance.py:337`); y la tabla de mínimos por
clase y por tier vive en el plan (`research.md` §D7, «ajustables en tasks») y cuelga de
`enforcement_tier_estricto`, que no aparece en ninguna línea de `backend/` ni de `frontend/`. El
único mínimo por clase en vigor es el `config_audit >= 365` del endpoint, que es de FR-007.

Por eso `test_el_plazo_del_borde_purga_normalmente` fija el borde: si alguien sube el piso del
purgador a un número por clase, tiene que hacerlo con la fuente en la mano y este test rojo
delante, no de memoria.

## Que este archivo muerde está MEDIDO (corrida de mutación del 14-ago)

Cada mutante se aplicó sobre `purger.py`, se corrieron los 37 tests de los cuatro archivos que
tocan este código —los 8 de acá, los 14 de `test_retention_purga_residuo.py`, los 9 de
`tests/unit/test_retention_purga_ventana.py` y los 6 de `tests/unit/test_retention_skeleton.py`—
y se restauró. La columna es cuántos se ponen ROJOS:

| mutación sobre `purger.py`                                                  | rojos |
|-----------------------------------------------------------------------------|-------|
| sin piso: `_plazo_en_dias` devuelve el valor tal cual                        |   6   |
| un plazo inválido aborta la CORRIDA entera (`run_once` re-levanta)           |   6   |
| el piso deja pasar el cero (`dias < 0` en vez de `< PLAZO_MINIMO_DIAS`)      |   5   |
| el piso no corre en simulacro (chequea sólo si `not _dry_run_de_env()`)      |   1   |
| `PLAZO_MINIMO_DIAS = 2` (piso inventado por encima de la fuente)             |   1   |
| `cutoff_de_residuo` sin piso (cuenta el residuo con el umbral en AHORA)      |   1   |

Cero mutantes sobrevivientes. Los tres de una sola muerte son los que miden decisiones que sólo
tienen un lugar donde verse, y por eso están escritos: sin `test_el_simulacro_no_reporta_un_
numero_bajo_un_plazo_invalido`, el piso podría quedar en la rama que borra y nadie se enteraría
—el simulacro es el modo por DEFAULT del producto—; sin
`test_el_plazo_del_borde_purga_normalmente`, la red podría subirse a un mínimo inventado; y sin
`test_sin_ninguna_politica_valida_el_residuo_no_se_cuenta`, el contador seguiría firmando un
número bajo un umbral parado en AHORA.
"""
import logging
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import null

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "sentinel_test_retencion_piso_plazo"

# Plazos del seed 004 (`alembic/versions/004_compliance_tables.py:102-108`). A mano y NO
# importados, con el mismo criterio que el archivo del residuo: si alguien cambia el seed, esto
# se pone rojo y lo explica, en vez de seguirlo en silencio.
PLAZO_USO = 365          # usage_metadata
PLAZO_MAS_LARGO = 730    # config_audit

# Edades del dataset. `HOY` es la protagonista: es la fila que el gate adversarial vio morir con
# la política en 0, o sea el daño exacto que este piso existe para impedir.
VIEJA = PLAZO_MAS_LARGO + 70   # vencida para las cuatro clases
HOY = 0                        # escrita en esta corrida: no está vencida para NADIE

# (marca, model, compliance_status, guardian_events, edad_dias). Una fila por clase con filas en
# `audit_logs`, en las mismas formas que usa el archivo del residuo — `prompt_content` no aparece
# porque su predicado es vacío por diseño (`classifier.CLASES_SIN_FILAS_EN_AUDIT_LOGS`).
USO_VIEJA = ("uso_vieja", "ollama-qwen3-4b", "passed", [], VIEJA)
USO_HOY = ("uso_hoy", "ollama-qwen3-4b", "passed", [], HOY)
SEGURIDAD_VIEJA = ("seguridad_vieja", "claude-3-5-sonnet-20241022", "blocked_secret", [], VIEJA)
CONFIG_VIEJA = ("config_vieja", "gpt-4o", "config_change_nlp_fail_mode", [], VIEJA)

# Residuo: un `guardian_events` que el purgador no puede inspeccionar (SQL NULL de verdad). Sólo
# se usa en el test del umbral del contador.
RESIDUO_VIEJO = ("residuo_viejo", "gpt-4o", "passed", null(), VIEJA)


# ── Harness ───────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def factory():
    _client, factory, cleanup = build_app_client(DB)
    yield factory
    cleanup()


@pytest.fixture(scope="module")
def politicas_del_seed(factory):
    """Los plazos tal como los dejó la migración, leídos UNA vez para poder restaurarlos.

    Se leen en vez de hardcodearse —lo que hay que devolver a su lugar es lo que el seed haya
    puesto— pero se VERIFICAN contra las constantes de arriba: si el seed cambia, el número nuevo
    aparece a la vista en vez de colarse.
    """
    from src.models.compliance import RetentionPolicy
    db = factory()
    try:
        seed = {p.log_type: p.retention_days for p in db.query(RetentionPolicy).all()}
    finally:
        db.close()
    assert seed["usage_metadata"] == PLAZO_USO, seed
    assert max(seed.values()) == PLAZO_MAS_LARGO, seed
    return seed


@pytest.fixture(autouse=True)
def caja_en_cero(factory, politicas_del_seed):
    """`audit_logs` vacía y los plazos del seed puestos antes de cada test.

    Los plazos, y no sólo la tabla: este archivo entero vive de romper `retention_policies`, así
    que sin restaurar, el test siguiente mediría la política que le dejó el anterior. La
    disciplina de la casa es que cada test sea autosuficiente e independiente del orden.
    """
    from src.models.audit import AuditLog
    from src.models.compliance import RetentionPolicy
    db = factory()
    try:
        db.query(AuditLog).delete()
        vivas = {p.log_type: p for p in db.query(RetentionPolicy).all()}
        for log_type, dias in politicas_del_seed.items():
            vivas[log_type].retention_days = dias
        db.commit()
    finally:
        db.close()


@pytest.fixture
def corrida_real(monkeypatch):
    """Corrida que BORRA: `SENTINEL_PURGE_DRY_RUN=false` explícito.

    El default del producto es el simulacro (mitad de la red de H7), así que un test que quiera
    medir borrado tiene que pedirlo — que es la disciplina que la perilla le impone al operador.
    """
    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "false")
    monkeypatch.setenv("SENTINEL_PURGE_BATCH_PAUSE_MS", "0")


def sembrar(factory, filas):
    """Las `filas` en `audit_logs`, con la edad pedida. Devuelve marca → id."""
    from src.models.audit import AuditLog
    from src.models.tenant import DEFAULT_TENANT_ID
    ahora = datetime.utcnow()
    db = factory()
    try:
        marcas = {}
        for marca, modelo, estado, eventos, edad in filas:
            fila_id = uuid.uuid4()
            db.add(AuditLog(
                id=fila_id, tenant_id=DEFAULT_TENANT_ID,
                timestamp=ahora - timedelta(days=edad), model=modelo,
                prompt_tokens=0, completion_tokens=0, cost_usd=0,
                pii_detected=False, compliance_status=estado, latency_ms=7,
                guardian_events=eventos,
            ))
            marcas[marca] = str(fila_id)
        db.commit()
        return marcas
    finally:
        db.close()


def poner_plazo(factory, **por_clase):
    """`retention_days` de las clases nombradas. Es el camino por el que entra el valor malo.

    Se escribe por DB directa y no por el PUT a propósito: lo que se mide es qué hace el PURGADOR
    con un plazo inválido que ya está en la tabla, venga del endpoint de hoy (que lo acepta con
    200), de una fuente futura o de un SQL a mano. Atarlo al endpoint volvería este archivo un
    test del endpoint — que es T015 y es de otro.
    """
    from src.models.compliance import RetentionPolicy
    db = factory()
    try:
        for clase, dias in por_clase.items():
            filas = (db.query(RetentionPolicy)
                     .filter(RetentionPolicy.log_type == clase)
                     .update({RetentionPolicy.retention_days: dias}))
            assert filas == 1, f"no existe la política de {clase!r}"
        db.commit()
    finally:
        db.close()


def ids_vivos(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return {str(fila_id) for (fila_id,) in db.query(AuditLog.id).all()}
    finally:
        db.close()


def por_clase(corrida):
    return {r.clase: r for r in corrida.clases}


# ── El piso no borra ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("plazo", [0, -30])
def test_un_plazo_no_positivo_no_borra_ni_una_fila(factory, corrida_real, plazo):
    """Los dos valores que el endpoint acepta hoy con 200, contra el purgador.

    `0` y `-30` no son el mismo bug con distinto signo: con `0` el cutoff se para EN el reloj de
    la DB y se lleva todo lo escrito hasta ese instante; con `-30` se para en el futuro y se
    lleva además lo que se escriba durante el próximo mes. Los dos tienen que abortar, y ninguno
    puede llevarse la fila de hoy — que es literalmente la que el gate vio morir.
    """
    from src.services.retention import purger

    marcas = sembrar(factory, [USO_VIEJA, USO_HOY])
    poner_plazo(factory, usage_metadata=plazo)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    vivos = ids_vivos(factory)
    assert marcas["uso_hoy"] in vivos, (
        f"con retention_days={plazo} el cutoff se para en el presente o en el futuro: una fila "
        "escrita HOY es exactamente la que el gate adversarial vio morir")
    assert marcas["uso_vieja"] in vivos, (
        f"con retention_days={plazo} no hay frontera válida: tampoco muere lo viejo")
    uso = por_clase(corrida)["usage_metadata"]
    assert uso.result == purger.RESULTADO_ERROR
    assert uso.rows_deleted == 0
    assert uso.cutoff is None, "no hubo frontera: el rastro no puede inventar una"


def test_la_corrida_dice_la_clase_y_el_valor(factory, corrida_real, caplog):
    """Abortar en silencio es retención apagada sin que nadie se entere: el error tiene nombre.

    Se miden los dos caminos porque son dos públicos distintos: dentro de `run_once` (el
    scheduler, que corre solo de madrugada) el motivo tiene que quedar en el log con la clase y
    el valor, porque hasta que entre T010 el log ES el rastro; y en la llamada suelta —la
    operación manual del DPO que acaba de tocar un plazo— la excepción sube y se ve en la cara.
    """
    from src.services.retention import purger

    sembrar(factory, [USO_VIEJA])
    poner_plazo(factory, usage_metadata=0)

    with caplog.at_level(logging.ERROR, logger="src.services.retention.purger"):
        purger.run_once(session_factory=factory, run_now=True)

    caidas = [r.exc_info[1] for r in caplog.records if r.exc_info]
    invalidos = [e for e in caidas if isinstance(e, purger.PlazoDeRetencionInvalido)]
    assert invalidos, "la corrida abortó la clase sin decir que el plazo era inválido"
    texto = "\n".join(str(e) for e in invalidos)
    assert "usage_metadata" in texto, "sin la clase, el operador no sabe cuál arreglar"
    assert "retention_days=0" in texto, "sin el valor, no sabe qué arreglar"
    # Y no sólo en el objeto de la excepción: en lo que el operador REALMENTE lee, que es la
    # línea renderizada del log. Hasta que T010 escriba el `purge_log`, eso es todo el rastro.
    assert "PlazoDeRetencionInvalido" in caplog.text and "retention_days=0" in caplog.text

    poner_plazo(factory, usage_metadata=-30)
    with pytest.raises(purger.PlazoDeRetencionInvalido) as caida:
        purger.purgar_clase("usage_metadata", session_factory=factory, run_now=True)
    assert "usage_metadata" in str(caida.value)
    assert "retention_days=-30" in str(caida.value)


def test_la_clase_mal_configurada_no_frena_a_las_otras_tres(factory, corrida_real):
    """La decisión del dictamen, escrita como test: aborta la CLASE, no la corrida.

    El escenario es el del operador: una clase mal tecleada de cuatro. Lo que tiene que pasar es
    que no se destruya ni una fila de la clase rota Y que las otras sigan enforced — abortar la
    corrida entera cambiaría un fallo acotado por una no-conformidad ancha del Art. 5.1.e, en un
    job que corre de madrugada y sin nadie mirando.

    Si algún día se decide lo contrario, este test es el que hay que invertir con el motivo
    escrito. No borrar.
    """
    from src.services.retention import purger

    marcas = sembrar(factory, [USO_VIEJA, SEGURIDAD_VIEJA, CONFIG_VIEJA])
    poner_plazo(factory, usage_metadata=0)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    vivos = ids_vivos(factory)
    assert marcas["uso_vieja"] in vivos, "la clase con el plazo inválido no se toca"
    for marca in ("seguridad_vieja", "config_vieja"):
        assert marcas[marca] not in vivos, (
            f"{marca} tiene su propio plazo, válido: una clase rota no la indulta")

    resultados = por_clase(corrida)
    assert resultados["usage_metadata"].result == purger.RESULTADO_ERROR
    assert [c for c, r in resultados.items() if r.result == purger.RESULTADO_ERROR] == [
        "usage_metadata"], "sólo la clase mal configurada queda en error"
    assert sum(r.rows_deleted for r in corrida.clases) == 2


# ── El piso también rige en el simulacro ──────────────────────────────────────────────


def test_el_simulacro_no_reporta_un_numero_bajo_un_plazo_invalido(factory, monkeypatch):
    """El ensayo es lo que el DPO FIRMA: no puede devolver un conteo sin frontera creíble.

    Las dos mitades van juntas y en este orden a propósito. Primero con el plazo del seed, para
    ver que el ensayo SÍ cuenta (si no, el segundo assert lo pasaría también un simulacro roto
    que nunca cuenta nada). Después con la política en 0: sin piso, el conteo saldría bajo
    `cutoff = AHORA`, o sea la clase entera, y con `result: ok` al lado — un número inventado,
    firmado.
    """
    from src.services.retention import purger

    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "true")
    marcas = sembrar(factory, [USO_VIEJA, USO_HOY])

    ensayo = purger.purgar_clase("usage_metadata", session_factory=factory, run_now=True)
    assert ensayo.dry_run is True
    assert ensayo.rows_deleted == 1, "sólo la vieja está vencida al plazo del seed"

    poner_plazo(factory, usage_metadata=0)
    corrida = purger.run_once(session_factory=factory, run_now=True)

    uso = por_clase(corrida)["usage_metadata"]
    assert corrida.dry_run is True
    assert uso.result == purger.RESULTADO_ERROR
    assert uso.rows_deleted == 0, (
        "un ensayo con plazo inválido no reporta «se irían N filas»: no hay frontera de la que "
        "salga ese N")
    assert set(marcas.values()) <= ids_vivos(factory)


def test_sin_ninguna_politica_valida_el_residuo_no_se_cuenta(factory, corrida_real):
    """El umbral del contador tiene el mismo piso, y por el mismo motivo aunque no borre.

    `filas_no_clasificadas` se cuenta bajo el plazo MÁS LARGO vigente. Con todas las políticas en
    0 ese umbral se para en AHORA y el contador reportaría «toda fila indecidible de la tabla
    está vencida» — otro número firmado que no sale de ninguna frontera. Lo correcto es `None`,
    que en este rastro significa «no lo pude contar» y ya está separado de `0` («conté y no
    hay»).
    """
    from src.services.retention import purger

    marcas = sembrar(factory, [RESIDUO_VIEJO, USO_VIEJA])
    poner_plazo(factory, usage_metadata=0, security_events=0, config_audit=0,
                prompt_content=0)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert corrida.filas_no_clasificadas is None, "sin umbral creíble no se cuenta: no es cero"
    assert corrida.cutoff_no_clasificadas is None
    assert set(marcas.values()) <= ids_vivos(factory), "y no se borró nada"
    assert all(r.result == purger.RESULTADO_ERROR for r in corrida.clases)


# ── Y lo válido sigue funcionando igual que antes ─────────────────────────────────────


def test_el_plazo_del_borde_purga_normalmente(factory, corrida_real):
    """`PLAZO_MINIMO_DIAS` es un plazo VÁLIDO, no el primero que se rechaza.

    Es el test que impide que la red se vuelva un piso inventado: hoy no hay mínimos por clase
    legibles por código (§«Por qué el piso es `> 0`» de `purger.py`), así que el purgador no
    puede rechazar un plazo de un día — con él, el cutoff ya cae en el pasado, que es la única
    propiedad que este módulo necesita. El día que FR-007 traiga mínimos por clase, el que los
    aplica es el endpoint y este borde se mueve con la fuente en la mano, no de memoria.
    """
    from src.services.retention import purger

    assert purger.PLAZO_MINIMO_DIAS == 1, (
        "el piso cambió: revisá que salga de la fuente y actualizá el dataset de este test")
    marcas = sembrar(factory, [
        ("uso_de_dos_dias", "ollama-qwen3-4b", "passed", [], purger.PLAZO_MINIMO_DIAS + 1),
        USO_HOY,
    ])
    poner_plazo(factory, usage_metadata=purger.PLAZO_MINIMO_DIAS)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    uso = por_clase(corrida)["usage_metadata"]
    assert uso.result == purger.RESULTADO_OK
    assert uso.cutoff is not None
    assert uso.rows_deleted == 1
    vivos = ids_vivos(factory)
    assert marcas["uso_de_dos_dias"] not in vivos, "vencida al plazo del borde: tenía que morir"
    assert marcas["uso_hoy"] in vivos, "escrita hoy: el borde no la alcanza"


def test_con_los_plazos_del_seed_la_corrida_es_la_de_siempre(factory, corrida_real):
    """La regresión: sin plazos rotos, el piso no se nota en ningún lado.

    Una red que cambia el comportamiento del camino feliz no es una red, es un bug nuevo. Se
    verifican las tres cosas que el piso podría haber roto: ninguna clase en error, lo vencido
    muere, y lo fresco vive.
    """
    from src.services.retention import purger

    marcas = sembrar(factory, [USO_VIEJA, USO_HOY, SEGURIDAD_VIEJA, CONFIG_VIEJA])

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert [r.clase for r in corrida.clases if r.result != purger.RESULTADO_OK] == []
    assert {r.clase for r in corrida.clases} == set(purger.classifier.clases())
    assert sum(r.rows_deleted for r in corrida.clases) == 3
    vivos = ids_vivos(factory)
    assert marcas["uso_hoy"] in vivos
    for marca in ("uso_vieja", "seguridad_vieja", "config_vieja"):
        assert marcas[marca] not in vivos
    assert corrida.filas_no_clasificadas == 0, "el contador sigue contando: 0 es «conté y no hay»"
