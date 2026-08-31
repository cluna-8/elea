"""SC-001 nombrado, verificable POR SQL sin conocer la implementación (spec 018, T012).

Es el test de ACEPTACIÓN de la User Story 1: una instalación sembrada con ~200 días de datos
sintéticos (el seed reutilizable de T013), tras UNA corrida REAL completa del purgador
(`run_once`, `run_now=True`, `SENTINEL_PURGE_DRY_RUN=false`), tiene que cumplir las cinco cosas del
Success Criteria a la vez y sobre la MISMA tabla:

1. **cero** filas vencidas de clases purgables quedan;
2. **cero** filas NO vencidas afectadas (las de antes del cutoff siguen intactas);
3. `verify_chain` (de `licensing/audit_events.py`) queda VERDE con todo el dataset adentro;
4. el export de true-up (`licensing/trueup_export.py`) no se lleva ni una fila ajena;
5. (FR-004) las `human_reviews` vencidas tienen `response_text IS NULL` y la fila persiste; las no
   vencidas conservan su texto.

## Qué NO se re-mide acá (para no duplicar lo ya verde)

La MECÁNICA ya tiene sus archivos y no se repite: el portón por forma y la partición del
clasificador viven en `tests/unit/test_retention_classifier.py`; la cadena sana bajo dataset
adversarial, en `tests/integration/test_retencion_dataset_abusivo.py`; el contador de residuo, los
lotes y el `partial`, en `tests/integration/test_retention_purga_residuo.py`; el `response_text` y
el rastro auditable, en `tests/integration/test_retention_purga_rastro.py`; el piso del plazo, en
`tests/integration/test_retention_piso_plazo.py`. Este archivo aserta el ESCENARIO COMPLETO sobre
UN dataset cohesivo, por ID contra la tabla — que es lo que ninguno de esos cubre.

## Verificable «sin conocer la implementación»

Las aserciones son sobre la TABLA por id sembrado (¿sigue esta fila?, ¿desapareció esta otra?) y
sobre el predicado SQL PÚBLICO del quickstart §1 (la forma de `guardian_events`), no sobre las
funciones internas del purgador. La corrida se dispara por su API pública (`run_once`) — el único
acoplamiento es el que el propio SC-001 nombra: `verify_chain` y `trueup_export`.
"""
import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration", _TESTS / "seeds"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402
from seed_retention_dataset import sembrar_dataset_retencion  # noqa: E402

require_postgres()

DB = "sentinel_test_retention_purge"

# El predicado PÚBLICO del quickstart §1 (SQL #1): «la fila la protege el portón por la marca en
# el [0]». Cubre eslabones US5+ y licencias pre-US5. Se usa a mano —no importado del clasificador—
# para que este test verifique por SQL directo, como lo haría un auditor sin el código delante.
SQL_FORMA_CADENA = text("""
    SELECT count(*) FROM audit_logs
    WHERE jsonb_typeof(guardian_events) = 'array'
      AND jsonb_typeof(guardian_events -> 0) = 'object'
      AND (jsonb_exists(guardian_events -> 0, 'seq')
           OR jsonb_exists(guardian_events -> 0, 'prev_hash')
           OR jsonb_exists(guardian_events -> 0, 'event_type'))
""")


# ── Harness ───────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def factory():
    _client, factory, cleanup = build_app_client(DB)
    yield factory
    cleanup()


@pytest.fixture(scope="module")
def escenario(factory, tmp_path_factory):
    """Siembra UNA vez (~200 días) y corre UNA purga REAL. Todos los tests leen ese estado.

    La corrida es REAL (`SENTINEL_PURGE_DRY_RUN=false`) y `run_now=True` (saltea la ventana). El
    `escenario` captura el conteo de filas de forma-cadena ANTES y DESPUÉS, porque «la evidencia no
    se movió» es una igualdad entre esos dos números (quickstart §1, SQL #1).
    """
    from src.licensing import deployment_key
    from src.services.retention import purger

    # Deployment key efímera para el export de true-up (mismo patrón que el dataset abusivo).
    keypath = tmp_path_factory.mktemp("dep_key") / "deployment_key.pem"
    prev = {k: os.environ.get(k) for k in
            ("SENTINEL_PURGE_DRY_RUN", "SENTINEL_PURGE_BATCH_PAUSE_MS", deployment_key.DEPLOYMENT_KEY_ENV)}
    os.environ["SENTINEL_PURGE_DRY_RUN"] = "false"
    os.environ["SENTINEL_PURGE_BATCH_PAUSE_MS"] = "0"
    os.environ[deployment_key.DEPLOYMENT_KEY_ENV] = str(keypath)
    deployment_key.ensure_deployment_key()
    try:
        ds = sembrar_dataset_retencion(factory, dias=200, plazo=90)
        forma_antes = _contar_forma_cadena(factory)
        corrida = purger.run_once(session_factory=factory, run_now=True)
        forma_despues = _contar_forma_cadena(factory)
        yield ds, corrida, forma_antes, forma_despues
    finally:
        for k, v in prev.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# ── Helpers de tabla (sin conocer la implementación del purgador) ─────────────────────


def _ids_vivos(factory):
    from src.models.audit import AuditLog
    db = factory()
    try:
        return {str(fid) for (fid,) in db.query(AuditLog.id).all()}
    finally:
        db.close()


def _contar_forma_cadena(factory):
    db = factory()
    try:
        return db.execute(SQL_FORMA_CADENA).scalar_one()
    finally:
        db.close()


def _leer_review(factory, rid):
    import uuid
    from src.models.compliance import HumanReview
    db = factory()
    try:
        return db.query(HumanReview).filter(HumanReview.id == uuid.UUID(rid)).one()
    finally:
        db.close()


# ── 0. guarda de la semilla: que los asserts de abajo no puedan pasar en vacío ────────


def test_el_dataset_sembrado_no_es_trivial(escenario):
    """Sin filas vencidas, «cero vencidas quedan» pasaría con la tabla intacta y el archivo
    entero mentiría en verde. Se exige que el seed haya puesto vencidas, frescas y cadena."""
    ds, _corrida, _a, _d = escenario
    assert len(ds.vencidas_todas) >= 3, "el seed no puso vencidas: los asserts de SC-001 serían vacíos"
    assert len(ds.frescas_todas) >= 3, "el seed no puso frescas: no habría qué preservar"
    assert len(ds.cadena_us5) == 3 and ds.licencia_pre_us5 and ds.spoof


# ── 1. cero vencidas de clases purgables ──────────────────────────────────────────────


def test_no_queda_ninguna_fila_vencida_de_clase_purgable(escenario, factory):
    """SC-001, mitad A: toda fila sembrada VENCIDA de una clase purgable desapareció de la tabla.

    Se aserta por id sobre `audit_logs`: ninguna de las vencidas sigue viva. Es la promesa RGPD
    literal del día 91 — «los datos que superan su plazo desaparecen solos»."""
    ds, _corrida, _a, _d = escenario
    vivos = _ids_vivos(factory)

    sobrevivientes = [fid for fid in ds.vencidas_todas if fid in vivos]
    assert sobrevivientes == [], (
        f"{len(sobrevivientes)} filas vencidas de clases purgables siguen en audit_logs tras la "
        "corrida real: la retención no se cumplió (SC-001).")


def test_el_spoof_de_licencia_muere_con_su_clase(escenario, factory):
    """El disfraz `model='license'` con `guardian_events=[]` es tráfico y MUERE (dictamen 14-ago).

    Es la fila que la letra anterior mantenía inmortal por el literal `model`. Que muera es la
    prueba de que la exclusión cuelga de la FORMA, no del literal, también en la corrida real."""
    ds, _corrida, _a, _d = escenario
    assert ds.spoof not in _ids_vivos(factory), (
        "el spoof `model='license'` con forma de tráfico sobrevivió: la columna `model` volvió a "
        "comprar inmortalidad (regresión del dictamen del 14-ago).")


# ── 2. cero NO-vencidas afectadas ─────────────────────────────────────────────────────


def test_ninguna_fila_no_vencida_fue_afectada(escenario, factory):
    """SC-001, mitad B: las filas anteriores al cutoff siguen intactas.

    Una purga que borra de MÁS es tan grave como una que no borra: se lleva puesta auditoría que
    todavía tenía que existir. Se aserta que las 15 frescas (5 por clase con filas) siguen todas."""
    ds, _corrida, _a, _d = escenario
    vivos = _ids_vivos(factory)

    faltantes = [fid for fid in ds.frescas_todas if fid not in vivos]
    assert faltantes == [], (
        f"{len(faltantes)} filas NO vencidas desaparecieron: la purga se llevó filas de edad "
        "<= plazo (SC-001).")


# ── 3. la cadena de licencias intacta + verify_chain verde ────────────────────────────


def test_toda_la_evidencia_de_licencias_sobrevivio(escenario, factory):
    """FR-003: eslabones US5+ y la licencia pre-US5 siguen vivos, y el conteo por FORMA no cambió.

    Las dos mitades: (a) por id, cada fila de la cadena protegida sigue; (b) por el SQL público del
    quickstart §1, el conteo de filas de forma-cadena es EXACTAMENTE el mismo antes y después —esa
    igualdad es lo que un auditor verifica sin el código delante—."""
    ds, _corrida, forma_antes, forma_despues = escenario
    vivos = _ids_vivos(factory)

    perdidas = [fid for fid in ds.cadena_protegida if fid not in vivos]
    assert perdidas == [], (
        f"la purga se llevó evidencia de licencias: {perdidas}. Es el incidente de confianza de "
        "FR-003 causado por la defensa (eslabón US5+ o licencia pre-US5).")

    # La licencia pre-US5 es la que el ancla por `seq` habría borrado: la afirmamos aparte.
    assert ds.licencia_pre_us5 in vivos, (
        "la licencia pre-US5 (`event_type` sin `seq`) se purgó: volvió el agujero histórico que "
        "el portón por forma vino a cerrar.")

    assert forma_despues == forma_antes, (
        f"el conteo de filas protegidas por forma cambió ({forma_antes} → {forma_despues}): la "
        "purga tocó la cadena, o la fila resumen se contó como cadena.")


def test_verify_chain_queda_verde_con_todo_el_dataset(escenario, factory):
    """SC-001: `verify_chain` verde tras la corrida, contando SÓLO los eslabones legibles (US5+).

    La pre-US5 no es eslabón legible (`_is_chain_link` pide `seq`+`prev_hash`) y el spoof ya murió,
    así que `checked` es exactamente los 3 eslabones del emisor real — y `ok` sin issues."""
    ds, _corrida, _a, _d = escenario
    from src.licensing.audit_events import verify_chain
    db = factory()
    try:
        reporte = verify_chain(db)
    finally:
        db.close()

    assert reporte["ok"] is True, reporte["issues"]
    assert reporte["issues"] == []
    assert reporte["checked"] == len(ds.cadena_us5), (
        "verify_chain contó otra cantidad de eslabones legibles que los emitidos: adoptó una fila "
        "ajena o perdió un eslabón real.")


# ── 4. el export de true-up no se lleva ni una fila ajena ─────────────────────────────


def test_el_export_de_trueup_no_arrastra_ninguna_fila_ajena(escenario, factory):
    """SC-001: el true-up firmado lleva EXACTAMENTE los eslabones de la cadena y verifica.

    El export es el papel con el que el operador renueva: si arrastrara una fila de tráfico (o le
    faltara un eslabón por una purga que no debía), `verify_export` lo rechaza. Se exige el rango
    exacto de `seq` y que el documento verifique de punta a punta."""
    ds, _corrida, _a, _d = escenario
    from src.licensing import deployment_key, trueup_export

    doc = trueup_export.generate_signed_export(session_factory=factory)

    seqs = [e["seq"] for e in doc["events"]]
    assert seqs == list(range(1, len(ds.cadena_us5) + 1)), (
        f"el export llevó seqs {seqs}: o adoptó una fila ajena o le falta un eslabón tras la purga.")
    assert doc["counter"] == len(ds.cadena_us5)
    assert doc["range"] == {"from_seq": 1, "to_seq": len(ds.cadena_us5)}
    # No levanta ⇒ firma válida, cadena interna contigua y head coherente con el historial.
    trueup_export.verify_export(doc, deployment_key.public_key_pem())


# ── 5. FR-004: el único texto real durable ────────────────────────────────────────────


def test_la_review_vencida_pierde_el_texto_pero_la_fila_persiste(escenario, factory):
    """FR-004, scenario 4: `response_text` vencido → NULL y la revisión persiste como metadata."""
    ds, _corrida, _a, _d = escenario
    rv = _leer_review(factory, ds.review_vencida)

    assert rv.response_text is None, "el texto de la revisión vencida tiene que morir (FR-004)"
    assert rv.reviewer_id == "dpo-018", "la fila persiste: quién revisó"
    assert rv.action == "approved", "la fila persiste: el veredicto"
    assert rv.created_at is not None


def test_la_review_no_vencida_conserva_su_texto(escenario, factory):
    """La otra cara de FR-004: el contenido dentro de plazo NO se toca."""
    ds, _corrida, _a, _d = escenario
    from seed_retention_dataset import TEXTO_REVISION_FRESCA

    rf = _leer_review(factory, ds.review_fresca)
    assert rf.response_text == TEXTO_REVISION_FRESCA, "el texto no vencido no se toca"
