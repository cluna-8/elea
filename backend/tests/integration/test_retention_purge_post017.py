"""SC-004: la purga sigue enforced en el mundo post-017 (spec 018, T014).

Todo corre bajo el harness `mundo_post017` (`tests/post017_harness.py`): la policy
`tenant_isolation_bootstrap` DROPEADA y la conexión con un rol de aplicación NOSUPERUSER, SIN
BYPASSRLS y sin propiedad sobre las tablas — el mundo que la 017 activa cuando cablee la identidad
por request. Es el ÚNICO mundo donde el bug de FR-006 es visible: con la ventana bootstrap abierta
(el estado de `main` hoy) una sesión pelada escribe y borra igual, y este test pasaría sin probar
nada.

## Qué prueba, y por qué el harness le da sentido

El purgador declara su identidad con `tenant_context(None, bypass=True)` y abre/cierra la sesión
DENTRO del bloque (el bypass viaja en un `SET LOCAL` que muere con la transacción). Este archivo
verifica que ese contrato ALCANZA: sembrando con el `session_factory` del mundo post-017 (que trae
el listener del GUC, como `SessionLocal`), `run_once` purga correctamente aunque el rol de DB no
tenga BYPASSRLS. Si la RLS bloqueara el `DELETE` —el modo de falla que la 018 vino a cerrar: un
purgador que pasa de borrar a NO VER FILAS en silencio—, las vencidas sobrevivirían y el test lo
caza.

El escenario es el MISMO dataset de T013 que usa T012 (SC-001) — a propósito: SC-004 es «el
SC-001 bajo RLS cerrada», así que compartir la siembra es lo que hace comparable el resultado
entre los dos mundos. Lo que este archivo NO re-mide es que el harness MUERDA (rol sin bypass,
bootstrap cerrada en todas las tablas): eso lo clava `test_identidad_batch_post017.py` sobre su
propia DB. Acá se conserva sólo el CANARIO de RLS —una sesión pelada no ve las filas— porque corre
sobre la DB de ESTE módulo y es lo que le da los dientes al resto de las aserciones.
"""
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration", _TESTS / "seeds"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from post017_harness import mundo_post017  # noqa: E402,F401 — fixture (scope de módulo)
from seed_retention_dataset import TEXTO_REVISION_FRESCA, sembrar_dataset_retencion  # noqa: E402

require_postgres()


# ── Escenario: sembrar + purgar UNA vez bajo el mundo post-017 ────────────────────────


@pytest.fixture(scope="module")
def escenario(mundo_post017, monkeypatch_module):
    """Siembra ~200 días con el `session_factory` del mundo post-017 y corre UNA purga REAL.

    La corrida REAL (`BASA_PURGE_DRY_RUN=false`, `run_now=True`) va contra el rol de app sin
    BYPASSRLS: si el `tenant_context(None, bypass=True)` del purgador no funcionara por GUC, el
    `DELETE` no vería sus filas y nada moriría."""
    from src.services.retention import purger

    monkeypatch_module.setenv("BASA_PURGE_DRY_RUN", "false")
    monkeypatch_module.setenv("BASA_PURGE_BATCH_PAUSE_MS", "0")

    ds = sembrar_dataset_retencion(mundo_post017.session_factory, dias=200, plazo=90)
    corrida = purger.run_once(session_factory=mundo_post017.session_factory, run_now=True)
    return ds, corrida


@pytest.fixture(scope="module")
def monkeypatch_module():
    """`monkeypatch` con scope de módulo: el escenario es de módulo y `monkeypatch` es de función.

    Mismo truco que usa el resto de la suite cuando un fixture caro de módulo necesita env."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    yield mp
    mp.undo()


# ── Helpers de lectura: SIEMPRE bajo identidad declarada (si no, la RLS devuelve 0 filas) ──


def _ids_vivos(mundo):
    from src.database import tenant_context
    from src.models.audit import AuditLog
    with tenant_context(None, bypass=True):
        db = mundo.session_factory()
        try:
            return {str(fid) for (fid,) in db.query(AuditLog.id).all()}
        finally:
            db.close()


def _leer_review(mundo, rid):
    import uuid
    from src.database import tenant_context
    from src.models.compliance import HumanReview
    with tenant_context(None, bypass=True):
        db = mundo.session_factory()
        try:
            return db.query(HumanReview).filter(HumanReview.id == uuid.UUID(rid)).one()
        finally:
            db.close()


# ── El canario: el mundo de VERDAD está cerrado para ESTA DB ──────────────────────────


def test_una_sesion_sin_identidad_no_ve_el_dataset(escenario, mundo_post017):
    """El canario que le da sentido al resto: bajo RLS cerrada, una sesión pelada ve CERO filas.

    Si esto afloja —porque el mundo se aguó o la RLS dejó de aplicar—, los tests de abajo pasarían
    con el bug adentro (un `DELETE` que funciona porque no hay RLS, no porque el bypass funcione).
    Bajo identidad declarada, en cambio, el dataset está entero: la diferencia entre los dos es
    exactamente lo que este archivo mide."""
    from src.models.audit import AuditLog

    db = mundo_post017.session_factory()
    try:
        assert db.query(AuditLog).count() == 0, (
            "una sesión sin GUC vio filas: el mundo no está cerrado y este archivo no prueba nada")
    finally:
        db.close()

    assert _ids_vivos(mundo_post017), "bajo identidad declarada el dataset tiene que estar entero"


# ── SC-004: la purga hizo su trabajo aunque el rol no tenga BYPASSRLS ──────────────────


def test_las_vencidas_purgables_murieron_bajo_rls_cerrada(escenario, mundo_post017):
    """El corazón de SC-004: `run_once` borró las vencidas vía GUC, con el rol app sin bypass.

    Si la RLS hubiera bloqueado el `DELETE`, estas filas seguirían vivas — retención que aparenta
    estar enforced sin estarlo, el peor modo de falla de la spec."""
    ds, _corrida = escenario
    assert len(ds.vencidas_todas) >= 3, "el seed no puso vencidas: este assert sería vacío"
    vivos = _ids_vivos(mundo_post017)

    sobrevivientes = [fid for fid in ds.vencidas_todas if fid in vivos]
    assert sobrevivientes == [], (
        f"{len(sobrevivientes)} vencidas sobrevivieron bajo el mundo post-017: el "
        "`tenant_context(None, bypass=True)` del purgador no llegó al `DELETE` por GUC (FR-006).")
    assert ds.spoof not in vivos, "el spoof `model='license'` también tiene que morir bajo RLS cerrada"


def test_las_no_vencidas_y_la_cadena_sobreviven(escenario, mundo_post017):
    """La purga bajo RLS cerrada no borra de más: frescas y evidencia de licencias intactas."""
    ds, _corrida = escenario
    vivos = _ids_vivos(mundo_post017)

    faltantes = [fid for fid in ds.frescas_todas if fid not in vivos]
    assert faltantes == [], f"{len(faltantes)} filas no vencidas desaparecieron bajo RLS cerrada"

    perdidas = [fid for fid in ds.cadena_protegida if fid not in vivos]
    assert perdidas == [], f"la purga se llevó evidencia de licencias bajo RLS cerrada: {perdidas}"


def test_verify_chain_verde_bajo_rls_cerrada(escenario, mundo_post017):
    """`verify_chain` (leído bajo identidad declarada) sigue verde tras la purga post-017."""
    ds, _corrida = escenario
    from src.database import tenant_context
    from src.licensing.audit_events import verify_chain

    with tenant_context(None, bypass=True):
        db = mundo_post017.session_factory()
        try:
            reporte = verify_chain(db)
        finally:
            db.close()

    assert reporte["ok"] is True, reporte["issues"]
    assert reporte["checked"] == len(ds.cadena_us5)


def test_fr004_bajo_rls_cerrada(escenario, mundo_post017):
    """FR-004 bajo el mundo post-017: el texto vencido murió (UPDATE vía GUC) y el fresco no."""
    ds, _corrida = escenario

    rv = _leer_review(mundo_post017, ds.review_vencida)
    assert rv.response_text is None, "el `UPDATE ... SET response_text=NULL` no llegó bajo RLS cerrada"
    assert rv.reviewer_id == "dpo-018", "la fila de revisión persiste como metadata"

    rf = _leer_review(mundo_post017, ds.review_fresca)
    assert rf.response_text == TEXTO_REVISION_FRESCA, "el texto no vencido no se toca"
