"""Seed REUTILIZABLE del dataset de retención de la 018 (T013).

Lo consumen T012 (`tests/integration/test_retention_purge.py`, SC-001), T014
(`tests/integration/test_retention_purge_post017.py`, SC-004) y el quickstart §1. Vive acá —y no
inline en cada test— porque el escenario SC-001 tiene que ser el MISMO en el mundo con la ventana
bootstrap abierta (T012) y en el mundo post-017 (T014): dos siembras distintas medirían dos
cosas distintas y la comparación entre worlds dejaría de valer.

## Qué siembra, y por qué cada pieza

Un dataset de ~`dias` días (200 por default) repartido en las clases de retención del
CLASIFICADOR REAL (`services/retention/classifier.py`) — la forma de cada clase NO se inventa
acá: se pregunta con `classifier.clase_de()` y se asserta en `_estado_representativo`, así que un
cambio en el mapeo del clasificador pone rojo el seed en vez de sembrar en la clase equivocada en
silencio. Las piezas:

* **filas VENCIDAS de clases purgables** (más viejas que el plazo) — tienen que MORIR en la
  corrida. Una por bucket en cada clase de `audit_logs` con filas (`usage_metadata`,
  `security_events`, `config_audit`; `prompt_content` no tiene filas en `audit_logs` por diseño,
  se cubre por `human_reviews`);
* **filas NO vencidas** (más nuevas que el plazo) — tienen que SOBREVIVIR intactas;
* **la cadena de licencias en sus TRES formas** (Contrato 1 / quickstart §1):
    1. eslabón US5+ — emitido por el emisor REAL (`emit_license_event`), trae `seq`+`prev_hash`+
       `event_type`. **Sobrevive** (FR-003);
    2. licencia pre-US5 — `event_type` SIN `seq` (ventana 16→20-jul-2026), sembrada a mano porque
       el emisor de hoy ya no la produce. **Sobrevive** (portón por `event_type`), aunque su
       `compliance_status` sea mortal: es exactamente el agujero histórico que el ancla por `seq`
       habría borrado;
    3. spoof — `model='license'` con `guardian_events=[]` (tráfico disfrazado). **MUERE** con su
       clase: desde el dictamen del 14-ago el literal `model` no le compra inmortalidad.
  Las tres van ENVEJECIDAS por debajo del cutoff a propósito: si la exclusión por forma se
  rompiera, las dos legítimas caerían en una clase mortal y la corrida se las llevaría — y ese es
  justo el incidente de FR-003 que T012 caza;
* **`human_reviews` con `response_text`** (FR-004): una vencida (el texto tiene que quedar `NULL`
  y la fila persistir) y una fresca (el texto se conserva).

## Parametrización (nº de días, plazo)

`dias` fija el ancho del dataset; `plazo` es el cutoff que se aplica a TODAS las clases. El seed
ESCRIBE `plazo` en las cuatro filas de `retention_policies` (por DB directa, no por el endpoint):
con los plazos de fábrica (90/365/365/730) un dataset de 200 días no tendría NINGUNA fila vencida
de `usage_metadata`/`security_events`/`config_audit`, y la purga de esas clases se probaría en
vacío. Homologar el plazo es lo que hace que el span de 200 días ejercite las cuatro clases con
vencidas y no-vencidas reales. Lo que se prueba —vencida muere, no-vencida sobrevive— no depende
de que el plazo sea el de fábrica.

## Identidad bajo RLS (FR-006, para que sirva en el mundo post-017)

Todo el trabajo de DB va DENTRO de `with tenant_context(None, bypass=True):` con la sesión abierta
y cerrada ahí adentro (mismo contrato que el purgador y el emisor de la cadena). En el mundo
normal (bootstrap viva) el bypass es inocuo; en el mundo post-017 (T014) es lo único que deja
sembrar y purgar bajo el rol de app sin BYPASSRLS. Por eso el seed recibe un `session_factory` y
funciona igual con el del harness normal (`seat_gate_harness.build_app_client`) y con el del
`mundo_post017` (que trae el listener del GUC).
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List

# Defaults del encargo: ~200 días de datos, cutoff homologado a 90 días.
DIAS_DEFAULT = 200
PLAZO_DEFAULT = 90
FILAS_POR_BUCKET_DEFAULT = 5

# `compliance_status` representativo de cada clase de `audit_logs` con filas. NO es la fuente de
# verdad de la clasificación —esa es el clasificador— sino un EXEMPLAR que `_estado_representativo`
# verifica contra `classifier.clase_de()` en tiempo de siembra. Se elige uno de bloqueo para
# `security_events` (el caso grave) y `config_change_*` para `config_audit` (730 d, el más largo).
_EXEMPLAR_POR_CLASE = {
    "usage_metadata": "passed",
    "security_events": "blocked_secret",
    "config_audit": "config_change_nlp_fail_mode",
}

# Textos centinela de las revisiones (FR-004). El vencido tiene un token reconocible para que un
# test de metadata-only lo pueda buscar en el rastro si quisiera.
TEXTO_REVISION_VENCIDA = "contenido sensible del sujeto (VENCIDO-018)"
TEXTO_REVISION_FRESCA = "revisión reciente que sobrevive"


@dataclass
class DatasetRetencion:
    """Lo sembrado, agrupado por EXPECTATIVA — para que los tests aserten sobre la tabla por id,
    sin conocer la implementación del purgador."""

    plazo: int
    dias: int
    # audit_logs, por clase → ids (str). `vencidas`: más viejas que el plazo, tienen que MORIR.
    # `frescas`: más nuevas, tienen que SOBREVIVIR.
    vencidas: Dict[str, List[str]] = field(default_factory=dict)
    frescas: Dict[str, List[str]] = field(default_factory=dict)
    # La cadena que SOBREVIVE (FR-003): eslabones US5+ (por el emisor real) y la licencia pre-US5.
    cadena_us5: List[str] = field(default_factory=list)
    licencia_pre_us5: str = ""
    # El spoof que MUERE (`model='license'` con forma de tráfico).
    spoof: str = ""
    # human_reviews (FR-004): la vencida pierde el texto, la fresca lo conserva.
    review_vencida: str = ""
    review_fresca: str = ""

    @property
    def vencidas_todas(self) -> List[str]:
        return [fid for ids in self.vencidas.values() for fid in ids]

    @property
    def frescas_todas(self) -> List[str]:
        return [fid for ids in self.frescas.values() for fid in ids]

    @property
    def cadena_protegida(self) -> List[str]:
        """Todo lo que la purga NO puede tocar jamás: eslabones US5+ + licencia pre-US5."""
        return list(self.cadena_us5) + [self.licencia_pre_us5]


def _estado_representativo(clase: str) -> str:
    """El `compliance_status` exemplar de `clase`, VERIFICADO contra el clasificador real.

    Es la mitad «usá el classifier real para saber qué forma tiene cada clase» del encargo: si el
    mapeo cambiara y una fila con este estado dejara de caer en `clase`, el seed se cae acá con el
    motivo, en vez de sembrar en la clase equivocada."""
    from src.models.audit import AuditLog
    from src.services.retention import classifier

    estado = _EXEMPLAR_POR_CLASE[clase]
    # Fila en memoria con la forma de tráfico (lista vacía = el caso mayoritario del producto).
    sonda = AuditLog(compliance_status=estado, guardian_events=[])
    real = classifier.clase_de(sonda)
    assert real == clase, (
        f"el exemplar {estado!r} ya no clasifica como {clase!r} sino como {real!r}: el "
        "clasificador cambió su mapeo y el seed sembraría en la clase equivocada. Ajustá "
        "`_EXEMPLAR_POR_CLASE`, no este assert.")
    return estado


def _edades_vencidas(plazo: int, dias: int, n: int) -> List[int]:
    """`n` edades (en días) repartidas entre `plazo+10` y `dias-5`: todas vencidas, escalonadas."""
    lo, hi = plazo + 10, dias - 5
    if n <= 1:
        return [(lo + hi) // 2]
    paso = (hi - lo) / (n - 1)
    return [round(lo + i * paso) for i in range(n)]


def _edades_frescas(plazo: int, n: int) -> List[int]:
    """`n` edades entre 3 y `plazo-10`: todas por debajo del cutoff, tienen que sobrevivir."""
    lo, hi = 3, plazo - 10
    if n <= 1:
        return [(lo + hi) // 2]
    paso = (hi - lo) / (n - 1)
    return [round(lo + i * paso) for i in range(n)]


def sembrar_dataset_retencion(
    session_factory,
    *,
    dias: int = DIAS_DEFAULT,
    plazo: int = PLAZO_DEFAULT,
    filas_por_bucket: int = FILAS_POR_BUCKET_DEFAULT,
    reset: bool = True,
) -> DatasetRetencion:
    """Siembra el dataset SC-001 con `session_factory` y devuelve un `DatasetRetencion`.

    `reset=True` deja `audit_logs`, `human_reviews` y `license_runtime_state` en cero antes de
    sembrar: es lo que hace que el eslabón real arranque en `seq=1` y que los conteos del test
    sean exactos y no «al menos». La corrida de purga la dispara el TEST, no el seed.
    """
    assert dias >= plazo + 20, f"el span ({dias} d) tiene que dejar lugar para vencidas: dias >= plazo+20"
    assert plazo >= 20, f"plazo={plazo} deja sin lugar a las frescas (necesita plazo >= 20)"

    from src.database import tenant_context
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event
    from src.models.audit import AuditLog
    from src.models.compliance import HumanReview, RetentionPolicy
    from src.models.license_state import LicenseRuntimeState
    from src.models.tenant import DEFAULT_TENANT_ID
    from src.services.retention import classifier

    ds = DatasetRetencion(plazo=plazo, dias=dias)
    ahora = datetime.utcnow()

    def _fila_audit(db, *, estado, eventos, edad, model="synthetic-018"):
        fid = uuid.uuid4()
        db.add(AuditLog(
            id=fid, tenant_id=DEFAULT_TENANT_ID,
            timestamp=ahora - timedelta(days=edad), model=model,
            prompt_tokens=0, completion_tokens=0, cost_usd=0,
            pii_detected=False, compliance_status=estado, latency_ms=7,
            guardian_events=eventos,
        ))
        return str(fid)

    # La sesión se abre y se cierra DENTRO del bloque: el bypass viaja en un `SET LOCAL` que muere
    # con la transacción, no con el `with` (idéntico contrato al del purgador y el emisor).
    with tenant_context(None, bypass=True):
        db = session_factory()
        try:
            if reset:
                db.query(HumanReview).delete()
                db.query(AuditLog).delete()
                db.query(LicenseRuntimeState).delete()
                db.commit()

            # Cutoff homologado: `plazo` en las cuatro clases (por DB directa; ver docstring).
            for pol in db.query(RetentionPolicy).all():
                pol.retention_days = plazo
            db.commit()

            # ── audit_logs: vencidas + frescas por clase con filas ──
            clases_con_filas = [c for c in classifier.clases()
                                if c not in classifier.CLASES_SIN_FILAS_EN_AUDIT_LOGS]
            for clase in clases_con_filas:
                estado = _estado_representativo(clase)
                ds.vencidas[clase] = [
                    _fila_audit(db, estado=estado, eventos=[], edad=e)
                    for e in _edades_vencidas(plazo, dias, filas_por_bucket)
                ]
                ds.frescas[clase] = [
                    _fila_audit(db, estado=estado, eventos=[], edad=e)
                    for e in _edades_frescas(plazo, filas_por_bucket)
                ]
            db.commit()

            # ── cadena forma 1: eslabones US5+ por el EMISOR REAL ──
            for i in range(3):
                emit_license_event(db, EVENT_SEAT_LIMIT, license_id="lic_seed_0018",
                                   seats_used=11 + i, max_seats=10, reason=f"seed-eslabon-{i}")
            # Envejecerlos por debajo del cutoff: la cadena hashea el CUERPO del evento (con su
            # propio `ts`), así que mover `timestamp` no toca el eslabón ni la verificación.
            eslabones = (db.query(AuditLog)
                         .filter(AuditLog.model == "license").all())
            for fila in eslabones:
                assert "seq" in fila.guardian_events[0], (
                    "el emisor real dejó de escribir `seq`: si es a propósito, este seed no es el "
                    "único que hay que revisar")
                fila.timestamp = ahora - timedelta(days=dias - 5)
                ds.cadena_us5.append(str(fila.id))
            db.commit()

            # ── cadena forma 2: licencia pre-US5 (event_type SIN seq/prev_hash) ──
            # `blocked_by_policy` a propósito: es una clase MORTAL. Sobrevive por el portón
            # (`event_type`), no por su estado — el agujero histórico que el ancla por `seq` borraba.
            ds.licencia_pre_us5 = _fila_audit(
                db, model="license", estado="blocked_by_policy",
                eventos=[{"event_type": "license_loaded", "license_id": "lic_seed_0018",
                          "seats_used": None, "max_seats": None,
                          "reason": "licencia legitima pre-US5", "ts": ahora.isoformat()}],
                edad=dias - 5)

            # ── cadena forma 3: spoof (model='license' con forma de tráfico) — TIENE que morir ──
            ds.spoof = _fila_audit(
                db, model="license", estado="blocked_secret", eventos=[], edad=dias - 5)
            db.commit()

            # ── human_reviews (FR-004): vencida (texto → NULL) + fresca (texto conservado) ──
            def _review(edad, texto):
                rid = uuid.uuid4()
                db.add(HumanReview(
                    id=rid, tenant_id=DEFAULT_TENANT_ID, review_token=uuid.uuid4(),
                    reviewer_id="dpo-018", action="approved",
                    created_at=(ahora - timedelta(days=edad)).isoformat(),
                    response_text=texto,
                ))
                return str(rid)

            ds.review_vencida = _review(plazo + 30, TEXTO_REVISION_VENCIDA)
            ds.review_fresca = _review(max(3, plazo - 30), TEXTO_REVISION_FRESCA)
            db.commit()
        finally:
            db.close()

    return ds
