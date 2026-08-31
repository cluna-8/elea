"""El residuo del fail-closed se CUENTA y se dice (spec 018, dictamen del manager 14-ago, c).

## Qué decisión defiende este archivo

El clasificador es fail-closed: una fila cuyo `guardian_events` no prueba que sea tráfico —el
NULL de SQL, el `'null'::jsonb`, un jsonb que no es lista, un primer evento que no es objeto—
no la reclama ninguna clase y por lo tanto **no se borra**. Eso ya está decidido y no se
re-discute acá: del otro lado de la duda puede haber un eslabón de la cadena de licencias en un
estado que el código no reconoce, y un `DELETE` no se deshace.

Lo que este archivo mide es la mitad que el dictamen agregó: **que deje de ser cierto el «nadie
se entera»**. La corrida cuenta esas filas y las reporta en `filas_no_clasificadas`, en la
corrida REAL y en el SIMULACRO — «el officer que ensaya la purga tiene que ver el residuo ANTES
de apretar el botón» (dictamen, textual). Un contador que sólo saliera en la corrida real le
mostraría el número a quien ya borró.

## Las tres cosas que el número tiene que cumplir, y por qué las tres

1. **exacto** — no «al menos». Un contador que sobra o falta por una fila no sirve para
   decidir si se aprieta el botón;
2. **no borra** — contarlas no puede cambiarlas de bando. El test verifica las mismas filas
   vivas DESPUÉS de una corrida real que sí se llevó lo que le correspondía;
3. **separa la duda de la exclusión por diseño** — los eslabones de la cadena tampoco los
   reclama ninguna clase, y NO son residuo: son la exclusión permanente de FR-003 y el purgador
   sabe perfectamente por qué no los toca. Si se contaran juntos, en una caja con dos años de
   cadena el officer leería un número grande que no le señala ningún problema, o sea un
   contador que se puede ignorar — que es como se muere un contador.

Por eso el eslabón de este dataset lo emite el **emisor real** (`emit_license_event`, no un
dict a mano): lo que hay que dejar fuera del contador es la forma que el producto emite, y el
día que `_append_chained` cambie de forma esto tiene que enterarse por acá.

## El piso del contador está TESTEADO, no escondido

`filas_no_clasificadas` cuenta lo vencido bajo el plazo MÁS LARGO vigente (hoy los 730 d de
`config_audit`), porque una fila que ninguna clase reclama tampoco tiene plazo propio y el único
umbral que no admite discusión es el que la deja vencida bajo TODAS las políticas a la vez. La
consecuencia —una fila deforme de 400 días existe y todavía no se cuenta— es una decisión, así
que tiene su test (`test_el_residuo_entre_plazos_todavia_no_se_cuenta`) en vez de quedar como
una sorpresa para el que lea el número.

## Que este archivo muerde está MEDIDO (corrida de mutación del 14-ago)

Cada mutante se aplicó a mano sobre `purger.py`, se corrieron los 29 tests de los tres archivos
que tocan este código (`tests/integration/test_retention_purga_residuo.py`,
`tests/unit/test_retention_purga_ventana.py` y `tests/unit/test_retention_skeleton.py`) y se
restauró. La columna es cuántos se ponen ROJOS:

| mutación sobre `purger.py`                                                | rojos |
|---------------------------------------------------------------------------|-------|
| el `DELETE` pierde el predicado de clase (se lleva lo no clasificado)      |   6   |
| `en_ventana` lee el naive como hora local del contenedor (ignora el huso)  |   6   |
| el residuo se cuenta SIN el filtro de vencidas (cualquier edad)            |   4   |
| `es_residuo()` sin `_guardian_events_no_inspeccionable()` (cuenta la cadena)|   4   |
| el cutoff del residuo usa el plazo más CORTO en vez del más largo          |   4   |
| el contador no corre en simulacro                                          |   2   |
| el `DELETE` no respeta el tamaño de lote (se lleva todo de una)            |   2   |
| `es_residuo()` sin `_ninguna_clase_la_reclama()`                           |   1   |
| fuera de ventana reporta `0` en vez de `None`                              |   1   |
| el log de la corrida no menciona el residuo                                |   1   |
| una clase caída se lleva puesta la corrida (sin el `except`)               |   1   |
| ventana cerrada ⇒ `partial` siempre (sin mirar si quedó backlog)           |   1   |
| el simulacro no calcula los lotes que harían falta                         |   1   |
| la ventana se lee cerrada en los dos extremos (`inicio <= t <= fin`)       |   1   |
| la ventana que cruza medianoche deja de soportarse                         |   1   |

Cero mutantes sobrevivientes. El de `_ninguna_clase_la_reclama()` empezó en 0 —hoy es un
mutante equivalente, porque toda fila indecidible falla también el portón— y se lo hizo morder
con `test_lo_que_una_clase_reclama_deja_de_ser_residuo`, que dobla el clasificador en vez de
inventar una fila que el clasificador real no puede producir.
"""
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

DB = "sentinel_test_retencion_purga_residuo"

# Plazos del seed 004 (`alembic/versions/004_compliance_tables.py:100-109`). Van a mano y NO
# importados: si alguien cambia el seed, este archivo tiene que ponerse rojo y explicar por qué,
# no seguirlo en silencio.
PLAZO_MAS_LARGO = 730   # config_audit
PLAZO_MEDIO = 365       # usage_metadata / security_events

# Edades del dataset, todas relativas a los plazos de arriba y ninguna mágica.
VIEJA = PLAZO_MAS_LARGO + 70    # vencida para las cuatro clases y para el contador
ENTRE_PLAZOS = PLAZO_MEDIO + 35  # vencida para uso/seguridad, NO para el umbral del residuo
FRESCA = 1                       # viva para todo

# (marca, model, compliance_status, guardian_events, edad_dias)
#
# Las filas se siembran por DB directa —como el dataset abusivo de al lado y por el mismo
# motivo— porque lo que se mide es qué hace la CORRIDA con filas de una forma y una edad dadas,
# no por qué puerta entraron. Además ningún escritor vivo puede producir estas formas ni estas
# edades: `guardian_events` no es declarable por el cliente en ninguno de los tres productores
# —eso lo clava `test_retencion_dataset_abusivo.py::test_ningun_escritor_deja_que_el_cliente_
# le_ponga_el_seq_a_su_propia_fila`— y las edades son del pasado. La única fila cuya FORMA
# importa que sea auténtica es el eslabón, y ésa la emite el emisor real (abajo).
CON_CLASE_VENCIDAS = [
    ("vencida_uso", "ollama-qwen3-4b", "passed", [], VIEJA),
    ("vencida_bloqueo", "claude-3-5-sonnet-20241022", "blocked_secret", [], VIEJA),
    ("vencida_config", "gpt-4o", "config_change_nlp_fail_mode", [], VIEJA),
]

CON_CLASE_VIVAS = [
    ("fresca_uso", "ollama-qwen3-4b", "passed", [], FRESCA),
    ("fresca_bloqueo", "gpt-4o", "blocked_prohibited", [], FRESCA),
]

# El residuo de verdad: las cuatro formas que el purgador NO PUEDE decidir, ya vencidas bajo
# cualquier plazo. Son las que el contador tiene que ver.
RESIDUO_VENCIDO = [
    # SQL NULL de verdad (la columna es nullable): `NULL -> 0` es NULL y no hay nada que leer.
    ("residuo_sql_null", "gpt-4o", "blocked_prohibited", null(), VIEJA),
    # El JSON `null`, que NO es lo mismo: el tipo JSON de SQLAlchemy trae `none_as_null=False`,
    # así que pasar `None` persiste `'null'::jsonb` y `jsonb_typeof` dice `'null'`, no NULL.
    ("residuo_json_null", "gpt-4o", "passed", None, VIEJA),
    # Lista cuyo primer elemento no es un objeto: no hay dónde buscar marcas.
    ("residuo_lista_de_numeros", "gpt-4o", "passed", [7], VIEJA),
    # Un objeto pelado: no es una lista de eventos.
    ("residuo_objeto_pelado", "gpt-4o", "blocked_secret", {"upstream": []}, VIEJA),
]

# Residuo que todavía NO cuenta: mismo jsonb indecidible, edad por debajo del umbral.
RESIDUO_NO_VENCIDO = [
    ("residuo_fresco", "gpt-4o", "passed", null(), FRESCA),
    ("residuo_entre_plazos", "gpt-4o", "passed", null(), ENTRE_PLAZOS),
]

TODAS = CON_CLASE_VENCIDAS + CON_CLASE_VIVAS + RESIDUO_VENCIDO + RESIDUO_NO_VENCIDO


# ── Harness ───────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def factory():
    _client, factory, cleanup = build_app_client(DB)
    yield factory
    cleanup()


@pytest.fixture(scope="module")
def politicas_del_seed(factory):
    """Los plazos tal como los dejó el seed 004, leídos UNA vez para poder restaurarlos.

    Se leen en vez de hardcodearse: lo que hay que devolver a su lugar es lo que la migración
    haya puesto, no lo que este archivo crea que puso. Las constantes de arriba
    (`PLAZO_MAS_LARGO`, `PLAZO_MEDIO`) siguen a mano y contra ellas se verifica acá — si el seed
    cambia, esto se pone rojo con el número nuevo a la vista.
    """
    from src.models.compliance import RetentionPolicy
    db = factory()
    try:
        seed = {p.log_type: p.retention_days for p in db.query(RetentionPolicy).all()}
    finally:
        db.close()
    assert max(seed.values()) == PLAZO_MAS_LARGO, seed
    assert seed["usage_metadata"] == PLAZO_MEDIO, seed
    return seed


@pytest.fixture(autouse=True)
def caja_en_cero(factory, politicas_del_seed):
    """Cada test arranca con `audit_logs` vacía y los plazos del seed puestos.

    Los dos, y no sólo el primero: hay tests que cambian `retention_policies` —bajar un plazo,
    borrar la fila de una clase— y sin restaurarlos el siguiente test mediría la política que le
    dejó el anterior. La disciplina de la casa es que cada test sea autosuficiente e
    independiente del orden, y acá se paga en la fixture porque el estado que ensucian está en
    una tabla, no en un objeto.

    `license_runtime_state` también se limpia: es lo que hace que el emisor real de la cadena
    arranque en `seq=1` en cada test.
    """
    from src.models.audit import AuditLog
    from src.models.compliance import RetentionPolicy
    from src.models.license_state import LicenseRuntimeState
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.query(LicenseRuntimeState).delete()
        vivas = {p.log_type: p for p in db.query(RetentionPolicy).all()}
        for log_type, dias in politicas_del_seed.items():
            if log_type in vivas:
                vivas[log_type].retention_days = dias
            else:
                db.add(RetentionPolicy(log_type=log_type, retention_days=dias,
                                       justification="restaurada por la suite"))
        db.commit()
    finally:
        db.close()


@pytest.fixture
def corrida_real(monkeypatch):
    """Corrida que BORRA: `SENTINEL_PURGE_DRY_RUN=false` explícito.

    El default del producto es el simulacro (`DEFAULT_DRY_RUN=True`, mitad de la red de H7), así
    que un test que quiera medir borrado tiene que pedirlo — que es exactamente la disciplina
    que la perilla busca imponerle al operador.
    """
    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "false")
    monkeypatch.setenv("SENTINEL_PURGE_BATCH_PAUSE_MS", "0")


def sembrar(factory, filas):
    """Las `filas` en la tabla, con la edad pedida. Devuelve marca → id."""
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


def sembrar_eslabon_viejo(factory, edad_dias=VIEJA):
    """Un eslabón por el EMISOR REAL de la 021, envejecido a `edad_dias`.

    Por el emisor y no por un dict a mano: lo que el contador tiene que dejar afuera es la forma
    que el producto emite. Un `{"seq": 1}` escrito acá probaría que el contador ignora una forma
    que nadie emite, y el día que `_append_chained` cambie nadie se enteraría por este lado.

    Se envejece con un UPDATE de `audit_logs.timestamp` y NADA más: la cadena hashea el CUERPO
    del evento (`guardian_events[0]`, con su propio `ts` adentro), así que mover la columna no
    toca el eslabón. Y hace falta envejecerlo porque el emisor escribe con el reloj de ahora:
    un eslabón fresco quedaría fuera del contador por edad y el test pasaría sin probar nada.
    """
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event
    from src.models.audit import AuditLog
    db = factory()
    try:
        emit_license_event(db, EVENT_SEAT_LIMIT, license_id="lic_test_0001",
                           seats_used=11, max_seats=10, reason="residuo-test")
        fila = db.query(AuditLog).filter(AuditLog.model == "license").one()
        assert "seq" in fila.guardian_events[0], (
            "el emisor real dejó de escribir `seq` en el primer evento: si eso es a propósito, "
            "este test no es el único que hay que revisar")
        fila.timestamp = datetime.utcnow() - timedelta(days=edad_dias)
        db.commit()
        return str(fila.id)
    finally:
        db.close()


def ids_vivos(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return {str(fila_id) for (fila_id,) in db.query(AuditLog.id).all()}
    finally:
        db.close()


def total_filas(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return db.query(AuditLog).count()
    finally:
        db.close()


# ── El contador ───────────────────────────────────────────────────────────────────────


def test_las_dos_formas_nulas_del_dataset_son_de_verdad_distintas(factory):
    """El dataset dice sembrar DOS formas nulas: hay que verificar que la tabla tenga dos.

    `null()` persiste SQL NULL y `None` persiste `'null'::jsonb`, porque el tipo JSON de
    SQLAlchemy trae `none_as_null=False`. Si esa diferencia se perdiera —un cambio de versión,
    alguien que «normaliza» el sembrado— las dos filas colapsarían en una sola forma y el resto
    del archivo seguiría VERDE midiendo la mitad: sólo el SQL NULL muerde el trivalente de
    Postgres, y sólo el `'null'::jsonb` muerde el `jsonb_typeof`.
    """
    from sqlalchemy import text

    sembrar(factory, RESIDUO_VENCIDO)
    db = factory()
    try:
        formas = [f for (f,) in db.execute(text(
            "SELECT coalesce(jsonb_typeof(guardian_events), 'SQL NULL') FROM audit_logs")).all()]
    finally:
        db.close()
    # `[7]` cuenta como `array` y `{"upstream": []}` como `object`: las cuatro filas del residuo
    # son cuatro formas distintas, y las dos nulas son dos.
    assert sorted(formas) == ["SQL NULL", "array", "null", "object"], formas


def test_la_corrida_real_cuenta_el_residuo_exacto_y_no_lo_borra(factory, corrida_real):
    """El escenario completo: se lleva lo que le toca, cuenta lo que no pudo decidir, y lo deja.

    Los tres asserts van juntos a propósito. Que el número sea 4 sin que la corrida borre nada
    lo pasaría también un purgador roto que no borra; que borre sin contar lo pasaría el
    comportamiento que el dictamen vino a cambiar. Lo que hay que ver es la misma corrida
    haciendo las dos cosas.
    """
    from src.services.retention import purger

    marcas = sembrar(factory, TODAS)
    eslabon = sembrar_eslabon_viejo(factory)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert corrida.dry_run is False
    # Las cuatro formas indecidibles y VENCIDAS, ni una más: ni el eslabón (excluido por
    # diseño), ni el residuo fresco, ni el de 400 días.
    assert corrida.filas_no_clasificadas == len(RESIDUO_VENCIDO)
    assert corrida.cutoff_no_clasificadas is not None

    vivos = ids_vivos(factory)
    # Lo que el purgador SÍ decidió: las tres clases vencidas ya no están.
    for marca, *_ in CON_CLASE_VENCIDAS:
        assert marcas[marca] not in vivos, f"{marca} tenía clase y estaba vencida: debía morir"
    # Y lo contado sigue exactamente donde estaba: contar no es borrar.
    for marca, *_ in RESIDUO_VENCIDO + RESIDUO_NO_VENCIDO:
        assert marcas[marca] in vivos, f"{marca} es residuo: se cuenta, NO se borra"
    for marca, *_ in CON_CLASE_VIVAS:
        assert marcas[marca] in vivos, f"{marca} no está vencida"
    assert eslabon in vivos, "la cadena de licencias no se purga jamás (FR-003)"

    # Y el rastro por clase sigue siendo por clase: el residuo no se le atribuyó a ninguna.
    assert {r.clase for r in corrida.clases} == set(purger.classifier.clases())
    assert sum(r.rows_deleted for r in corrida.clases) == len(CON_CLASE_VENCIDAS)


def test_el_simulacro_reporta_el_mismo_residuo_y_no_borra_nada(factory, monkeypatch):
    """«El officer que ensaya la purga tiene que ver el residuo ANTES de apretar el botón».

    Mismo dataset que la corrida real, mismo número. Si el contador viviera sólo en el camino
    que borra, este test se cae — y es el único lugar donde se cae, porque el simulacro es el
    modo por default y nadie más lo mira.
    """
    from src.services.retention import purger

    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "true")
    marcas = sembrar(factory, TODAS)
    sembrar_eslabon_viejo(factory)
    antes = total_filas(factory)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert corrida.dry_run is True
    assert corrida.filas_no_clasificadas == len(RESIDUO_VENCIDO)
    # El simulacro cuenta lo que se habría llevado…
    assert sum(r.rows_deleted for r in corrida.clases) == len(CON_CLASE_VENCIDAS)
    # …y no se llevó nada, ni siquiera lo que sí tenía clase.
    assert total_filas(factory) == antes
    assert set(marcas.values()) <= ids_vivos(factory)


def test_sin_residuo_el_contador_dice_cero(factory, corrida_real):
    """Cero de verdad: la tabla tiene tráfico y cadena, y ninguna fila indecidible vencida.

    El `0` es tan importante como el número: un contador que siempre reporta algo (porque
    cuenta también los eslabones, por ejemplo) no le sirve al officer para decidir nada.
    """
    from src.services.retention import purger

    sembrar(factory, CON_CLASE_VENCIDAS + CON_CLASE_VIVAS)
    sembrar_eslabon_viejo(factory)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert corrida.filas_no_clasificadas == 0


def test_el_eslabon_del_emisor_real_no_es_residuo(factory, corrida_real):
    """La forma que emite `_append_chained` no entra en el contador, y sigue viva.

    Es la mitad «no es un bug, es la exclusión de FR-003» del número. Acopla el contador con el
    emisor REAL: si mañana el emisor deja de escribir un `guardian_events` inspeccionable —una
    lista con un objeto adentro—, su eslabón pasa a contarse como residuo y este test lo dice
    ANTES de que un cliente vea el número inflado.
    """
    from src.services.retention import purger

    eslabon = sembrar_eslabon_viejo(factory)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert corrida.filas_no_clasificadas == 0, (
        "un eslabón de la cadena no es residuo: no es que el purgador no pudiera decidir, es "
        "que decidió no tocarlo (FR-003)")
    assert eslabon in ids_vivos(factory)


def test_el_residuo_entre_plazos_todavia_no_se_cuenta(factory, corrida_real):
    """El piso del contador, escrito como test para que no sorprenda a nadie.

    Una fila indecidible de `ENTRE_PLAZOS` días está vencida bajo `usage_metadata` (365 d) pero
    no bajo `config_audit` (730 d). Como ninguna clase la reclama, tampoco tiene plazo propio, y
    el contador usa el umbral que no admite discusión: vencida bajo TODAS las políticas. El
    número es un piso, y esto es lo que el piso deja afuera.

    Si algún día se decide contar por «vencida bajo alguna», este test es el que hay que
    invertir, con el motivo escrito — no borrar.
    """
    from src.services.retention import purger

    marcas = sembrar(factory, RESIDUO_NO_VENCIDO)

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert corrida.filas_no_clasificadas == 0
    assert set(marcas.values()) <= ids_vivos(factory), "no vencida y sin clase: no se toca"


def test_el_umbral_del_residuo_sale_de_la_tabla_y_no_de_una_constante(factory, corrida_real):
    """Si el DPO acorta el plazo más largo, el umbral del residuo se mueve con él.

    Es lo que hace que el contador siga siendo verdad después de un cambio de política: con el
    umbral horneado, el officer que baja `config_audit` a 90 d seguiría sin ver el residuo de
    100 días que su propia decisión acaba de dejar vencido.
    """
    from src.models.compliance import RetentionPolicy
    from src.services.retention import purger

    marcas = sembrar(factory, RESIDUO_NO_VENCIDO)
    assert purger.run_once(session_factory=factory, run_now=True).filas_no_clasificadas == 0

    # El plazo más largo baja por debajo de `ENTRE_PLAZOS` y queda por encima de `FRESCA`: el
    # umbral se mueve lo justo para que UNA de las dos filas pase a estar vencida. Un cambio que
    # las cruzara a las dos no distinguiría «el umbral se movió» de «el contador cuenta todo».
    nuevo_plazo = (ENTRE_PLAZOS + FRESCA) // 2
    db = factory()
    try:
        db.query(RetentionPolicy).update({RetentionPolicy.retention_days: nuevo_plazo})
        db.commit()
    finally:
        db.close()

    corrida = purger.run_once(session_factory=factory, run_now=True)
    assert corrida.filas_no_clasificadas == 1, "sólo la de ENTRE_PLAZOS quedó vencida"
    assert set(marcas.values()) <= ids_vivos(factory), "cambiar el plazo no cambia el fail-closed"


def test_lo_que_una_clase_reclama_deja_de_ser_residuo(factory, monkeypatch):
    """Quién define el residuo es el CLASIFICADOR, no este archivo.

    Es la mitad `_ninguna_clase_la_reclama()` del predicado, y sin este test no la mide nada:
    hoy toda fila indecidible falla también el portón, así que sacar ese conjunto no cambia
    ningún número — un mutante equivalente, o sea código que nadie cuida. La condición existe
    para el día que el clasificador aprenda a reclamar alguna de estas formas: esa fila tiene
    que pasar a morir con su clase y salir del contador SOLA, sin que nadie venga a mantener el
    purgador.

    Se dobla `classifier.predicado` (el colaborador, no los datos) porque el clasificador real
    no puede producir hoy esa situación — que es justamente el motivo por el que el mutante
    sobrevive. En simulacro para que el doble no borre nada: lo que se mide es el CONTEO.
    """
    from sqlalchemy import true

    from src.services.retention import purger

    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "true")
    sembrar(factory, RESIDUO_VENCIDO)
    assert purger.run_once(session_factory=factory,
                           run_now=True).filas_no_clasificadas == len(RESIDUO_VENCIDO)

    # Un clasificador que reclama todo: no queda residuo que contar, aunque el jsonb siga
    # siendo igual de indecidible.
    monkeypatch.setattr(purger.classifier, "predicado", lambda clase: true())

    assert purger.run_once(session_factory=factory, run_now=True).filas_no_clasificadas == 0


def test_el_contador_queda_en_el_log_de_la_corrida(factory, corrida_real, caplog):
    """Hasta que T010 escriba el `purge_log`, el log ES el rastro — y tiene que gritar.

    `warning` y no `info` cuando hay residuo: el número existe para que alguien se entere, y en
    una caja con el nivel en INFO por default un `info` más entre miles es lo mismo que nada.
    """
    import logging

    from src.services.retention import purger

    sembrar(factory, RESIDUO_VENCIDO)

    with caplog.at_level(logging.INFO, logger="src.services.retention.purger"):
        corrida = purger.run_once(session_factory=factory, run_now=True)

    avisos = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert avisos, "una corrida con residuo tiene que dejar un warning"
    texto = "\n".join(r.getMessage() for r in avisos)
    assert str(corrida.filas_no_clasificadas) in texto
    assert corrida.run_id in texto, "el número sin el id de corrida no se puede rastrear"


def test_fuera_de_ventana_no_se_cuenta_y_se_dice_que_no_se_conto(factory, monkeypatch):
    """`None` no es `0`: «no conté» y «no hay» son dos hechos distintos y el rastro los separa.

    Un `0` acá sería una afirmación firmada sobre una tabla que nadie miró — el «nadie se
    entera» de vuelta, esta vez desde adentro del contador.
    """
    from src.services.retention import purger

    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "false")
    # Ventana de un minuto en un huso donde no estamos: cerrada seguro, sin depender de la hora
    # a la que corra la suite. `en_ventana` compara en la TZ configurada, así que la ventana y
    # la zona se eligen juntas: 00:00-00:01 en UTC sólo está abierta un minuto por día.
    monkeypatch.setenv("SENTINEL_PURGE_WINDOW", "00:00-00:01")
    monkeypatch.setenv("SENTINEL_PURGE_WINDOW_TZ", "UTC")
    if purger.en_ventana(datetime.utcnow(), "00:00-00:01", "UTC"):
        pytest.skip("la suite corrió justo en el minuto de la ventana de prueba")

    marcas = sembrar(factory, TODAS)
    corrida = purger.run_once(session_factory=factory)

    assert corrida.clases == ()
    assert corrida.filas_no_clasificadas is None, "fuera de ventana no se cuenta: no es cero"
    assert set(marcas.values()) <= ids_vivos(factory)


def test_una_clase_caida_no_se_lleva_puesto_el_contador(factory, corrida_real):
    """El residuo se cuenta igual aunque una clase falle: son dos preguntas distintas.

    Se rompe la clase de verdad —borrándole la política, que es el modo de falla real— en vez de
    parchear el módulo: así el test mide el camino de error que el código tiene, no uno inventado.
    """
    from src.models.compliance import RetentionPolicy
    from src.services.retention import purger

    sembrar(factory, RESIDUO_VENCIDO)
    db = factory()
    try:
        db.query(RetentionPolicy).filter(
            RetentionPolicy.log_type == "usage_metadata").delete()
        db.commit()
    finally:
        db.close()

    corrida = purger.run_once(session_factory=factory, run_now=True)

    caidas = [r for r in corrida.clases if r.result == purger.RESULTADO_ERROR]
    assert [r.clase for r in caidas] == ["usage_metadata"]
    assert caidas[0].cutoff is None, "sin plazo no hubo frontera: el rastro no la inventa"
    assert corrida.filas_no_clasificadas == len(RESIDUO_VENCIDO)


# ── La corrida por lotes que hay debajo del contador ──────────────────────────────────
#
# Estos dos no son del contador: son del cuerpo de la corrida (T008), que se implementó en el
# mismo cambio porque sin corrida no hay dónde contar nada. Viven acá y no en un archivo aparte
# para que el código nuevo y sus tests estén en el mismo diff. El SC-001 completo —200 días
# sintéticos, cadena intercalada, plazo acortado en caliente, reloj de la DB— es T012 y NO está
# cubierto acá: lo que se mide es lo que este cambio agregó.


def test_la_corrida_recorre_la_clase_en_lotes(factory, monkeypatch):
    """El backlog se va en lotes acotados, y el simulacro predice CUÁNTOS.

    Los lotes son lo que sostiene SC-003: un `DELETE` único de millones de filas se toma la
    tabla más caliente del producto por un rato largo. Y el `batches` del simulacro es la mitad
    útil del ensayo — «se van 412.000 filas» no le dice al officer si eso son tres lotes o tres
    mil.
    """
    from src.services.retention import purger

    monkeypatch.setenv("SENTINEL_PURGE_BATCH_SIZE", "2")
    monkeypatch.setenv("SENTINEL_PURGE_BATCH_PAUSE_MS", "0")
    cinco = [(f"vieja_{i}", "ollama-qwen3-4b", "passed", [], VIEJA) for i in range(5)]
    marcas = sembrar(factory, cinco)

    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "true")
    ensayo = purger.purgar_clase("usage_metadata", session_factory=factory, run_now=True)
    assert (ensayo.rows_deleted, ensayo.batches) == (5, 3)   # 2 + 2 + 1
    assert set(marcas.values()) <= ids_vivos(factory), "el ensayo no borra"

    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "false")
    real = purger.purgar_clase("usage_metadata", session_factory=factory, run_now=True)
    assert (real.rows_deleted, real.batches) == (5, 3), "la corrida real confirma el ensayo"
    assert not (set(marcas.values()) & ids_vivos(factory))


def test_si_la_ventana_se_cierra_a_mitad_la_clase_queda_partial(factory, monkeypatch):
    """La ventana se respeta ENTRE lotes, y lo que queda a medias se declara `partial`.

    Sin el corte, una primera corrida con años de backlog seguiría borrando en hora punta. Sin
    el `partial`, el auditor leería «al día» sobre una clase que no lo está.

    Se dobla `en_ventana` —no el reloj— porque lo que se mide es la reacción del BUCLE al cierre
    de la ventana; esperar a que pase de verdad sería un test que tarda horas.
    """
    from src.services.retention import purger

    monkeypatch.setenv("SENTINEL_PURGE_BATCH_SIZE", "2")
    monkeypatch.setenv("SENTINEL_PURGE_BATCH_PAUSE_MS", "0")
    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "false")
    marcas = sembrar(factory, [(f"vieja_{i}", "ollama-qwen3-4b", "passed", [], VIEJA)
                               for i in range(5)])

    respuestas = iter([True, False])
    monkeypatch.setattr(purger, "en_ventana",
                        lambda *a, **k: next(respuestas, False))

    resultado = purger.purgar_clase("usage_metadata", session_factory=factory)

    assert resultado.result == purger.RESULTADO_PARCIAL
    assert (resultado.rows_deleted, resultado.batches) == (2, 1), "un solo lote y se cortó"
    assert len(set(marcas.values()) & ids_vivos(factory)) == 3


def test_ventana_cerrada_sobre_una_clase_al_dia_no_es_partial(factory, monkeypatch):
    """`partial` es «quedó backlog», no «la ventana estaba cerrada».

    Es la diferencia entre una señal que el auditor puede creer y una que aprende a ignorar: si
    toda clase al día que no alcanzó a correr saliera `partial`, el estado dejaría de significar
    nada el primer mes.
    """
    from src.services.retention import purger

    monkeypatch.setenv("SENTINEL_PURGE_DRY_RUN", "false")
    sembrar(factory, CON_CLASE_VIVAS)   # nada vencido
    monkeypatch.setattr(purger, "en_ventana", lambda *a, **k: False)

    resultado = purger.purgar_clase("usage_metadata", session_factory=factory)

    assert resultado.result == purger.RESULTADO_OK
    assert resultado.rows_deleted == 0


# ── HALLAZGOS / anotaciones ───────────────────────────────────────────────────────────
#
# 1. `filas_no_clasificadas` vive en `ResultadoCorrida` (nivel corrida) y NO en `ResultadoPurga`
#    (nivel clase). El comentario de `test_retencion_dataset_abusivo.py` —escrito por el agente
#    de al lado antes de que esto existiera— dice «sobre `ResultadoPurga`»: quedó desactualizado
#    por una línea. El motivo del cambio está en el docstring de `ResultadoCorrida`: un residuo
#    no tiene clase, así que repetirlo en las cuatro entradas invita a sumarlo por clase y
#    reportar cuatro veces las mismas filas, y atribuírselo a una miente sobre a qué clase
#    pertenece. De paso deja intacta la forma de la entrada de `purge_log` que fija
#    `data-model.md`.
#
# 2. Lo que este archivo NO mide, para que nadie lo lea de más: T009 (`response_text`) y T010
#    (escritura de `purge_log` + fila resumen `config_audit`) no están implementadas. El rastro
#    de una corrida hoy es el objeto devuelto y la línea de log; cuando T010 entre, el contador
#    ya tiene forma y hogar (la fila resumen es POR CORRIDA, como el contador).
#
# 3. Costo del contador, MEDIDO el 14-ago sobre Postgres 16 (compose jeff018), `audit_logs`
#    cargada a 200.000 filas repartidas en 900 días y con `ANALYZE` corrido: 7,4 ms el conteo
#    con el backlog entero vencido (Bitmap Index Scan sobre `ix_audit_logs_timestamp`) y 3,3 ms
#    después de los DELETE, contra 12,2 ms que cuesta el conteo de UNA sola clase (Parallel Seq
#    Scan) — y la corrida hace cuatro de ésos. La tabla completa está en el docstring de
#    `purger.run_once`. Es UNA consulta agregada por corrida y no se puede sacar de las
#    consultas de las clases: el residuo es exactamente lo que ninguna de ellas levanta.
#
#    No se ship‑ea como test porque medir esto pide cargar 200.000 filas: un test de 40 s en la
#    suite de cada PR, para vigilar un número que sólo cambia si cambia el plan del planner. La
#    receta para repetirlo está en el reporte de la tarea.
