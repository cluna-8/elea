"""FR-004 (T009) + FR-005 (T010): la muerte del único texto real y el rastro auditable.

Contra Postgres REAL (no el gemelo Python): lo que se afirma es el efecto en la tabla tras una
corrida, que es lo único que un auditor puede ver.

## Qué mide cada mitad

**T009 — el único texto real durable muere (FR-004).** `audit_logs` es metadata-only por diseño,
así que el plazo de `prompt_content` no muerde ahí: muerde en `human_reviews.response_text`
(`models/compliance.py:84`). Al vencer, el texto pasa a NULL y la fila de revisión PERSISTE como
metadata (quién revisó, cuándo, veredicto). Se mide: (a) el texto vencido quedó NULL de verdad en
la DB; (b) el no vencido no se tocó; (c) la fila de review sigue con su metadata; (d) el simulacro
NO anula pero SÍ cuenta; (e) los lotes.

**Criterio de edad — decisión documentada (ambigüedad de spec).** Ni `spec.md` FR-004 (scenario 4)
ni `data-model.md:53` nombran `created_at` vs `reviewed_at`. Se eligió `created_at` por el lado
conservador para privacidad: es el timestamp más TEMPRANO (`created_at <= reviewed_at`), así que el
contenido muere antes, y no es nullable —`reviewed_at` sí—, así que una revisión abierta que nunca
se cerró igual pierde su texto en vez de vivir para siempre. `test_la_edad_sale_de_created_at…` y
`test_una_revision_abierta…` clavan esa decisión: si alguien la invierte a `reviewed_at`, se ponen
rojos con el motivo escrito.

**T010 — la purga es auditable (FR-005/SC-002).** Cada corrida REAL deja dos rastros metadata-only:
una entrada por clase en su `retention_policies.purge_log` (capada a 50) y UNA fila resumen por
corrida en `audit_logs` clase `config_audit`. El simulacro NO escribe (no toma locks de escritura).
Security Constraint 1: el rastro JAMÁS reintroduce el contenido purgado — `test_la_fila_resumen_es_
metadata_only` lo verdugo con un texto centinela.
"""
import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent.parent
for _dir in (_TESTS, _TESTS / "integration"):
    if str(_dir) not in sys.path:
        sys.path.insert(0, str(_dir))

from migration_harness import require_postgres  # noqa: E402
from seat_gate_harness import build_app_client  # noqa: E402

require_postgres()

DB = "basa_test_retencion_rastro"

# Plazos del seed 004 (a mano, con el mismo criterio del resto de la suite: si el seed cambia,
# esto se pone rojo y lo explica en vez de seguirlo en silencio).
PLAZO_PROMPT = 90    # prompt_content → muerde sobre human_reviews.response_text
VIEJA = PLAZO_PROMPT + 30     # 120 d: vencida para prompt_content
FRESCA = 5                    # 5 d: no vencida para nadie
MUY_VIEJA = 800               # vencida para las cuatro clases

# audit_logs, una por clase con filas (prompt_content no aparece: su predicado sobre audit_logs
# es vacío por diseño). Sirven para ver las entradas de purge_log de las otras clases.
USO_VIEJA = ("uso_vieja", "ollama-qwen3-4b", "passed", [], MUY_VIEJA)
SEG_VIEJA = ("seg_vieja", "claude-3-5-sonnet-20241022", "blocked_secret", [], MUY_VIEJA)
CONFIG_VIEJA = ("config_vieja", "gpt-4o", "config_change_nlp_fail_mode", [], MUY_VIEJA)


# ── Harness ───────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def factory():
    _client, factory, cleanup = build_app_client(DB)
    yield factory
    cleanup()


@pytest.fixture(autouse=True)
def caja_en_cero(factory):
    """`audit_logs` y `human_reviews` vacías antes de cada test. Las políticas del seed quedan
    intactas (este archivo no rompe plazos: eso es el archivo del piso)."""
    from src.models.audit import AuditLog
    from src.models.compliance import HumanReview
    db = factory()
    try:
        db.query(AuditLog).delete()
        db.query(HumanReview).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def corrida_real(monkeypatch):
    """Corrida que BORRA/ANULA/ESCRIBE: `BASA_PURGE_DRY_RUN=false` explícito (el default es el
    simulacro)."""
    monkeypatch.setenv("BASA_PURGE_DRY_RUN", "false")
    monkeypatch.setenv("BASA_PURGE_BATCH_PAUSE_MS", "0")


def sembrar_audit(factory, filas):
    from src.models.audit import AuditLog
    from src.models.tenant import DEFAULT_TENANT_ID
    ahora = datetime.utcnow()
    db = factory()
    try:
        marcas = {}
        for marca, modelo, estado, eventos, edad in filas:
            fid = uuid.uuid4()
            db.add(AuditLog(
                id=fid, tenant_id=DEFAULT_TENANT_ID,
                timestamp=ahora - timedelta(days=edad), model=modelo,
                prompt_tokens=0, completion_tokens=0, cost_usd=0,
                pii_detected=False, compliance_status=estado, latency_ms=7,
                guardian_events=eventos,
            ))
            marcas[marca] = str(fid)
        db.commit()
        return marcas
    finally:
        db.close()


def sembrar_review(factory, *, edad_dias, texto="contenido sensible del sujeto",
                   reviewer="dpo-1", accion="approved", edad_reviewed=None):
    """Una `human_review` con `created_at` a `edad_dias` de antigüedad y su `response_text`.

    `edad_reviewed=None` deja `reviewed_at` en NULL (revisión abierta). Devuelve el id (str).
    """
    from src.models.compliance import HumanReview
    from src.models.tenant import DEFAULT_TENANT_ID
    ahora = datetime.utcnow()
    db = factory()
    try:
        rid = uuid.uuid4()
        reviewed = None
        if edad_reviewed is not None:
            reviewed = (ahora - timedelta(days=edad_reviewed)).isoformat()
        db.add(HumanReview(
            id=rid, tenant_id=DEFAULT_TENANT_ID, review_token=uuid.uuid4(),
            reviewer_id=reviewer, action=accion, reviewed_at=reviewed,
            created_at=(ahora - timedelta(days=edad_dias)).isoformat(),
            response_text=texto,
        ))
        db.commit()
        return str(rid)
    finally:
        db.close()


def leer_review(factory, rid):
    from src.models.compliance import HumanReview
    db = factory()
    try:
        return db.query(HumanReview).filter(HumanReview.id == uuid.UUID(rid)).one()
    finally:
        db.close()


def por_clase(corrida):
    return {r.clase: r for r in corrida.clases}


# ── T009 · el único texto real durable muere ──────────────────────────────────────────


def test_la_corrida_real_anula_el_texto_vencido_y_conserva_la_fila(factory, corrida_real):
    """(a) el texto vencido quedó NULL de verdad; (b) el fresco intacto; (c) la fila persiste."""
    from src.services.retention import purger

    vieja = sembrar_review(factory, edad_dias=VIEJA, texto="prompt clínico del paciente",
                           reviewer="dpo-7", accion="approved")
    fresca = sembrar_review(factory, edad_dias=FRESCA, texto="revisión reciente")

    corrida = purger.run_once(session_factory=factory, run_now=True)

    rv = leer_review(factory, vieja)
    assert rv.response_text is None, "el texto vencido tiene que morir (FR-004)"
    # La fila PERSISTE como metadata: quién revisó, veredicto, cuándo.
    assert rv.reviewer_id == "dpo-7"
    assert rv.action == "approved"
    assert rv.created_at is not None

    rf = leer_review(factory, fresca)
    assert rf.response_text == "revisión reciente", "el texto no vencido no se toca"

    pc = por_clase(corrida)["prompt_content"]
    assert pc.result == purger.RESULTADO_OK
    assert pc.cutoff is not None
    assert pc.rows_deleted == 1, "una sola revisión vencida con texto"


def test_el_simulacro_no_anula_ningun_texto_pero_lo_cuenta(factory, monkeypatch):
    """El ensayo que el DPO firma: reporta cuántas se anularían y NO anula ninguna."""
    from src.services.retention import purger

    monkeypatch.setenv("BASA_PURGE_DRY_RUN", "true")
    vieja = sembrar_review(factory, edad_dias=VIEJA, texto="secreto que sobrevive al ensayo")

    corrida = purger.run_once(session_factory=factory, run_now=True)

    assert leer_review(factory, vieja).response_text == "secreto que sobrevive al ensayo", (
        "el simulacro NO anula: cero UPDATE")
    pc = por_clase(corrida)["prompt_content"]
    assert pc.dry_run is True
    assert pc.rows_deleted == 1, "pero SÍ cuenta lo que se anularía, para que el DPO lo vea antes"


def test_la_edad_sale_de_created_at_no_de_reviewed_at(factory, corrida_real):
    """Decisión documentada: la edad se mide contra `created_at` (el más temprano, conservador).

    `created_at` vencido (120 d) y `reviewed_at` FRESCO (1 d): si la edad saliera de `reviewed_at`
    el texto sobreviviría. Muere → prueba que decide `created_at`. Si alguien invierte la decisión,
    este test es el que hay que voltear con el motivo escrito.
    """
    from src.services.retention import purger

    rid = sembrar_review(factory, edad_dias=VIEJA, edad_reviewed=1, texto="contenido")
    purger.run_once(session_factory=factory, run_now=True)

    rv = leer_review(factory, rid)
    assert rv.response_text is None, (
        "created_at vencido manda: un reviewed_at reciente no indulta el contenido")
    assert rv.reviewed_at is not None, "la fila persiste con su metadata de revisión"


def test_una_revision_abierta_y_vieja_igual_pierde_el_texto(factory, corrida_real):
    """`reviewed_at` NULL (nunca se cerró) + `created_at` viejo → el texto muere igual.

    Es la otra cara de la misma decisión: atar la muerte del contenido a que alguien apretara
    «revisado» dejaría el texto de una revisión abierta vivo para siempre — el modo de falla que
    la 018 vino a cerrar.
    """
    from src.services.retention import purger

    rid = sembrar_review(factory, edad_dias=VIEJA, edad_reviewed=None, accion=None,
                         texto="abierta y vieja")
    purger.run_once(session_factory=factory, run_now=True)

    rv = leer_review(factory, rid)
    assert rv.response_text is None
    assert rv.reviewed_at is None, "sigue abierta; sólo murió el texto, la fila persiste"


def test_prompt_content_anula_por_lotes(factory, monkeypatch):
    """Mismos lotes que el DELETE de audit_logs: 5 revisiones vencidas en lotes de 2 → 3 lotes."""
    from src.services.retention import purger

    monkeypatch.setenv("BASA_PURGE_DRY_RUN", "false")
    monkeypatch.setenv("BASA_PURGE_BATCH_PAUSE_MS", "0")
    monkeypatch.setenv("BASA_PURGE_BATCH_SIZE", "2")

    ids = [sembrar_review(factory, edad_dias=VIEJA, texto=f"t{i}") for i in range(5)]

    corrida = purger.run_once(session_factory=factory, run_now=True)

    pc = por_clase(corrida)["prompt_content"]
    assert pc.rows_deleted == 5
    assert pc.batches == 3, "5 filas en lotes de 2 → 2+2+1 = 3 lotes"
    for rid in ids:
        assert leer_review(factory, rid).response_text is None


# ── T010 · la purga es auditable ──────────────────────────────────────────────────────


def test_la_corrida_real_deja_entrada_en_purge_log(factory, corrida_real):
    """Cada clase gana UNA entrada de esta corrida en su `retention_policies.purge_log`."""
    from src.models.compliance import RetentionPolicy
    from src.services.retention import purger

    sembrar_audit(factory, [USO_VIEJA, SEG_VIEJA, CONFIG_VIEJA])
    sembrar_review(factory, edad_dias=VIEJA, texto="x")

    corrida = purger.run_once(session_factory=factory, run_now=True)

    db = factory()
    try:
        logs = {p.log_type: list(p.purge_log or []) for p in db.query(RetentionPolicy).all()}
    finally:
        db.close()

    esperado = por_clase(corrida)
    for clase in purger.classifier.clases():
        entradas = [e for e in logs[clase] if e.get("run_id") == corrida.run_id]
        assert len(entradas) == 1, f"{clase} no dejó exactamente una entrada de esta corrida"
        e = entradas[0]
        assert e["clase"] == clase
        assert e["dry_run"] is False
        assert e["result"] in (purger.RESULTADO_OK, purger.RESULTADO_PARCIAL,
                               purger.RESULTADO_ERROR)
        # la entrada NO miente sobre lo que devolvió la corrida
        assert e["rows_deleted"] == esperado[clase].rows_deleted
        for campo in ("started_at", "finished_at", "cutoff", "batches", "window"):
            assert campo in e, f"falta {campo} en la entrada de {clase}"


def test_existe_la_fila_resumen_config_audit(factory, corrida_real):
    """UNA fila resumen por corrida, clasificada `config_audit` (730 d), con los campos de la
    corrida en metadata."""
    from src.models.audit import AuditLog
    from src.services.retention import classifier, purger

    sembrar_audit(factory, [USO_VIEJA])
    corrida = purger.run_once(session_factory=factory, run_now=True)

    db = factory()
    try:
        filas = (db.query(AuditLog)
                 .filter(AuditLog.compliance_status == purger.COMPLIANCE_RESUMEN_PURGA).all())
        assert len(filas) == 1, "una fila resumen por corrida"
        fila = filas[0]
        # Se clasifica config_audit (730 d), no usage_metadata (365) — el literal config_change.
        assert classifier.clase_de(fila) == classifier.CLASE_CONFIG_AUDIT
        # NO es un eslabón de la cadena: el lector único (chained_entries) sólo lee model='license'.
        assert fila.model != "license"
        blob = fila.guardian_events[0]
        assert blob["kind"] == purger.RESUMEN_KIND
        assert blob["run_id"] == corrida.run_id
        assert blob["dry_run"] is False
        # El residuo es POR CORRIDA y vive acá (no en las entradas por clase).
        assert "filas_no_clasificadas" in blob
        assert len(blob["clases"]) == len(corrida.clases)
    finally:
        db.close()


def test_el_simulacro_no_deja_rastro_en_tabla(factory, monkeypatch):
    """`simulacro no escribe`: ni fila resumen ni entrada de purge_log de esta corrida."""
    from src.models.audit import AuditLog
    from src.models.compliance import RetentionPolicy
    from src.services.retention import purger

    monkeypatch.setenv("BASA_PURGE_DRY_RUN", "true")
    sembrar_audit(factory, [USO_VIEJA])
    sembrar_review(factory, edad_dias=VIEJA, texto="x")

    corrida = purger.run_once(session_factory=factory, run_now=True)
    assert corrida.dry_run is True

    db = factory()
    try:
        resumenes = (db.query(AuditLog)
                     .filter(AuditLog.compliance_status == purger.COMPLIANCE_RESUMEN_PURGA)
                     .count())
        assert resumenes == 0, "el simulacro no escribe la fila resumen config_audit"
        logs = [list(p.purge_log or []) for p in db.query(RetentionPolicy).all()]
        for entradas in logs:
            assert not any(e.get("run_id") == corrida.run_id for e in entradas), (
                "el simulacro no escribe purge_log")
    finally:
        db.close()


def test_el_purge_log_se_capa_a_las_ultimas_50(factory, corrida_real):
    """Sin tope, el registro de una instalación vieja crece sin límite dentro de una fila."""
    from src.models.compliance import RetentionPolicy
    from src.services.retention import purger

    db = factory()
    try:
        pol = (db.query(RetentionPolicy)
               .filter(RetentionPolicy.log_type == "usage_metadata").one())
        pol.purge_log = [{"run_id": f"viejo-{i}", "clase": "usage_metadata"}
                         for i in range(purger.PURGE_LOG_MAX)]
        db.commit()
    finally:
        db.close()

    corrida = purger.run_once(session_factory=factory, run_now=True)

    db = factory()
    try:
        pol = (db.query(RetentionPolicy)
               .filter(RetentionPolicy.log_type == "usage_metadata").one())
        log = list(pol.purge_log)
    finally:
        db.close()

    assert len(log) == purger.PURGE_LOG_MAX, "capado a las últimas 50 corridas por clase"
    assert log[-1]["run_id"] == corrida.run_id, "la corrida nueva quedó al final"
    assert log[0]["run_id"] == "viejo-1", "la más vieja (viejo-0) se cayó del tope"


def test_la_fila_resumen_es_metadata_only(factory, corrida_real):
    """Security Constraint 1 — verdugo: el rastro JAMÁS reintroduce el contenido purgado."""
    from src.models.audit import AuditLog
    from src.services.retention import purger

    sembrar_audit(factory, [USO_VIEJA])
    sembrar_review(factory, edad_dias=VIEJA, texto="TEXTO-SECRETO-QUE-NO-DEBE-APARECER")

    corrida = purger.run_once(session_factory=factory, run_now=True)
    assert por_clase(corrida)["prompt_content"].rows_deleted == 1  # de verdad se anuló algo

    db = factory()
    try:
        fila = (db.query(AuditLog)
                .filter(AuditLog.compliance_status == purger.COMPLIANCE_RESUMEN_PURGA).one())
        serial = json.dumps(fila.guardian_events)
    finally:
        db.close()

    assert "SECRETO" not in serial, "el rastro no puede reintroducir el contenido que borró"

    def _claves(o):
        out = set()
        if isinstance(o, dict):
            out |= set(o.keys())
            for v in o.values():
                out |= _claves(v)
        elif isinstance(o, list):
            for v in o:
                out |= _claves(v)
        return out

    prohibidos = {"response_text", "prompt", "prompt_content", "content",
                  "subject_identifier", "user_email", "masked_entities"}
    assert not (_claves(fila.guardian_events) & prohibidos), (
        "ningún campo de contenido ni de sujeto en el rastro")
