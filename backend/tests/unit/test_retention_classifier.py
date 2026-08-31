"""T004 (spec 018) — el clasificador de retención, auditado contra su CONTRATO.

Este test se escribió contra `specs/018-retencion-tiers/contracts/clasificador-identidad-tier.md`
(Contrato 1) y contra el seed de clases de la 004, no leyendo `classifier.py` para acomodarle
las expectativas. Es a propósito: el clasificador es la ÚNICA definición de «qué fila pertenece
a qué clase de retención», y de esa definición cuelgan dos consumidores que tienen que contar lo
mismo — el purgador, que BORRA, y la vitrina del officer, que muestra.

Las cuatro reglas del contrato, y cómo se muerden acá:

1. **Partición total de lo purgable** (regla 1). Toda fila de `audit_logs` cae en exactamente
   una clase o en la exclusión `license`. Se verifica con álgebra de conjuntos sobre TODAS las
   filas de la tabla: nada sin clase (una fila sin clase es una fila inmortal — la promesa del
   día 91 deja de ser cierta para ella) y nada en dos clases (una fila en dos clases tiene dos
   fechas de muerte, gana la más corta, y la clase larga le miente al auditor).

2. **La evidencia de licencias no se purga, y la regla no cuelga de una columna que el cliente
   escribe** (regla 2). Ningún predicado devuelve una fila de la cadena, y la exclusión NO es
   por estado: las filas de la hash-chain (021) se siembran acá con TODO el vocabulario de
   estados, no sólo con los tres que hoy emite `_COMPLIANCE_BY_EVENT`, porque una exclusión que
   dependiera del estado sería un bug latente esperando al primer evento de licencia con literal
   nuevo. Purgar un eslabón no es un bug de retención: `verify_chain` lee cualquier hueco como
   manipulación y el true-up exige historial completo.

   Tampoco es por `model` —esa columna la escribe el inspeccionado— ni por «trae `seq`», que
   fue la enmienda de una ronda anterior y dejaba un agujero histórico verificado: entre el
   16 y el 20 de julio el emisor de la 021 escribió filas de licencia LEGÍTIMAS **sin** `seq`
   (0a8cda1, 1a93cf3, 8e8f705; `seq` recién aparece en 9cd7b99), y con ese ancla caían en clase
   mortal y el purgador las borraba. Hoy la pregunta está invertida: se purga lo que es
   demostrablemente TRÁFICO, por la FORMA de `guardian_events`. La última sección de este
   archivo es la que muerde esa forma, con la tabla de verdad medida contra Postgres.

   **Y desde el dictamen del manager del 14-ago la columna `model` no participa del portón NI
   COMO CONDICIÓN ADITIVA**: «la exclusión la compra la FORMA, no el literal». Lo que sostiene
   eso es el acoplamiento entre el emisor real y el portón, y por eso hay un test que llama a
   `emit_license_event` y verifica en SQL que la fila que deja no es purgable
   (`test_la_forma_que_emite_el_emisor_real_no_es_purgable`). El corolario incómodo, afirmado y
   no disimulado: una fila que dice `license` con forma de tráfico (un SPOOF — el emisor nunca
   la escribió) SÍ es purgable, y eso es lo que se quería.

3. **El emisor nuevo no pasa de contrabando** (regla 4). Acá está el corazón de la tarea, y
   conviene ser explícito sobre el mecanismo, porque el clasificador NO es un inventario: la
   clasificación es por prefijos totales, con `usage_metadata` como fail-safe para el literal
   que nadie previó (decisión argumentada en el docstring de `classifier.py`: entre «murió con
   el plazo equivocado» y «no muere nunca y nadie se entera», la 018 eligió lo primero). Con esa
   forma, `clase_de` nunca devuelve None para tráfico y la partición nunca se rompe sola. Lo
   que sostiene la regla 4 es `EMISORES_VIGENTES`, el inventario declarado del clasificador… que
   es exactamente el tipo de lista escrita a mano que alguien se olvida de actualizar.
   **Por eso el oráculo de este test es el CÓDIGO FUENTE, no el inventario**: se censan los dos
   planos (backend y motor) buscando literales de `compliance_status`, y se exige que todo lo
   que el producto emite hoy esté declarado. Un emisor nuevo sin inventariar pone esto en rojo
   con su `archivo:línea` — eso es la feature, no un bug.

4. **`clase_de()` y `predicado()` cuentan lo mismo**. Son dos caminos a la misma verdad —uno en
   Python sobre la fila, otro en SQL sobre la tabla— y los consume gente distinta: el purgador
   borra con el predicado y el rastro de la corrida se explica con `clase_de`. Si divergen, el
   `purge_log` le miente al auditor sobre qué se borró.

Lo que este test NO hace, a propósito: no fija a qué clase va CADA literal contra una tabla
propia — sería un calco de la implementación, verde con cualquier cosa que el clasificador diga.
Sí fija los anclajes que el papel firmado SÍ resuelve, en el `justification` del seed 004:
`security_events` son «eventos de guardianes y alertas de seguridad» y `config_audit` son
«cambios de configuración del sistema». Un bloqueo que no viva como evento de seguridad, o
tráfico ordinario viviendo 730 días como si fuera un cambio de configuración, contradice el
documento que el cliente firma, no una preferencia nuestra.

## Que este archivo muerde está MEDIDO, no supuesto

Corrida de mutación del 14-ago sobre los 74 tests de este archivo. El número es cuántos se
ponen rojos; la columna «abus» es el MISMO mutante sobre
`tests/integration/test_retencion_dataset_abusivo.py` (41 tests):

| mutación                                                        | acá | abus |
|-----------------------------------------------------------------|-----|------|
| el portón deja de nombrar la lista vacía (`= '[]'::jsonb`)        |  11 |   13 |
| saco `event_type` de `MARCAS_DE_LA_CADENA`                        |   4 |    0 |
| saco la guarda `jsonb_typeof(primero) = 'object'`                 |   4 |    0 |
| saco `guardian_events IS NOT NULL`                                |   3 |    0 |
| VUELVE la condición aditiva `model <> 'license'` al portón        |   2 |    5 |
| `dice_licencia()` compara por PREFIJO en vez de por igualdad      |   2 |    0 |
| `_modelo()` sin su `coalesce`                                     |   1 |    0 |
| **el EMISOR deja de escribir el eslabón (`guardian_events=[]`)**   | **1** |  0 |
| **el EMISOR renombra las tres marcas de la cadena**                | **1** |  0 |

Las dos últimas son el test VERDUGO (`test_la_forma_que_emite_el_emisor_real_no_es_purgable`) y
son las únicas de la tabla que mutan `licensing/audit_events.py` y no el clasificador. Ese es el
punto del dictamen del 14-ago: desde que el portón es la única defensa, el rojo tiene que
aparecer cuando cambia el EMISOR, no sólo cuando alguien toca el clasificador.

Mutante que NO cae y no es un agujero, anotado para que la próxima corrida no lo persiga: que el
emisor deje de escribir SÓLO `event_type` (conservando `seq` y `prev_hash`) da 0 rojos, y está
bien — la fila sigue protegida por las otras dos marcas y ninguna licencia muere.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import null, text
from sqlalchemy.orm import sessionmaker

from migration_harness import fresh_db, owner_engine, require_postgres, run_alembic
from src.models.audit import AuditLog
from src.services.retention import classifier

require_postgres()

DB = "sentinel_test_retention_clf"
TENANT = uuid.UUID("00000000-0000-0000-0000-000000000001")  # default tenant (seed 010)

# `model='license'` — el literal de la exclusión estructural (FR-003). Va acá como constante del
# test y NO importado del clasificador a propósito: si el clasificador se equivocara de literal,
# importárselo haría que el test se equivoque con él.
MODELO_LICENCIA = "license"

# Las cuatro clases del seed 004:100-109. Se nombran acá sólo para los anclajes semánticos; la
# lista canónica se lee de `retention_policies` en la DB (ver `test_las_clases_...`).
CLASE_PROMPT_CONTENT = "prompt_content"
CLASE_SECURITY_EVENTS = "security_events"
CLASE_CONFIG_AUDIT = "config_audit"
# La clase fail-safe: donde cae lo que nadie previó (y donde tienen que caer los bordes que
# mira la última sección). Escrita acá y no importada del clasificador por el mismo motivo que
# `MODELO_LICENCIA`: si el clasificador se equivocara de literal, importárselo haría que el
# test se equivoque con él.
CLASE_USAGE_METADATA = "usage_metadata"


# ══ Censo de emisores ════════════════════════════════════════════════════════════════
#
# De dónde salen los `compliance_status` que existen DE VERDAD. Los emite gente de los DOS
# planos: el backend (`chat.py`, `gateway.py`, `guardians.py`, `budget_service.py`,
# `engine_gate.py`, `licensing/audit_events.py`) y el motor (`litellm/extensions/*`, que escribe
# por `POST /internal/audit-logs`). Olvidarse del plano motor sería censar la mitad:
# `blocked_entity_type`, `blocked_nlp_unavailable` y `degraded_nlp_regex` sólo existen allá.
#
# Se censa sobre el TEXTO del fuente y no con AST porque los literales viajan de todas las
# formas posibles: kwarg (`compliance_status="blocked_secret"`), constante de módulo
# (`STATUS_SATURATED`), valor de un dict (`_COMPLIANCE_BY_EVENT`), default de un `.get()`, y
# hasta embebidos dentro de un SQL en string (`analytics.py:212`). Un AST que resolviera todos
# esos caminos sería más frágil que estas tres redes, no menos.
_REDES = {
    # 1) Por FORMA: las familias del vocabulario vigente (convención D1).
    "forma": re.compile(
        r"""["'](passed|allowed[a-z0-9_]*|flagged[a-z0-9_]*|blocked[a-z0-9_]*"""
        r"""|rejected[a-z0-9_]*|config_change[a-z0-9_]*)["']"""),
    # 2) Por POSICIÓN: el literal escrito donde se asigna la columna.
    "kwarg": re.compile(r"""compliance_status["']?\s*[=:]\s*["']([a-z][a-z0-9_]*)["']"""),
    # 3) Por NOMBRE de la constante que lo bautiza. Es la red que caza a los estados SIN prefijo
    #    de familia — hoy `degraded_nlp_regex` (`STATUS_NLP_DEGRADED`), que la red de forma no ve.
    "const": re.compile(
        r"""^\s*_?[A-Z0-9_]*(?:STATUS|COMPLIANCE)[A-Z0-9_]*\s*=\s*["']([a-z][a-z0-9_]*)["']"""),
}

# Literales con forma de estado que NO son `compliance_status`. Cada uno con su motivo escrito:
# la próxima persona que agregue uno tiene que poder discutir el motivo, no adivinarlo.
_HOMONIMOS = {
    "blocked": "decisión del registry 027 y clave del veredicto de guardián, no un estado",
    "blocked_by_layer": "nombre de columna de audit_logs (el layer_key que bloqueó)",
    "blocked_topics": "clave de configuración de un guardián (guardian_service.py:159)",
    "blocked_words": "clave del payload de una política de contenido (spec 036 US2: la LISTA "
                     "de palabras a bloquear que viaja a litellm_content_filter), no un estado "
                     "de auditoría — mismo caso que `blocked_topics`",
    "flagged": "familia visual del monitor (monitor.py:318), no un estado",
    "allowed_tools": "clave de política de contexto/custom_auth",
    "allowed_models": "clave de política de contexto/custom_auth",
    "compliance_officer": "valor del enum Rol (auth/matrix.py, spec 017 T003) — nombre de rol "
                          "RBAC, NO un compliance_status de auditoría (los estados son passed/"
                          "blocked/config_change_*, jamás un rol)",
}

# Módulos donde `STATUS_*` nombra OTRO vocabulario. Se excluyen de la red 3 (no de las otras):
# sus constantes son estados de otras máquinas, no de una fila de auditoría.
_OTROS_VOCABULARIOS_DE_STATUS = {
    "entitlement.py": "STATUS_* = estado de la LICENCIA (active/grace/expired…), spec 021",
    "sentinel_governance.py": "STATUS_* = estado de una CAPA del registry (applied/skipped…), spec 027",
}

# Piso del censo: emisores que existen hoy y que se verificaron a mano al escribir esto
# (13-ago-2026). No es la lista de la que sale el dataset —esa es el censo completo— sino el
# canario DEL CENSO: si el mecanismo se rompe (ruta mal armada, plano motor sin montar, regex
# tocado), esto se pone rojo en vez de dejar pasar una suite vacía y verde, que es la peor forma
# de fallar que tiene un test: la que no se nota.
_PISO_DEL_CENSO = {
    "passed",                       # camino feliz, los dos planos
    "allowed",                      # legado: analytics.py:212 lo sigue contando como permitido
    "flagged_high_risk",            # AI-Act alto riesgo (compliance_service.py:55)
    "degraded_nlp_regex",           # D10 fail-open: NLP caído, se siguió con regex (plano motor)
    "blocked_prohibited",           # práctica prohibida AI-Act
    "blocked_by_policy",            # default de la cadena de licencias (audit_events.py:195)
    "blocked_secret",               # gateway.py:433 · sentinel_guardrail.py:500
    "blocked_residency",            # chat.py:1229 (residencia de datos)
    "blocked_nlp_unavailable",      # D10 fail-closed (plano motor)
    "blocked_entity_type",          # sentinel_guardrail.py:588 (plano motor)
    "rejected_saturated",           # engine_gate.py — tope de admisión (NO es un bloqueo)
    "rejected_budget",              # budget_service.py — tope de presupuesto (issue #157)
    "config_change_nlp_fail_mode",  # guardians.py:334 — cambio de configuración
}

# El punto ciego conocido del censo, escrito para que no se pierda: `upstream_error` se emite
# POSICIONALMENTE (`_audit(ident, model, 0, 0, "upstream_error", …)` en gateway.py:1482, :1519,
# :1527), sin nombre de columna ni constante ni prefijo de familia. Ninguna red de texto lo ve.
# Se lo verifica por el otro lado: tiene que estar inventariado igual (ver su test).
_CIEGOS_AL_CENSO = {
    "upstream_error": "gateway.py:1482,1519,1527 — argumento posicional de _audit()",
}

_RAIZ_BACKEND = Path(__file__).resolve().parents[2]
_RAIZ_REPO = _RAIZ_BACKEND.parent


def _planos_de_emision() -> list[Path]:
    """Los dos árboles de código que escriben `compliance_status` en `audit_logs`.

    El plano motor se busca con la MISMA lógica con que `conftest.py` lo importa: dentro del
    container está montado en `backend/litellm_config/extensions`; en el checkout vive en
    `<repo>/litellm/extensions`.
    """
    planos = [_RAIZ_BACKEND / "src"]
    for candidato in (_RAIZ_BACKEND / "litellm_config", _RAIZ_REPO / "litellm"):
        if (candidato / "extensions").is_dir():
            planos.append(candidato / "extensions")
            break
    return planos


def _corto(fuente: Path) -> str:
    """Ruta legible para el mensaje de error. Dentro del container el checkout está en `/app` y
    el plano motor montado aparte, así que no siempre hay una raíz común: cuando no la hay, el
    nombre del archivo alcanza para encontrarlo."""
    for raiz in (_RAIZ_REPO, _RAIZ_BACKEND):
        try:
            return str(fuente.relative_to(raiz))
        except ValueError:
            continue
    return fuente.name


def _censo_de_emisores() -> dict[str, list[str]]:
    """`compliance_status` → dónde se emite (`archivo:línea`), barriendo los dos planos.

    Se excluye `services/retention/` del barrido: el clasificador no puede ser su propio censor
    — su inventario es justamente lo que este test contrasta contra la realidad.
    """
    censo: dict[str, list[str]] = {}
    for plano in _planos_de_emision():
        for fuente in sorted(plano.rglob("*.py")):
            partes = fuente.parts
            if "__pycache__" in partes or ("services" in partes and "retention" in partes):
                continue
            for nro, linea in enumerate(
                    fuente.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                for red, patron in _REDES.items():
                    if red == "const" and fuente.name in _OTROS_VOCABULARIOS_DE_STATUS:
                        continue
                    for hallazgo in patron.finditer(linea):
                        literal = hallazgo.group(1)
                        if literal in _HOMONIMOS:
                            continue
                        censo.setdefault(literal, []).append(f"{_corto(fuente)}:{nro}")
    return censo


CENSO = _censo_de_emisores()

# El vocabulario completo que hay que sembrar: lo que el fuente emite (censo) MÁS lo que el
# clasificador declara (inventario). La unión y no una de las dos: si el inventario tiene un
# literal que ya nadie emite, igual queremos ver cómo clasifica; si el fuente tiene uno que
# nadie inventarió, queremos que aparezca en la tabla y que el test lo nombre.
VOCABULARIO = sorted(set(CENSO) | set(classifier.EMISORES_VIGENTES))

_ESTADOS_DE_CONFIG = sorted(e for e in VOCABULARIO if e.startswith("config_change"))
_ESTADOS_DE_BLOQUEO = sorted(e for e in VOCABULARIO if e.startswith("blocked"))
# Tráfico ordinario: ni bloqueo, ni rechazo, ni cambio de configuración. Es lo que la promesa
# del día 91 tiene que alcanzar.
_ESTADOS_DE_TRAFICO = sorted(
    e for e in VOCABULARIO if not e.startswith(("blocked", "rejected", "config_change")))


def _donde_se_emite(estado: str) -> str:
    return ", ".join(CENSO.get(estado, ["sin origen censado"])[:3])


# ══ Dataset sembrado ═════════════════════════════════════════════════════════════════
def _ahora() -> datetime:
    # La columna es naive (UTC por convención del repo); se construye así y no con `utcnow()`
    # sólo para no arrastrar el DeprecationWarning a la salida de la suite.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _filas_del_dataset() -> list[AuditLog]:
    """Una fila por (estado × edad × plano), más la fila real del cambio de configuración.

    Las **dos edades** (de hoy y de hace 400 días) no son decorado: la clase de una fila es su
    naturaleza, no su antigüedad. Quién está vencido lo decide el purgador contra el reloj de la
    DB; si el clasificador mirara el `timestamp`, una misma clase tendría dos poblaciones según
    el día en que corra el test y la partición sería inestable.

    Los **tokens** separan las poblaciones también a propósito: el tráfico real trae tokens y
    coste, y los eventos de configuración y de licencia traen CERO (así los escriben
    `guardians.py:371` y `audit_events.py:189`). Sembrar todo en cero dejaría pasar sin ruido a
    un clasificador que se apoyara en esa columna.
    """
    ahora = _ahora()
    filas: list[AuditLog] = []
    for estado in VOCABULARIO:
        for dias in (0, 400):
            filas.append(AuditLog(
                tenant_id=TENANT, timestamp=ahora - timedelta(days=dias),
                model="gpt-4o", prompt_tokens=120, completion_tokens=340,
                cost_usd=0.0123, pii_detected=False,
                compliance_status=estado, latency_ms=850,
            ))
            # El MISMO estado, pero en la cadena de licencias: la exclusión es por `model`.
            filas.append(AuditLog(
                tenant_id=TENANT, timestamp=ahora - timedelta(days=dias),
                model=MODELO_LICENCIA, prompt_tokens=0, completion_tokens=0,
                cost_usd=0, pii_detected=False,
                compliance_status=estado, latency_ms=0,
                guardian_events=[{"event_type": "license_loaded", "seq": 1}],
            ))
    # La fila del cambio de `nlp_fail_mode` tal cual la escribe `guardians.py:373`: el "modelo"
    # es el CÓDIGO del cambio con la transición pegada, no un LLM. Se siembra con esa forma
    # exacta porque es la única fila del sistema cuyo `model` no nombra un modelo.
    for estado in _ESTADOS_DE_CONFIG:
        filas.append(AuditLog(
            tenant_id=TENANT, timestamp=ahora - timedelta(days=800),
            model=f"{estado}:closed->open", prompt_tokens=0, completion_tokens=0,
            cost_usd=0, pii_detected=False,
            compliance_status=estado, latency_ms=0,
            processing_purpose="administrative",
        ))
    return filas


@pytest.fixture(scope="module")
def sesion():
    fresh_db(DB)
    run_alembic(DB, "upgrade", "head")
    engine = owner_engine(DB)
    # Sesión propia (no `SessionLocal`): sin GUC de tenant aplica la policy
    # `tenant_isolation_bootstrap` de la 010 y el dataset entero es visible.
    s = sessionmaker(bind=engine)()
    s.add_all(_filas_del_dataset())
    s.commit()
    yield s
    s.close()
    engine.dispose()


def _ids_por_clase(sesion) -> dict[str, set]:
    return {
        clase: {f.id for f in sesion.query(AuditLog.id).filter(classifier.predicado(clase))}
        for clase in classifier.clases()
    }


def _una_fila(sesion, estado: str) -> AuditLog:
    """Una fila de tráfico (no-licencia) con ese estado. Falla ruidoso si el dataset no la tiene:
    un test que se saltea silenciosamente el caso que vino a mirar no está midiendo nada."""
    fila = sesion.query(AuditLog).filter(
        AuditLog.compliance_status == estado, AuditLog.model != MODELO_LICENCIA).first()
    assert fila is not None, f"el dataset no sembró ninguna fila de tráfico con {estado!r}"
    return fila


# ══ El censo, antes que nada ═════════════════════════════════════════════════════════
def test_el_censo_de_emisores_no_se_degrado_en_silencio():
    assert len(_planos_de_emision()) == 2, (
        "Falta el plano motor (`litellm/extensions`): `blocked_entity_type`, "
        "`blocked_nlp_unavailable` y `degraded_nlp_regex` sólo se emiten allá y quedarían fuera "
        "del censo y del dataset.")
    faltantes = _PISO_DEL_CENSO - set(CENSO)
    assert not faltantes, (
        f"El censo del fuente dejó de encontrar emisores que existen: {sorted(faltantes)}. "
        f"Planos barridos: {[str(p) for p in _planos_de_emision()]}. "
        "No bajes el piso para poner esto en verde: si el censo no ve, el contraste contra el "
        "inventario queda vacío y verde, que es lo mismo que no tenerlo.")


def test_los_emisores_ciegos_al_censo_siguen_inventariados():
    """El censo tiene un punto ciego conocido y acotado: los literales que viajan como argumento
    POSICIONAL no los ve ninguna red de texto. Hoy hay exactamente uno (`upstream_error`), y como
    la máquina no puede vigilarlo, lo vigila este test a mano. Si alguien lo saca del inventario
    mientras `gateway.py` lo sigue emitiendo, se pone rojo acá."""
    for estado, donde in _CIEGOS_AL_CENSO.items():
        assert estado in classifier.EMISORES_VIGENTES, (
            f"{estado!r} ({donde}) desapareció del inventario de emisores vigentes. Si el emisor "
            "murió, el que se borra es este renglón del test —con el commit que lo mató a la "
            "vista—; si sigue vivo, vuelve al inventario.")


# ══ Contrato 1 · `clases()` ══════════════════════════════════════════════════════════
def test_las_clases_son_las_cuatro_del_seed_004(sesion):
    """Las clases no las inventa el clasificador: son las sembradas en `retention_policies`
    (004:100-109), que es de donde el purgador lee los plazos. Se leen de la TABLA y no de una
    lista escrita acá para que agregar una quinta clase al seed sin darle predicado rompa por
    donde tiene que romper."""
    del_seed = {fila[0] for fila in sesion.execute(
        text("SELECT log_type FROM retention_policies")).fetchall()}
    clases = classifier.clases()

    assert set(clases) == del_seed, (
        f"El clasificador dice {sorted(clases)} y el seed 004 tiene {sorted(del_seed)}. Una clase "
        "sembrada sin predicado es un plazo configurado que nunca purga; un predicado sin clase "
        "sembrada es una purga sin plazo del que leer.")
    assert len(clases) == len(set(clases)), f"clases() repite valores: {clases}"
    assert clases == classifier.clases(), "clases() no devuelve un orden estable"


# ══ Contrato 1 · regla 4: el emisor nuevo no pasa de contrabando ═════════════════════
def test_todo_emisor_vivo_del_fuente_esta_inventariado():
    """**El test que define esta tarea.**

    El clasificador clasifica por prefijos totales con fail-safe, así que un literal nuevo NUNCA
    queda sin clase: cae en `usage_metadata` y muere a los 365 días sin que nadie lo haya
    decidido. Lo único que convierte eso en una decisión consciente es `EMISORES_VIGENTES`, y un
    inventario escrito a mano sólo vale si algo independiente lo confronta con la realidad. Ese
    algo es este test: el oráculo es el CÓDIGO FUENTE de los dos planos, no el inventario.

    Si esto se pone rojo con un literal nuevo, la respuesta NO es agregarlo al inventario a las
    apuradas: es decidir cuánto tiene que vivir ese dato (¿es evidencia de seguridad a 365 d? ¿es
    un cambio de configuración a 730 d? ¿es metadata de uso?) y que el literal lleve el prefijo
    que corresponda a esa respuesta. El inventario se actualiza DESPUÉS de esa decisión.
    """
    sin_inventariar = {e: CENSO[e] for e in CENSO if e not in classifier.EMISORES_VIGENTES}
    assert not sin_inventariar, (
        "Emisores de `compliance_status` que el fuente escribe y nadie inventarió en "
        "`EMISORES_VIGENTES`:\n" + "\n".join(
            f"  · {estado!r} — emitido en {', '.join(donde[:3])}"
            for estado, donde in sorted(sin_inventariar.items())
        ) + "\n\nCada uno cae hoy en la clase fail-safe (`usage_metadata`, 365 d) sin que nadie "
        "haya decidido que ese es su plazo. Si el literal NO es un `compliance_status` (un "
        "homónimo: una clave de config, un nombre de columna), va a `_HOMONIMOS` de este test "
        "CON EL MOTIVO ESCRITO. Que esto rompa es la feature (Contrato 1, regla 4).")


def test_el_inventario_no_se_contradice_con_la_clasificacion_real(sesion):
    """La otra mitad: el inventario declara a qué clase va cada literal, y la clasificación la
    hacen los prefijos. Son dos afirmaciones distintas escritas en el mismo archivo, y pueden
    divergir — declarar `blocked_x: usage_metadata` compila igual, y a partir de ahí el
    inventario dice una cosa y el purgador hace otra. Lo que este test prueba es que la
    declaración y el comportamiento coinciden; a qué clase DEBE ir cada uno lo miran los anclajes
    semánticos de más abajo, que sí se apoyan en el seed 004 y no en el propio clasificador."""
    divergencias = []
    for estado, clase_declarada in sorted(classifier.EMISORES_VIGENTES.items()):
        clase_real = classifier.clase_de(_una_fila(sesion, estado))
        if clase_real != clase_declarada:
            divergencias.append(
                f"  · {estado!r}: el inventario dice {clase_declarada!r}, "
                f"el clasificador la manda a {clase_real!r}")
    assert not divergencias, (
        "El inventario de emisores y la clasificación real no dicen lo mismo:\n"
        + "\n".join(divergencias))


# ══ Contrato 1 · regla 1: partición total ════════════════════════════════════════════
def test_particion_total_de_lo_purgable(sesion):
    """Toda fila PURGABLE de `audit_logs` cae en exactamente una clase. Se verifica contra lo
    que HAY EN LA TABLA —no contra una lista escrita a mano— y lo que hay en la tabla salió del
    censo del fuente.

    «Purgable» en este dataset son las filas de tráfico: las que traen el `guardian_events`
    vacío con el que las persiste el producto. Se afirma esa premisa antes de medir nada (el
    `assert` de la forma): si un día el fixture sembrara tráfico con otra forma de jsonb, la
    partición seguiría verde midiendo un universo más chico del que cree, que es la manera
    silenciosa de que este test deje de cubrir lo que dice cubrir.

    Que el conjunto se separe por `model == 'license'` es una comodidad del FIXTURE, no el
    criterio del clasificador: en este dataset las filas de licencia se siembran con un primer
    evento con `seq`, así que el portón las excluye por su FORMA y el literal no decide nada.
    Si mañana alguien sembrara una fila `license` con `guardian_events=[]`, sería un spoof, sería
    purgable, y este test lo diría en el `assert` de la forma antes de medir la partición.
    """
    todas = {fila.id: fila for fila in sesion.query(AuditLog).all()}
    assert todas, "dataset vacío: el fixture no sembró nada"

    de_licencia = {i for i, f in todas.items() if f.model == MODELO_LICENCIA}
    purgables = set(todas) - de_licencia
    otra_forma = sorted(
        f"{todas[i].compliance_status!r} → {todas[i].guardian_events!r}"
        for i in purgables if todas[i].guardian_events != [])
    assert not otra_forma, (
        "El fixture sembró tráfico con un `guardian_events` que no es la lista vacía que "
        "escribe el producto (`audit_service.py:361`, y el DEFAULT '[]' de la 003). La "
        f"partición de abajo estaría midiendo otra cosa: {otra_forma}")
    por_clase = _ids_por_clase(sesion)
    cubiertas = set().union(*por_clase.values()) if por_clase else set()

    sin_clase = purgables - cubiertas
    assert not sin_clase, (
        "Filas purgables que NINGUNA clase reclama — inmortales: la promesa del día 91 no las "
        "alcanza y nadie se entera, que es el modo de falla que la 018 vino a matar. Estados sin "
        "clase: " + "; ".join(sorted(
            f"{todas[i].compliance_status!r} (emitido en {_donde_se_emite(todas[i].compliance_status)})"
            for i in sin_clase)))

    en_dos_clases = {
        i: [c for c, ids in por_clase.items() if i in ids]
        for i in purgables if sum(i in ids for ids in por_clase.values()) > 1
    }
    assert not en_dos_clases, (
        "Filas reclamadas por más de una clase — cada una tiene dos fechas de muerte, gana la más "
        "corta y la clase larga miente: " + "; ".join(
            f"{todas[i].compliance_status!r} → {clases}" for i, clases in en_dos_clases.items()))


def test_prompt_content_no_reclama_filas_de_audit_logs(sesion):
    """`audit_logs` es metadata-only por diseño (`audit_service.py:280`: «absolutely no raw prompt
    text or PII is recorded»), así que la clase `prompt_content` es el conjunto VACÍO sobre esta
    tabla y su plazo de 90 d muerde en otro lado: `human_reviews.response_text` (FR-004, T009).

    Se afirma porque un `WHERE` que no matchea nada borra cero filas SIN error: una clase vacía
    por diseño y una purga rota se ven idénticas desde afuera. Si mañana entra contenido a
    `audit_logs`, este test es el que avisa que FR-004 tiene que cambiar de manos."""
    assert CLASE_PROMPT_CONTENT in classifier.clases()
    reclamadas = sesion.query(AuditLog).filter(
        classifier.predicado(CLASE_PROMPT_CONTENT)).count()
    assert reclamadas == 0, (
        f"{CLASE_PROMPT_CONTENT!r} reclama {reclamadas} filas de audit_logs. O entró contenido a "
        "la tabla (y entonces FR-004 ya no se cumple borrando sólo human_reviews), o el predicado "
        "se solapa con otra clase.")


# ══ Contrato 1 · regla 2: la cadena de licencias no se toca ══════════════════════════
def test_ningun_predicado_devuelve_filas_de_la_cadena_de_licencias(sesion):
    """FR-003. La exclusión vale con CUALQUIER estado: acá la cadena está sembrada con todo el
    vocabulario, incluidos los `blocked*` que ella misma emite (`_COMPLIANCE_BY_EVENT` default =
    `blocked_by_policy`) y los que hoy no emite. Todas esas filas traen su `seq`, o sea que son
    eslabones de la 021 US5 en adelante, y lo que las protege es esa FORMA y no el literal del
    `model` (desde el 14-ago el portón ni mira esa columna). La forma pre-US5 —sin `seq`— y el
    resto de las formas que la columna admite los mira la última sección."""
    for clase in classifier.clases():
        colados = sesion.query(AuditLog).filter(
            classifier.predicado(clase), AuditLog.model == MODELO_LICENCIA).all()
        assert not colados, (
            f"La clase {clase!r} reclama {len(colados)} eslabón(es) de la hash-chain de licencias "
            f"(estados: {sorted({f.compliance_status for f in colados})}). Un hueco en la cadena "
            "lo lee `verify_chain` como manipulación y rompe el true-up: es un incidente de "
            "confianza con el cliente, no un bug de retención.")


def test_clase_de_no_le_pone_clase_a_la_cadena_de_licencias(sesion):
    """Corolario de la regla 2 por el camino Python: si `clase_de` le pusiera clase a un eslabón,
    el rastro de la corrida lo contaría como purgable y el auditor leería que la evidencia de
    licencias tiene fecha de vencimiento. No la tiene."""
    for fila in sesion.query(AuditLog).filter(AuditLog.model == MODELO_LICENCIA).all():
        clase = classifier.clase_de(fila)
        assert clase is None, (
            f"clase_de() clasificó un eslabón de licencia (estado "
            f"{fila.compliance_status!r}) como {clase!r}; la exclusión de FR-003 no admite clase.")


# ══ Contrato 1 · los dos caminos cuentan lo mismo ════════════════════════════════════
def test_clase_de_y_predicado_dicen_lo_mismo_de_cada_fila(sesion):
    """El purgador borra con `predicado()` (SQL) y el rastro de la corrida se explica con
    `clase_de()` (Python). Si divergen, el `purge_log` le miente al auditor sobre qué se borró."""
    por_clase = _ids_por_clase(sesion)
    desacuerdos = []
    for fila in sesion.query(AuditLog).all():
        segun_sql = [c for c, ids in por_clase.items() if fila.id in ids]
        esperado = segun_sql[0] if len(segun_sql) == 1 else None
        dicho = classifier.clase_de(fila)
        if dicho != esperado:
            desacuerdos.append(
                f"  · model={fila.model!r} estado={fila.compliance_status!r}: "
                f"predicado dice {segun_sql or 'ninguna'} y clase_de dice {dicho!r}")
    assert not desacuerdos, "\n".join(
        ["`clase_de()` y `predicado()` no cuentan lo mismo:"] + desacuerdos[:15])


# ══ El fail-safe, verificado en vez de asumido ═══════════════════════════════════════
def test_un_literal_no_previsto_cae_en_una_clase_mortal(sesion):
    """El clasificador eligió fail-safe en vez de inventario cerrado: el literal que nadie previó
    cae en una clase MORTAL en lugar de quedarse sin predicado y sobrevivir para siempre. Esa
    decisión sólo es defendible si de verdad funciona por los dos caminos — si `clase_de` lo
    clasificara pero ningún predicado lo levantara, la fila sería inmortal igual y encima el
    rastro de la corrida diría que estaba cubierta.

    La fila se inserta y se descarta con `rollback`: es un canario, no dataset (si quedara, el
    test de contraste contra el inventario la vería como un emisor sin declarar).
    """
    canario = AuditLog(
        tenant_id=TENANT, timestamp=_ahora(), model="gpt-4o",
        prompt_tokens=10, completion_tokens=10, cost_usd=0.001, pii_detected=False,
        compliance_status="quarantined_by_a_brand_new_emitter", latency_ms=10,
    )
    try:
        sesion.add(canario)
        sesion.flush()

        clase = classifier.clase_de(canario)
        assert clase in classifier.clases(), (
            f"Un literal no previsto quedó en {clase!r}: fuera de las clases del seed no hay "
            "plazo que leer, o sea que la fila no muere nunca.")
        levantada_por = [c for c in classifier.clases()
                         if sesion.query(AuditLog.id).filter(
                             classifier.predicado(c), AuditLog.id == canario.id).count()]
        assert levantada_por == [clase], (
            f"clase_de manda el literal no previsto a {clase!r} pero el SQL lo levanta en "
            f"{levantada_por}: el fail-safe existe en Python y no en el WHERE que borra.")
    finally:
        sesion.rollback()


def test_un_bloqueo_desconocido_no_se_disfraza_de_trafico(sesion):
    """La familia que más crece es `blocked_*`: mañana un guardián nuevo emite
    `blocked_<lo_que_sea>`. Ese literal tiene que seguir viviendo como evidencia de seguridad
    —365 d— aunque nadie lo haya inventariado todavía; si cayera en una clase de tráfico, la
    evidencia del bloqueo se moriría antes de tiempo, que es justo la que el officer busca
    cuando pregunta qué pasó."""
    nuevo = AuditLog(
        tenant_id=TENANT, timestamp=_ahora(), model="gpt-4o",
        prompt_tokens=0, completion_tokens=0, cost_usd=0, pii_detected=False,
        compliance_status="blocked_por_un_guardian_que_no_existe_todavia", latency_ms=5,
    )
    try:
        sesion.add(nuevo)
        sesion.flush()
        clase = classifier.clase_de(nuevo)
        assert clase == CLASE_SECURITY_EVENTS, (
            f"Un bloqueo desconocido quedó clasificado como {clase!r} en vez de "
            f"{CLASE_SECURITY_EVENTS!r} (seed 004: «eventos de guardianes y alertas de "
            "seguridad»). El prefijo `blocked` es la convención D1 de todo el producto: si el "
            "clasificador deja de respetarlo, cada guardián nuevo nace con el plazo equivocado.")
    finally:
        sesion.rollback()


# ══ Anclajes semánticos: lo que el papel firmado SÍ resuelve ═════════════════════════
def test_los_bloqueos_viven_como_eventos_de_seguridad(sesion):
    """Seed 004: `security_events` = «Eventos de guardianes y alertas de seguridad… requisitos
    ENS». Un bloqueo es exactamente eso. Si viviera como tráfico, el ENS se quedaría sin sus
    365 días de evidencia."""
    assert CLASE_SECURITY_EVENTS in classifier.clases()
    assert _ESTADOS_DE_BLOQUEO, "el vocabulario no tiene ningún `blocked*` — revisar el censo"
    for estado in _ESTADOS_DE_BLOQUEO:
        clase = classifier.clase_de(_una_fila(sesion, estado))
        assert clase == CLASE_SECURITY_EVENTS, (
            f"{estado!r} (emitido en {_donde_se_emite(estado)}) quedó como {clase!r} en vez de "
            f"{CLASE_SECURITY_EVENTS!r}.")


def test_los_cambios_de_configuracion_viven_como_config_audit(sesion):
    """Seed 004: `config_audit` = «Cambios de configuración del sistema. Mínimo 24 meses para
    trazabilidad de decisiones administrativas». La fila del cambio de `nlp_fail_mode` es el caso
    vivo: es la traza de quién aflojó el fail-closed del NLP, y se siembra con el `model` raro que
    escribe `guardians.py` (`config_change_nlp_fail_mode:closed->open`) para verificar que la
    clase la decide el estado y no la forma del modelo."""
    assert CLASE_CONFIG_AUDIT in classifier.clases()
    assert _ESTADOS_DE_CONFIG, "el vocabulario no tiene ningún `config_change*` — revisar el censo"
    for estado in _ESTADOS_DE_CONFIG:
        filas = sesion.query(AuditLog).filter(
            AuditLog.compliance_status == estado, AuditLog.model != MODELO_LICENCIA).all()
        assert len(filas) >= 3, "faltan las variantes sembradas (dos edades + la fila real)"
        for fila in filas:
            clase = classifier.clase_de(fila)
            assert clase == CLASE_CONFIG_AUDIT, (
                f"{estado!r} (model={fila.model!r}, emitido en {_donde_se_emite(estado)}) quedó "
                f"como {clase!r}; con menos de 730 días la traza administrativa no llega a los "
                "24 meses que el seed promete.")


def test_el_trafico_ordinario_no_se_disfraza_de_configuracion_ni_de_seguridad(sesion):
    """La otra mitad del anclaje. Un `passed` clasificado como `config_audit` viviría 730 días: la
    promesa del día 91 (US1) sería falsa justo para las filas más numerosas del sistema."""
    assert _ESTADOS_DE_TRAFICO, "el vocabulario no tiene tráfico ordinario — revisar el censo"
    prohibidas = {CLASE_CONFIG_AUDIT, CLASE_SECURITY_EVENTS}
    for estado in _ESTADOS_DE_TRAFICO:
        clase = classifier.clase_de(_una_fila(sesion, estado))
        assert clase not in prohibidas, (
            f"Tráfico ordinario ({estado!r}, emitido en {_donde_se_emite(estado)}) clasificado "
            f"como {clase!r}: ni es un cambio de configuración ni es una alerta de seguridad, y "
            "con ese plazo la purga del día 91 no lo alcanza.")


# ══ Las tres guardas load-bearing del clasificador ═══════════════════════════════════
#
# Los tests de arriba miran el MAPEO (qué fila va a qué clase) sobre el vocabulario que el
# producto emite hoy. Esta sección mira otra cosa: las tres guardas defensivas que el módulo
# escribió a propósito y cuyo docstring declara load-bearing. Ninguna cambia el resultado con
# los datos de hoy — por eso el mapeo entero puede quedar verde con las tres sacadas, y por eso
# necesitan test propio. Las tres fallan igual: en silencio y hacia el mismo lado, filas que
# nadie borra y una purga que aparenta correr. Que es el modo de falla que la 018 vino a matar.


def test_predicado_de_una_clase_desconocida_levanta_en_vez_de_devolver_vacio():
    """**Guarda 1 · `predicado()` con una clase que no existe.**

    Es la más importante de las tres y la que menos se nota: cambiar el `raise` por un
    `return false()` deja la suite entera en verde. Verde y mintiendo — porque un predicado
    vacío no explota, se mete en el `WHERE` del DELETE, borra CERO filas y devuelve éxito. El
    purgador registraría su corrida `ok` con `rows_deleted=0` para esa clase, el officer leería
    «al día» y las filas seguirían ahí. Comparado con eso, un `ValueError` en el arranque del
    job es el mejor final posible: rompe fuerte, temprano y con nombre.

    Una clase fuera de `clases()` no es un caso de negocio, es un error del programa: un typo
    en una perilla, una quinta clase agregada al seed 004 sin darle predicado, o alguien
    pidiendo `license` como si la exclusión estructural fuera una clase más (regla 2 — no lo
    es, y por eso está en la lista de abajo).
    """
    desconocidas = [
        "license",            # la exclusión (regla 2) NO es una clase: pedirla es el bug
        "clase_que_no_existe",
        "prompt-content",     # guion en vez de guion bajo
        "usage_metadatos",    # typo del que se escribe de memoria
        "PROMPT_CONTENT",     # el mismo nombre en otra caja
        "",                   # una perilla vacía leída del entorno
    ]
    for clase in desconocidas:
        with pytest.raises(ValueError) as excepcion:
            classifier.predicado(clase)
        assert repr(clase) in str(excepcion.value), (
            f"El error de {clase!r} no nombra la clase que se pidió: quien lo lea a las 3 de la "
            "mañana en el log del job tiene que saber qué se pidió sin abrir el fuente.")

    # La otra mitad: la guarda no puede haberse pasado de rosca. Las cuatro del seed tienen que
    # seguir devolviendo predicado — si esto rompe, la purga no corre para NADIE.
    for clase in classifier.clases():
        assert classifier.predicado(clase) is not None


def test_el_prefijo_de_configuracion_no_es_un_comodin_de_like(sesion):
    """**Guarda 2 · `autoescape=True` en el predicado de `config_change`.**

    En LIKE el `_` es comodín de un carácter, así que `config_change` crudo también matchea
    `configXchange…`. Compilado contra el dialecto de producción se ve la diferencia exacta:

        con autoescape:  LIKE 'config/_change' || '%' ESCAPE '/'
        sin  autoescape:  LIKE 'config_change' || '%'

    Sin la guarda, un literal así entra a `config_audit` por el camino SQL y se queda 730 días,
    mientras el gemelo Python (`str.startswith`, que no tiene comodines) lo sigue mandando a
    `usage_metadata`. Ese es el daño real: los dos caminos dejan de contar lo mismo, el purgador
    borra según uno y el rastro de la corrida se explica con el otro.

    El canario se inserta y se descarta con `rollback` — es un canario, no dataset.
    """
    canario = AuditLog(
        tenant_id=TENANT, timestamp=_ahora(), model="gpt-4o",
        prompt_tokens=90, completion_tokens=15, cost_usd=0.002, pii_detected=False,
        # Elegido para que el `_` importe: matchea `config_change%` SÓLO si el guion bajo
        # sigue siendo comodín.
        compliance_status="configXchange_de_un_emisor_que_no_existe", latency_ms=40,
    )
    try:
        sesion.add(canario)
        sesion.flush()

        levantada_por = [c for c in classifier.clases()
                         if sesion.query(AuditLog.id).filter(
                             classifier.predicado(c), AuditLog.id == canario.id).count()]
        assert CLASE_CONFIG_AUDIT not in levantada_por, (
            f"El SQL metió {canario.compliance_status!r} en {CLASE_CONFIG_AUDIT!r}: el `_` de "
            "`config_change` volvió a ser comodín de LIKE. Esa fila viviría 730 días como si "
            "fuera un cambio de configuración auditado, y `clase_de()` —que compara con "
            "`str.startswith`, sin comodines— diría que muere a los 365.")
        assert levantada_por == [CLASE_USAGE_METADATA], (
            f"El literal cayó en {levantada_por} en vez de en la clase fail-safe "
            f"{CLASE_USAGE_METADATA!r}.")
        assert classifier.clase_de(canario) == CLASE_USAGE_METADATA
    finally:
        sesion.rollback()


def test_clase_de_no_revienta_con_una_fila_en_memoria_sin_estado():
    """**Guarda 3a · el `or ""` de `clase_de()`.**

    El caso no es hipotético y el docstring del clasificador lo dice: un `AuditLog` construido
    en memoria y todavía sin flush llega con `compliance_status=None`, porque el NOT NULL vive
    en la DB y el objeto Python no lo sabe. Sin la guarda eso es `None.startswith(...)` →
    `AttributeError`, y el que lo come no es un test: es el purgador armando el rastro de su
    corrida, o cualquiera que clasifique una fila antes de que toque la base.

    Sin sesión a propósito: el punto es justamente la fila que nunca llegó a la DB.
    """
    fila = AuditLog(
        tenant_id=TENANT, timestamp=_ahora(), model="gpt-4o",
        prompt_tokens=10, completion_tokens=10, cost_usd=0.001, pii_detected=False,
        latency_ms=10,
        # Explícito, y no confiando en el `default=list` de la columna: ese default lo aplica
        # el FLUSH y esta fila no llega a la base, así que sin esta línea `guardian_events` es
        # `None` y lo que mediríamos sería el portón —que devuelve `None` por forma, y con
        # razón— en vez del `or ""` que este test vino a mirar. Un test que se cae por el
        # motivo equivocado tapa el que decía cubrir.
        guardian_events=[],
    )
    assert fila.compliance_status is None, (
        "el modelo empezó a traer un default para compliance_status — este test ya no siembra "
        "el caso que vino a mirar")

    assert classifier.clase_de(fila) == CLASE_USAGE_METADATA, (
        "Una fila sin estado tiene que caer en la clase fail-safe, igual que cualquier literal "
        "no previsto: no clasificar es no morir nunca.")

    # La fila COMPLETAMENTE pelada (sin `model` tampoco) cae en la misma clase, y desde el
    # 14-ago por un motivo más simple que antes: `clase_de()` ya no le mira el `model` a nadie.
    # El portón es la forma de `guardian_events` y nada más, así que una fila sin modelo no es
    # un caso especial — es una fila de tráfico como cualquier otra.
    assert classifier.clase_de(AuditLog(guardian_events=[])) == CLASE_USAGE_METADATA


def test_una_fila_en_memoria_sin_guardian_events_no_se_clasifica():
    """El **cambio de comportamiento** de esta ronda, escrito donde se ve.

    Antes, una fila construida en memoria sin `guardian_events` caía en `usage_metadata`: el
    clasificador sólo le miraba el estado. Hoy el portón le mira la FORMA, y `None` no es una
    lista, así que la fila no es demostrablemente tráfico y `clase_de()` devuelve `None`. Es
    fail-closed a propósito y no un descuido — el porqué está en el docstring del clasificador,
    sección «Las dos direcciones».

    Que esto no rompa al purgador NO es una esperanza, es una propiedad de la tabla: el
    purgador clasifica filas LEÍDAS de la base, y ahí la columna nunca llega en `None` sin que
    alguien lo haya escrito a mano (`audit_service.py:361` persiste `guardian_events or []`,
    el INSERT de `/internal/audit` ni la nombra y toma el `DEFAULT '[]'` de la 003, y el plano
    chat arma la lista en `chat.py:559-561`). El caso de acá es el objeto en memoria, que es
    justamente el que no viaja a ningún `DELETE`.
    """
    assert classifier.clase_de(AuditLog()) is None, (
        "Una fila sin `guardian_events` volvió a clasificarse. El portón es fail-closed: lo "
        "que no se puede demostrar que es tráfico no se borra, porque puede ser un eslabón de "
        "la cadena de licencias con el jsonb en un estado que este código no reconoce.")


def _es_nullable(sesion, columna: str) -> bool:
    return sesion.execute(text(
        "SELECT is_nullable = 'YES' FROM information_schema.columns "
        "WHERE table_name = 'audit_logs' AND column_name = :columna"), {"columna": columna}).scalar()


def test_una_fila_con_estado_nulo_igual_cae_en_una_clase_mortal(sesion):
    """**Guarda 3b · el `coalesce` de `_estado()`, el gemelo SQL del `or ""`.**

    Hoy la columna es NOT NULL, así que el `coalesce` no cambia ni una fila y por eso ningún
    test del mapeo lo toca. Está por dónde falla si eso cambiara: en SQL,
    `NOT (NULL LIKE 'blocked%')` no es TRUE, es NULL, y una fila con estado nulo no matchearía
    NINGÚN predicado. No se rompe nada: la fila simplemente se vuelve inmortal en silencio, que
    es exactamente lo que la regla 1 prohíbe.

    Para sembrar el caso hay que aflojar el NOT NULL, y se hace DENTRO de la transacción: el
    DDL en Postgres es transaccional, así que el `rollback` devuelve columna y fila juntas. Se
    verifica al final que el esquema volvió — este `sesion` es de módulo y lo usan los otros
    tests.
    """
    nullable_antes = _es_nullable(sesion, "compliance_status")
    try:
        if not nullable_antes:
            sesion.execute(text(
                "ALTER TABLE audit_logs ALTER COLUMN compliance_status DROP NOT NULL"))
        huerfana = AuditLog(
            tenant_id=TENANT, timestamp=_ahora(), model="gpt-4o",
            prompt_tokens=70, completion_tokens=25, cost_usd=0.004, pii_detected=False,
            compliance_status=None, latency_ms=60,
        )
        sesion.add(huerfana)
        sesion.flush()

        levantada_por = [c for c in classifier.clases()
                         if sesion.query(AuditLog.id).filter(
                             classifier.predicado(c), AuditLog.id == huerfana.id).count()]
        assert levantada_por, (
            "Una fila con `compliance_status` NULL no la reclama NINGUNA clase: ningún WHERE la "
            "levanta, ninguna purga la borra y nadie se entera. Es la fila inmortal de la regla "
            "1, y la trae el trivalente de SQL — `NOT (NULL LIKE ...)` es NULL, no TRUE.")
        assert levantada_por == [CLASE_USAGE_METADATA], (
            f"La fila sin estado cayó en {levantada_por}; el fail-safe es "
            f"{CLASE_USAGE_METADATA!r}.")
        # Y los dos caminos siguen contando lo mismo también en el borde.
        assert classifier.clase_de(huerfana) == CLASE_USAGE_METADATA
    finally:
        sesion.rollback()

    assert _es_nullable(sesion, "compliance_status") == nullable_antes, (
        "El rollback no devolvió el NOT NULL de `audit_logs.compliance_status`: el esquema quedó "
        "tocado para los tests que comparten este fixture de módulo.")


def test_una_fila_con_modelo_nulo_no_se_le_esconde_al_officer(sesion):
    """**Guarda 3c · el `coalesce` de `_modelo()` — el mismo trivalente en la OTRA columna.**

    Este test cambió de blanco el 14-ago, y conviene decir por qué antes de leerlo: hasta ese
    día `_modelo()` viajaba en la condición aditiva del PORTÓN, y lo que se medía acá era una
    fila inmortal. La aditiva cayó (dictamen del manager: «la exclusión la compra la FORMA, no
    el literal»), así que el portón ya no mira `model` y por ese lado no hay nada que medir —
    una fila con `model` NULL es tráfico como cualquier otra, por su `guardian_events`.

    Lo que sí quedó vivo, y es lo que este test mide ahora, es el OTRO consumidor de
    `_modelo()`: la VITRINA, que excluye la cadena con `~dice_licencia()`. Ahí el trivalente
    muerde de verdad, y está medido contra el Postgres del compose:

        NOT (NULL = 'license')                → NULL   ⇒ la fila NO aparece en el listado
        NOT (coalesce(NULL,'') = 'license')   → True   ⇒ la fila se sigue viendo

    O sea que sin el `coalesce` una fila con `model` nulo se le esconde al officer en silencio.
    Es el daño nº2 del gate adversarial —el inspeccionado desapareciendo del reporte— servido
    por la puerta de la defensa, y encima sin que nadie tenga que declarar nada: alcanza con que
    la columna se vuelva nullable.

    `model` es NOT NULL en el esquema (igual que `compliance_status`), así que la fila no
    existe hasta aflojar la columna: el DDL va DENTRO de la transacción —en Postgres el DDL es
    transaccional— y el `rollback` devuelve columna y fila juntas. Se verifica al final que el
    esquema volvió: este `sesion` es de módulo y lo comparten los demás tests.
    """
    nullable_antes = _es_nullable(sesion, "model")
    try:
        if not nullable_antes:
            sesion.execute(text("ALTER TABLE audit_logs ALTER COLUMN model DROP NOT NULL"))
        # Estado de tráfico ordinario a propósito: lo único raro de esta fila es el `model`,
        # así que no hay dónde esconder el fallo.
        sin_modelo = AuditLog(
            tenant_id=TENANT, timestamp=_ahora(), model=None,
            prompt_tokens=15, completion_tokens=45, cost_usd=0.002, pii_detected=False,
            compliance_status="passed", latency_ms=95, guardian_events=[],
        )
        sesion.add(sin_modelo)
        sesion.flush()

        # 1. La VITRINA: la fila tiene que estar en el universo que la pantalla lista.
        visibles = {f.id for f in sesion.query(AuditLog.id).filter(
            ~classifier.dice_licencia())}
        assert sin_modelo.id in visibles, (
            "Una fila con `model` NULL desapareció del universo de la vitrina: el officer deja "
            "de verla y nadie falla. Lo trae el trivalente de SQL — `NOT (NULL = 'license')` es "
            "NULL, no TRUE — y lo tapa el `coalesce` de `_modelo()`.")
        # Y no se cuenta como cadena: NULL no es `license`, es «no se sabe», y acá «no se sabe»
        # tiene que significar «no es de licencia».
        assert sin_modelo.id not in {f.id for f in sesion.query(AuditLog.id).filter(
            classifier.dice_licencia())}

        # 2. La PURGA: sigue teniendo clase, ahora por la sola forma de `guardian_events`.
        levantada_por = [c for c in classifier.clases()
                         if sesion.query(AuditLog.id).filter(
                             classifier.predicado(c), AuditLog.id == sin_modelo.id).count()]
        assert levantada_por == [CLASE_USAGE_METADATA], (
            f"La fila sin modelo cayó en {levantada_por}; el fail-safe es "
            f"{CLASE_USAGE_METADATA!r}. El portón mira la FORMA, y esta fila trae `[]`.")
        assert classifier.clase_de(sin_modelo) == CLASE_USAGE_METADATA
    finally:
        sesion.rollback()

    assert _es_nullable(sesion, "model") == nullable_antes, (
        "El rollback no devolvió el NOT NULL de `audit_logs.model`: el esquema quedó tocado "
        "para los tests que comparten este fixture de módulo.")


# ══ El portón: «¿es demostrablemente TRÁFICO?» ═══════════════════════════════════════
#
# Esta sección mide la pieza que estas rondas cambiaron, y conviene tenerlas presentes a las
# TRES porque cada una existe por el daño que hizo la anterior.
#
# **Ronda 1 (gate adversarial, 13-ago).** `audit_logs.model` la escribe el INSPECCIONADO: en el
# passthrough sale del cuerpo del pedido (`api/gateway.py:1455`) y se persiste ANTES de llamar
# al motor. Mientras la exclusión se apoyó sólo en esa columna, `{"model": "license"}` compraba
# inmortalidad (ningún predicado levantaba la fila), invisibilidad (la vitrina saca la cadena de
# los dos baldes) y veneno para la cadena. La respuesta fue anclar al `seq`.
#
# **Ronda 2.** El ancla al `seq` tenía un agujero histórico, y está en el historial del repo:
#
#     0a8cda1 (16-jul, US1) · 1a93cf3 (17-jul, US3) · 8e8f705 (17-jul, US4)
#         emit_license_event → guardian_events=[{event_type, license_id, seats_used,
#                                                max_seats, reason, ts}]      ← SIN `seq`
#     9cd7b99 (20-jul, US5)
#         _append_chained    → recién acá aparecen `prev_hash` y `seq`
#
# O sea que hay filas de licencia LEGÍTIMAS, emitidas entre el 16 y el 20 de julio, que no
# traen `seq`. Con el ancla de la ronda 1 caían en clase mortal por su `compliance_status` y el
# purgador **las borraba**: destrucción irreversible de evidencia de licencia causada por
# nuestro propio fix — el incidente de confianza de FR-003 provocado por la defensa y no por el
# ataque. `test_la_licencia_pre_us5_no_la_borra_nadie` es el que clava eso.
#
# El predicado nuevo invierte la pregunta y mira la FORMA de `guardian_events`: se purga lo que
# es demostrablemente tráfico y nada más. La tabla de verdad de `_FORMAS` está MEDIDA contra
# Postgres 16, no inferida, y es el oráculo de esta sección.
#
# **Ronda 3 (dictamen del manager, 14-ago).** Al portón por forma se le había dejado SUMADA la
# condición de la ronda 1, `coalesce(model,'') <> 'license'`, como defensa en profundidad. Cayó,
# y el motivo es que no protegía ni una fila legítima: el emisor de la cadena
# (`licensing/audit_events.py::_append_chained`) es ESCRITOR ÚNICO de ese literal y escribe UNA
# sola forma, que el portón ya excluye por `seq`/`prev_hash`/`event_type`; la otra forma
# legítima es la pre-US5, que el portón excluye por `event_type`. Lo único que la aditiva
# mantenía vivo eran los spoofs YA escritos en la base de un cliente instalado, y les daba
# inmortalidad PERMANENTE — la Capa B tapa lo nuevo, no lo viejo. La frase del dictamen: «la
# exclusión la compra la FORMA, no el literal».
#
# Ese dictamen le pone una obligación nueva a este archivo: si el portón es la ÚNICA defensa de
# la evidencia de licencias, entonces tiene que estar acoplado al emisor real y no a una idea
# nuestra de cómo escribe. Eso es `test_la_forma_que_emite_el_emisor_real_no_es_purgable`, que
# llama a `emit_license_event` y mide el portón EN SQL sobre la fila que quedó.
#
# Los canarios se insertan y se descartan con `rollback`, como los de arriba y por un motivo
# más: una fila `model='license'` que quedara en el dataset la levantaría
# `test_ningun_predicado_devuelve_filas_de_la_cadena_de_licencias` como si fuera un eslabón.


def _eslabon_de_la_021(seq: int = 7) -> dict:
    """El `guardian_events[0]` con la forma EXACTA que persiste `_append_chained` hoy
    (`licensing/audit_events.py:253-262`, o sea la 021 US5 en adelante).

    Se escribe el evento entero y no un `{"seq": …}` pelado a propósito: lo que hay que probar
    es que el eslabón REAL sigue excluido. Con un dict mínimo probaríamos que lo está uno que
    nadie emite.

    Ojo con qué garantiza y qué no: esto es una COPIA de la forma vigente, así que si el emisor
    cambia, esta copia no se entera. Lo que acopla este archivo con el emisor de verdad es
    `test_la_forma_que_emite_el_emisor_real_no_es_purgable`, que llama a `emit_license_event`.
    Esta función existe para poder meter la forma en la tabla de verdad `_FORMAS` junto a las
    demás (que se comparan entre sí y con el gemelo Python), no para sustituir ese acoplamiento.
    """
    return {
        "event_type": "license_loaded",
        "license_id": "sentinel-camara-2026",
        "seats_used": None,
        "max_seats": 300,
        "reason": None,
        "ts": _ahora().isoformat(),
        "prev_hash": "0" * 64,
        "seq": seq,
    }


def _eslabon_pre_us5() -> dict:
    """La forma que el emisor de la 021 persistió entre el 16 y el 20 de julio de 2026.

    Copiada del fuente de aquel momento (`emit_license_event` en 8e8f705): las MISMAS seis
    claves y ninguna más. Sin `prev_hash` y sin `seq`, porque la hash-chain llegó recién con la
    US5 (9cd7b99).

    **Es la excepción legítima a la regla del depto de «no inventar fixtures», y el motivo va
    escrito acá para que no haya que adivinarlo**: esta forma NO la puede volver a generar
    ningún emisor de hoy — `_append_chained` escribe `prev_hash` y `seq` desde 9cd7b99 y no hay
    perilla para que no los escriba—. Es evidencia HISTÓRICA: filas que están en la base de una
    instalación viva y que no se van a mover. Sembrarla llamando al emisor es imposible; la
    única fuente honesta es el fuente de aquel momento (8e8f705), de donde está copiada.

    Y ese es exactamente el motivo por el que el portón no puede depender de la forma vigente
    del emisor: si dependiera, el purgador borraría estas filas. La forma VIGENTE sí se siembra
    llamando al emisor real (`test_la_forma_que_emite_el_emisor_real_no_es_purgable`).
    """
    return {
        "event_type": "license_seat_limit_exceeded",
        "license_id": "sentinel-camara-2026",
        "seats_used": 26,
        "max_seats": 25,
        "reason": "seats en uso por encima del máximo licenciado",
        "ts": _ahora().isoformat(),
    }


def _fila_con(sesion, modelo, guardian_events, estado="blocked_by_policy") -> AuditLog:
    """Fila con el `model` y el `guardian_events` que se le pasen, ya flusheada y releída.

    El resto de las columnas van como las escribe el emisor de la 021 (cero tokens, cero coste,
    `blocked_by_policy`), así lo ÚNICO que separa un caso de otro en esta sección son las dos
    variables que se están midiendo. El estado de BLOQUEO no es decoración: es el que hace grave
    al hallazgo —una fila inmortal que además es un intento impedido de verdad— y el que
    garantiza que la clase esperada (`security_events`) no coincida con el fail-safe.
    """
    fila = AuditLog(
        tenant_id=TENANT, timestamp=_ahora(), model=modelo,
        prompt_tokens=0, completion_tokens=0, cost_usd=0, pii_detected=False,
        compliance_status=estado, latency_ms=0,
        guardian_events=guardian_events,
    )
    sesion.add(fila)
    sesion.flush()
    # `refresh` y no sólo `flush`: en ESTA columna lo que se le pasa al constructor y lo que
    # queda persistido no siempre es lo mismo (ver el caso del JSON `null` en `_FORMAS`), y el
    # gemelo Python del clasificador corre sobre filas LEÍDAS de la base — el purgador arma su
    # rastro con lo que trae la query, no con lo que alguien construyó en memoria. Sin el
    # refresh, el camino Python se estaría midiendo sobre un objeto que no existe en la tabla.
    sesion.refresh(fila)
    return fila


def _fila_que_dice_license(sesion, guardian_events) -> AuditLog:
    """Atajo para el caso más repetido de la sección: `model='license'`."""
    return _fila_con(sesion, MODELO_LICENCIA, guardian_events)


def _levantada_por(sesion, fila) -> list:
    """Las clases cuyo PREDICADO SQL reclama esta fila. Es el camino que BORRA."""
    return [c for c in classifier.clases()
            if sesion.query(AuditLog.id).filter(
                classifier.predicado(c), AuditLog.id == fila.id).count()]


def test_el_eslabon_legitimo_de_la_cadena_sigue_excluido(sesion):
    """La otra mitad de la enmienda, y la que importa primero: endurecer la exclusión no puede
    dejar afuera a un eslabón de verdad.

    Si esto se pusiera rojo, la purga borraría una fila que `verify_chain` relee y el
    deployment se acusaría solo de manipulación — el incidente de confianza de FR-003 causado
    por la defensa, no por el ataque.
    """
    try:
        eslabon = _fila_que_dice_license(sesion, [_eslabon_de_la_021()])

        assert _levantada_por(sesion, eslabon) == [], (
            "Un eslabón REAL de la cadena (con su `seq`) quedó reclamado por una clase de "
            "retención: la purga lo borraría y `verify_chain` leería el hueco como tamper.")
        assert classifier.clase_de(eslabon) is None, (
            "clase_de() le puso clase a un eslabón real: el rastro de la corrida le diría al "
            "auditor que la evidencia de licencias tiene fecha de vencimiento. No la tiene.")
    finally:
        sesion.rollback()


# ── La tabla de verdad del portón, MEDIDA contra Postgres 16 ─────────────────────────
#
# `(nombre, guardian_events, borrable)`. La tercera columna NO se dedujo leyendo el
# clasificador: se midió ejecutando el predicado contra la base, forma por forma. Que el oráculo
# sea la base y no el código es lo que le da a este bloque la posibilidad de contradecir a la
# implementación — una tabla copiada del fuente estaría de acuerdo con cualquier cosa que el
# fuente diga, incluida la equivocada.
_FORMAS = [
    # ── Lo que SÍ se purga: las formas con las que el producto escribe TRÁFICO ──
    #
    # La lista vacía es el caso mayoritario: el pedido que no disparó ningún guardián
    # (`audit_service.py:361` persiste `guardian_events or []`, y el INSERT de `/internal/audit`
    # ni nombra la columna y toma el `DEFAULT '[]'` de la 003).
    ("lista vacía", [], True),
    # Un disparo local, tal cual lo arma el plano chat (`guardian`/`action`/`detail`).
    ("evento de guardián real", [{"type": "ES_NIF", "count": 2}], True),
    # El sobre con el que `chat.py:559-561` guarda el blob del MOTOR. Es la pieza que sostiene
    # todo esto: sin el sobre, la posición 0 de una fila de tráfico la elegiría el upstream y
    # bastaría con que contestara un `event_type` para comprarse la inmortalidad.
    ("el sobre del motor", [{"upstream": [{"type": "SECRET_DETECTION"}]}], True),
    # Objeto sin ninguna de las tres marcas: no hay nada que lo haga parecer un eslabón.
    ("objeto vacío", [{}], True),
    # El `seq` empujado una posición. Manda el PRIMER evento, que es el único que releen los
    # dos lectores de la cadena (`chained_entries`, `audit_events.py:130`). Si el predicado
    # barriera la lista entera, protegería filas que la cadena ni mira: inmortalidad regalada.
    ("seq en el segundo evento", [{"type": "PII_MASKING"}, {"seq": 1}], True),

    # ── Lo que NO se purga ──
    #
    # SQL NULL de verdad. La columna es nullable (`003_audit_guardian_events.py:18`: JSONB con
    # DEFAULT '[]', sin NOT NULL), así que la fila existe. Todo lo que se le pregunte al jsonb
    # da NULL; el portón contesta FALSE igual (fail-closed) y sin devolver NULL.
    ("SQL NULL", null(), False),
    # El JSON `null`, que NO es lo mismo y por eso va aparte: pasarle `None` a esta columna no
    # escribe SQL NULL, porque el tipo JSON de SQLAlchemy trae `none_as_null=False` por default
    # y persiste el literal `'null'::jsonb`. Se ve en que `jsonb_typeof` devuelve `'null'` en
    # vez de NULL. Hacen falta los DOS sembrados: sólo el de arriba muerde el trivalente.
    ("el JSON `null`", None, False),
    # El eslabón vigente de la cadena (021 US5 en adelante).
    ("eslabón de la 021", [_eslabon_de_la_021()], False),
    # **El caso de esta ronda.** Licencia LEGÍTIMA con la forma que el emisor persistió entre el
    # 16 y el 20 de julio: `event_type` sí, `seq` y `prev_hash` no. Tiene test propio con el
    # daño escrito (`test_la_licencia_pre_us5_no_la_borra_nadie`); acá figura para que la tabla
    # de verdad esté completa y para que los dos gemelos se comparen también sobre ella.
    ("licencia pre-US5", [_eslabon_pre_us5()], False),
    # Tráfico con un blob que TIENE forma de eslabón. Fail-closed: no se borra. El costo está
    # asumido y escrito en `test_el_trafico_con_forma_de_eslabon_tampoco_se_borra`.
    ("blob forjado", [{"seq": 1, "prev_hash": "0" * 64, "event_type": "license_loaded"}], False),
    # Una sola de las tres marcas alcanza: las tres van con OR, no con AND. Si fueran AND, un
    # eslabón al que le faltara una clave —justamente el caso pre-US5— quedaría desprotegido.
    ("sólo prev_hash", [{"prev_hash": "0" * 64}], False),
    # La clave como ELEMENTO y no como clave. Ojo con este: es el ÚNICO no-objeto que quedaría
    # protegido igual sin el `jsonb_typeof(...) = 'object'`, porque `?` sobre un jsonb string
    # compara el string ENTERO y ahí coincide. Está sembrado para que se vea la casualidad, no
    # para probar la guarda — la guarda la prueban `un string que no coincide` y `un número
    # como primer evento`, que son las dos que sí se dan vuelta si alguien la saca.
    ("la clave como string suelto", ["seq"], False),
    # El string que NO coincide es el que muerde: las tres marcas contestan «no la tengo», así
    # que sin el chequeo de tipo esta fila pasaría por tráfico. Del lado Python el disfraz entra
    # por `"seq" in "consequence"`, que es `True` porque `in` sobre un string busca SUBCADENA —
    # o sea que los dos gemelos llegan al mismo «no es tráfico» por caminos opuestos, y por eso
    # los dos necesitan su guarda de tipo. Es el mismo borde que el HALLAZGO 2 del gate cazó en
    # los lectores de la cadena (`tests/integration/test_retencion_dataset_abusivo.py`).
    ("un string que no coincide", ["consequence"], False),
    # Un objeto en vez de una lista: `{"seq": 1} -> 0` es NULL en SQL (el índice entero no
    # aplica a un objeto), y en Python `eventos[0]` sería un KeyError. Ninguno de los dos puede
    # reventar ni dejar pasar.
    ("un objeto en vez de una lista", {"seq": 1}, False),
    # Un escalar como primer evento: ni objeto ni nada que se le parezca.
    ("un número como primer evento", [7], False),
]

_IDS_FORMAS = [nombre for nombre, _eventos, _borrable in _FORMAS]


def _valor_del_porton(sesion, fila):
    """El valor CRUDO que devuelve el predicado estructural en SQL para esta fila.

    Crudo y no «¿la levanta el WHERE?» a propósito: un `WHERE` colapsa NULL y FALSE en «no
    aparece», y la bivalencia —que el predicado nunca devuelva NULL— es justamente una de las
    tres propiedades del contrato. Medida a través de un `WHERE` sería invisible.
    """
    return sesion.query(
        classifier.es_trafico_demostrable().label("borrable")
    ).filter(AuditLog.id == fila.id).scalar()


@pytest.mark.parametrize("nombre,eventos,borrable", _FORMAS, ids=_IDS_FORMAS)
def test_el_porton_estructural_dice_lo_que_se_midio_contra_postgres(
        sesion, nombre, eventos, borrable):
    """**El test que define esta ronda.** La forma de `guardian_events` decide, y nada más.

    La fila va con `model='gpt-4o'` a propósito: acá se mide el predicado ESTRUCTURAL solo. Si
    se sembrara con `license`, la condición aditiva sobre `model` taparía el resultado y el
    bloque entero quedaría verde aunque alguien borrara las tres marcas del clasificador —el
    modo de falla más caro que tiene un test, el que pasa por el motivo equivocado.

    El `is` y no `==`: `esperado` es `True`/`False`, así que la identidad exige además que el
    valor sea un booleano de verdad y no un `None` que en un `assert` pasaría por falso.
    """
    try:
        fila = _fila_con(sesion, "gpt-4o", eventos)
        assert _valor_del_porton(sesion, fila) is borrable, (
            f"Con guardian_events = «{nombre}» el portón contestó distinto de lo medido contra "
            f"Postgres (esperado: {borrable}). Si pasó de False a True, el clasificador dejó de "
            "reconocer una forma de eslabón y el purgador borraría evidencia de licencia que no "
            "se reconstruye. Si pasó de True a False, dejó de reconocer tráfico y esas filas se "
            "vuelven inmortales: la promesa del día 91 no las alcanza.")
    finally:
        sesion.rollback()


@pytest.mark.parametrize("nombre,eventos,borrable", _FORMAS, ids=_IDS_FORMAS)
def test_el_porton_estructural_nunca_devuelve_null(sesion, nombre, eventos, borrable):
    """**Bivalencia**, la propiedad que permite que el predicado no lleve `coalesce(…, false)`.

    En SQL, un predicado que devuelve NULL no es «falso»: es «no se sabe», y en un `WHERE` se
    comporta como falso mientras que negado sigue siendo NULL. El clasificador se apoya en que
    éste nunca devuelve NULL —medido sobre todas las formas de `_FORMAS`— y por eso lo escribe
    pelado. Si alguien lo envolviera «por las dudas», la envoltura no cambiaría ninguna
    respuesta de hoy y taparía para siempre la regresión que este test existe para ver.

    Que el daño de un NULL esté acotado igual (el portón se consume en POSITIVO, así que un
    NULL no borra) no vuelve prescindible esta afirmación: acotado no es lo mismo que ausente, y
    un portón que empieza a contestar «no sé» está roto aunque falle hacia el lado bueno.
    """
    try:
        fila = _fila_con(sesion, "gpt-4o", eventos)
        assert _valor_del_porton(sesion, fila) is not None, (
            f"Con guardian_events = «{nombre}» el portón devolvió NULL. Dejó de ser bivaluado: "
            "o se le agregó una comparación que no es total, o se sacó una de las guardas de "
            "forma que hacen que el `->` de Postgres no propague su NULL.")
    finally:
        sesion.rollback()


@pytest.mark.parametrize("nombre,eventos,borrable", _FORMAS, ids=_IDS_FORMAS)
def test_los_dos_gemelos_del_porton_dicen_lo_mismo_de_cada_forma(
        sesion, nombre, eventos, borrable):
    """El purgador BORRA con el predicado SQL y EXPLICA su corrida con el camino Python.

    Si los dos se separan, el `purge_log` le miente al auditor sobre qué se borró — y en esta
    columna la tentación de separarse es real: el `->` de Postgres devuelve NULL donde Python
    levanta `TypeError`/`IndexError`, y el `?` de Postgres compara el string entero donde el
    `in` de Python busca subcadena. Cada guarda del gemelo Python es uno de esos bordes escrito
    a mano.

    Se compara sobre la fila LEÍDA de la base y no sobre la construida en memoria: en esta
    columna lo que se le pasa al constructor y lo que queda persistido no siempre es lo mismo
    (el JSON `null` es el caso), y el purgador clasifica lo que trae la query.
    """
    try:
        fila = _fila_con(sesion, "gpt-4o", eventos)
        en_memoria = classifier.es_trafico_demostrable_en_memoria(fila)

        assert isinstance(en_memoria, bool), (
            f"Con guardian_events = «{nombre}» el gemelo Python devolvió "
            f"{en_memoria!r} ({type(en_memoria).__name__}) en vez de un bool. Un `None` acá "
            "sería falsy por accidente y no por decisión: el día que la respuesta correcta sea "
            "`True`, el bug es invisible.")
        assert en_memoria is _valor_del_porton(sesion, fila), (
            f"Con guardian_events = «{nombre}» los dos gemelos del portón no dicen lo mismo. "
            "El purgador borraría según uno y le explicaría al auditor con el otro.")
    finally:
        sesion.rollback()


def test_la_licencia_pre_us5_no_la_borra_nadie(sesion):
    """**El agujero que esta ronda vino a cerrar**, y el más caro de los dos.

    Entre el 16 y el 20 de julio de 2026 el emisor de la 021 escribió filas de licencia
    LEGÍTIMAS que no traen `seq`: la hash-chain llegó recién con la US5 (9cd7b99, 20-jul), y
    hasta entonces `emit_license_event` persistía `[{event_type, license_id, seats_used,
    max_seats, reason, ts}]` (0a8cda1, 1a93cf3, 8e8f705). Con el ancla de la ronda anterior
    —`model='license'` **y** `seq`— esas filas no eran «de la cadena»: caían en clase mortal por
    su `compliance_status` y el purgador **las borraba**. Evidencia de licencia destruida sin
    vuelta atrás, causada por nuestro propio fix.

    Sembrada a MANO, y es la excepción legítima a la regla del depto de «no inventar fixtures»:
    esta forma no la emite el emisor de hoy y no se puede volver a generar llamándolo. Es
    evidencia HISTÓRICA — filas que están en la base de una instalación viva y que no se van a
    mover—, y por eso el fuente de aquel momento (8e8f705) es el único oráculo posible. La
    forma VIGENTE, en cambio, se siembra llamando al emisor real: ver
    `test_la_forma_que_emite_el_emisor_real_no_es_purgable`.

    Se afirman las DOS mitades:

    1. la fila real (con `model='license'`) no la reclama ninguna clase;
    2. **la MISMA forma con otro `model` tampoco**. Este segundo assert existía porque hasta el
       14-ago la condición aditiva sobre `model` podía estar salvando la fila sola y dejar el
       test verde con la marca `event_type` borrada. La aditiva cayó, así que hoy los dos
       asserts miden lo mismo por el mismo camino y el primero ya no puede pasar por el motivo
       equivocado. Se dejan los dos igual: el segundo es el que documenta que la protección
       viene de la FORMA y sobrevive a que la columna `model` la escriba otro.
    """
    try:
        historica = _fila_que_dice_license(sesion, [_eslabon_pre_us5()])
        assert _levantada_por(sesion, historica) == [], (
            "Una fila de licencia legítima anterior a la 021 US5 quedó reclamada por una clase "
            "de retención: el purgador la borraría. Es evidencia de licencia que no se "
            "reconstruye, destruida por la defensa y no por el ataque (FR-003).")
        assert classifier.clase_de(historica) is None, (
            "clase_de() le puso clase a una licencia pre-US5: el rastro de la corrida le diría "
            "al auditor que esa evidencia tiene fecha de vencimiento. No la tiene.")

        por_la_forma = _fila_con(sesion, "gpt-4o", [_eslabon_pre_us5()])
        assert _levantada_por(sesion, por_la_forma) == [], (
            "La forma pre-US5 sólo queda protegida cuando la fila además dice `license`: o sea "
            "que la protección la está dando la condición ADITIVA sobre `model` y no el portón "
            "estructural. Falta la marca `event_type` en el clasificador — y con ella falta la "
            "única defensa que no depende de una columna que escribe el inspeccionado.")
        assert classifier.clase_de(por_la_forma) is None
    finally:
        sesion.rollback()


def test_la_exclusion_la_compra_la_forma_no_el_literal(sesion):
    """**El cambio de comportamiento del dictamen del 14-ago**, afirmado donde se ve.

    Hasta ese día el portón llevaba SUMADA la condición `coalesce(model,'') <> 'license'` y
    este test exigía lo contrario de lo que exige ahora: que una fila con el literal reservado
    NO fuera purgable, aunque su `guardian_events` fuera el de cualquier tráfico. La aditiva
    cayó, y el motivo medido es que no protegía ninguna fila legítima:

    * el emisor de la cadena es escritor único de `model='license'` y escribe UNA sola forma,
      que el portón excluye por `seq`/`prev_hash`/`event_type` (lo clava
      `test_la_forma_que_emite_el_emisor_real_no_es_purgable`, llamando al emisor de verdad);
    * la otra forma legítima es la pre-US5, que el portón excluye por `event_type` (lo clava
      `test_la_licencia_pre_us5_no_la_borra_nadie`);
    * lo único que la aditiva mantenía vivo eran los SPOOFS `model='license'` ya escritos en la
      base de una instalación, y les daba inmortalidad PERMANENTE: la Capa B
      (`gateway.sanear_modelo_declarado`) impide los nuevos, no limpia los viejos.

    O sea que la aditiva era costo puro, y esto es lo que se compró sacándola: el spoof viejo
    deja de ser inmortal y se extingue con las corridas de purga.

    Los dos asserts de abajo son los dos lados de la misma moneda —el literal sin la forma NO
    protege, y el centinela de la Capa B sigue siendo una fila mortal como cualquier otra—, y
    el segundo además es la red contra el `LIKE 'license%'` que todavía nadie escribió (ojo:
    en LIKE el `_` es comodín, así que `'license_%'` tampoco esquiva al centinela).
    """
    try:
        # `[]` es la forma con la que el producto persiste el TRÁFICO que no disparó ningún
        # guardián; el emisor de la cadena nunca la escribió. O sea: esto es un spoof.
        spoof = _fila_que_dice_license(sesion, [])
        assert _levantada_por(sesion, spoof) == [CLASE_SECURITY_EVENTS], (
            "Una fila que dice `license` con forma de TRÁFICO (`guardian_events=[]`) volvió a "
            "ser inmortal: alguien devolvió la condición aditiva sobre `model` al portón. Esa "
            "condición no protege ninguna fila legítima —las dos formas del emisor las protege "
            "la FORMA— y le regala inmortalidad permanente a los spoofs que ya estén en la base "
            "de un cliente instalado. Dictamen del manager, 14-ago.")
        assert classifier.clase_de(spoof) == CLASE_SECURITY_EVENTS, (
            "El gemelo Python sigue tratando el literal como exclusión: el purgador borraría "
            "la fila y el rastro de la corrida diría que no la tocó.")

        centinela = _fila_con(sesion, "license__cliente", [])
        assert _levantada_por(sesion, centinela) == [CLASE_SECURITY_EVENTS], (
            "El centinela de la Capa B dejó de ser mortal: alguien comparó por prefijo en vez "
            "de por igualdad, y la fila saneada quedó tan inmortal como la que el saneo vino a "
            "desalojar.")
        assert classifier.clase_de(centinela) == CLASE_SECURITY_EVENTS
    finally:
        sesion.rollback()


def test_el_trafico_con_forma_de_eslabon_tampoco_se_borra(sesion):
    """El precio del fail-closed, afirmado en vez de disimulado.

    Una fila de TRÁFICO cuyo primer evento traiga una de las tres marcas no la borra nadie. Es
    la dirección elegida a conciencia: entre dejar viva una fila de metadata de más y borrar
    algo que PODRÍA ser un eslabón de la cadena, la spec elige lo primero, porque lo segundo no
    se reconstruye (`verify_chain` lee el hueco como manipulación y el true-up pierde
    historial). Va con test propio para que la decisión sea visible y discutible, no un efecto
    lateral que alguien descubra leyendo el predicado.

    Que hoy ningún pedido pueda producir esa fila NO es suerte: los tres escritores vivos dejan
    la columna como array y la posición 0 es de la casa —`chat.py:559-561` mete el blob del
    motor dentro de un sobre nuestro—. Si ese sobre se cayera, este test dejaría de describir un
    borde teórico y pasaría a describir la nueva forma de comprarse la inmortalidad.
    """
    try:
        forjada = _fila_con(sesion, "gpt-4o", [{"event_type": "lo_que_sea", "count": 1}])
        assert _levantada_por(sesion, forjada) == [], (
            "El portón dejó purgable una fila cuyo primer evento tiene forma de eslabón. Si es "
            "un cambio deliberado, se discute acá: lo que se está aceptando es que el purgador "
            "borre filas que podrían ser evidencia de licencia.")
        assert classifier.clase_de(forjada) is None
    finally:
        sesion.rollback()


# ══ Las DOS preguntas: `dice_licencia()` (vitrina) vs. el portón (purga) ═════════════
#
# Dictamen del manager, 14-ago, textual:
#
#     purga = por forma (irreversible → no confía en nadie); vitrina = por literal (reversible
#     → y el literal ya es nuestro gracias a la Capa B)
#
# Los tres tests de abajo miden esa separación sobre las PRIMITIVAS, que es donde se define el
# criterio; que la pantalla lo siga es lo que verifican los tests de paridad de la vitrina
# (`tests/integration/test_audit_paridad_clasificador.py`, que no es de este archivo).


def _visibles_para_la_vitrina(sesion) -> set:
    """Los ids que la vitrina lista: su exclusión de la cadena es `~dice_licencia()`."""
    return {f.id for f in sesion.query(AuditLog.id).filter(~classifier.dice_licencia())}


def test_la_vitrina_excluye_por_literal_y_la_purga_por_forma(sesion):
    """Las dos preguntas sobre las MISMAS cuatro filas, en la misma corrida.

    Ponerlas juntas es el punto: cada fila contesta distinto a «¿se ve?» y a «¿se borra?», y
    leerlas de a una deja la impresión de que una de las dos primitivas está rota.

    | fila                              | ¿se ve? (`~dice_licencia`) | ¿se borra? (portón) |
    |-----------------------------------|----------------------------|---------------------|
    | eslabón vigente (021 US5)         | no                         | no                  |
    | licencia pre-US5 (`event_type`)   | no                         | no                  |
    | spoof `license` + `[]`            | no  ← NOTA heredada        | **SÍ**              |
    | centinela `license__cliente`      | sí                         | sí                  |

    El renglón del spoof es el que hay que leer despacio. Que NO se vea es comportamiento
    heredado de `main` —la vitrina excluye por literal, y el spoof declara el literal— y no una
    regresión de esta ronda; lo que cambió es que ahora ES purgable, así que el spoof viejo de
    una instalación se extingue con las corridas de purga en vez de quedarse invisible para
    siempre. Está anotado como NOTA no bloqueante en el docstring de `dice_licencia()`.

    El renglón del centinela es la red contra el `LIKE 'license%'` que todavía nadie escribió:
    el lugar donde la Capa B deja el intento a la VISTA no puede convertirse en el segundo
    escondite, estrenado por la defensa.
    """
    try:
        eslabon = _fila_que_dice_license(sesion, [_eslabon_de_la_021()])
        pre_us5 = _fila_que_dice_license(sesion, [_eslabon_pre_us5()])
        spoof = _fila_que_dice_license(sesion, [])
        centinela = _fila_con(sesion, "license__cliente", [])

        visibles = _visibles_para_la_vitrina(sesion)

        assert eslabon.id not in visibles, (
            "El eslabón legítimo entró al universo de la vitrina: «se venció la licencia del "
            "deployment» aparecería junto a los intentos bloqueados de los usuarios.")
        assert pre_us5.id not in visibles, (
            "Una licencia LEGÍTIMA pre-US5 volvió a aparecer en los baldes del officer, "
            "mezclada con intentos de fuga. Es exactamente lo que el dictamen del 14-ago vino a "
            "cerrar volviendo al literal: con `~es_licencia()` esta fila se mostraba porque no "
            "trae `seq`.")
        assert spoof.id not in visibles, (
            "Cambió el criterio de la vitrina. No es que este test defienda que el spoof esté "
            "escondido —es herencia de `main` y está anotado como NOTA—, pero si la exclusión "
            "dejó de ser por literal, quien lo decida tiene que venir a discutirlo acá.")
        assert centinela.id in visibles, (
            "El centinela de la Capa B dejó de ser visible: alguien excluyó por prefijo "
            "(`LIKE 'license%'`, y ojo que en LIKE el `_` es comodín, así que `'license_%'` "
            "hace lo mismo) y el intento que la capa B registró a propósito desapareció del "
            "reporte.")

        # …y la otra pregunta, sobre las mismas cuatro filas.
        assert _levantada_por(sesion, eslabon) == []
        assert _levantada_por(sesion, pre_us5) == []
        assert _levantada_por(sesion, spoof) == [CLASE_SECURITY_EVENTS], (
            "El spoof volvió a ser inmortal: si la vitrina lo esconde Y la purga no lo toca, la "
            "fila desaparece del reporte para siempre. Ese par es justamente lo que el dictamen "
            "del 14-ago rompió sacando la condición aditiva sobre `model`.")
        assert _levantada_por(sesion, centinela) == [CLASE_SECURITY_EVENTS]
    finally:
        sesion.rollback()


def test_por_que_la_vitrina_no_puede_usar_es_licencia(sesion):
    """La MEDICIÓN que sostiene el dictamen (b), escrita como test y no como afirmación.

    Las dos primitivas no son intercambiables, y la fila que las separa es la licencia
    LEGÍTIMA pre-US5: trae `event_type` y NO trae `seq`.

    * `dice_licencia()` (literal pelado) la reconoce ⇒ la vitrina la saca de los baldes;
    * `es_licencia()` (literal **y** `seq`) NO la reconoce ⇒ con esa exclusión la fila se le
      muestra al officer entre los «bloqueados», mezclada con los intentos de fuga de los
      usuarios. Ese es el `total=1` donde `main` daba `0`.

    Si algún día `es_licencia()` empieza a contestar lo mismo que `dice_licencia()` sobre esta
    fila, este test se pone rojo — y tiene que ponerse: significaría que la primitiva de
    «eslabón VERIFICABLE» dejó de pedir la marca que la hace verificable.
    """
    try:
        pre_us5 = _fila_que_dice_license(sesion, [_eslabon_pre_us5()])

        def contesta(predicado):
            return sesion.query(predicado.label("v")).filter(
                AuditLog.id == pre_us5.id).scalar()

        assert contesta(classifier.dice_licencia()) is True, (
            "`dice_licencia()` dejó de reconocer una fila que dice `license`: la vitrina "
            "mostraría evidencia de licencia entre los bloqueos de los usuarios.")
        assert contesta(classifier.es_licencia()) is False, (
            "`es_licencia()` empezó a aceptar una fila SIN `seq`. Dejó de significar «eslabón "
            "verificable» —que es lo único que esa primitiva sabe contestar y las otras dos "
            "no— y pasó a ser un duplicado de `dice_licencia()`.")
    finally:
        sesion.rollback()


def test_dice_licencia_compara_por_igualdad_exacta(sesion):
    """La primitiva del literal no es un prefijo ni un `LIKE`, y eso hay que clavarlo.

    Es la misma red que ya existe para el centinela, dicha sobre la primitiva: el día que
    alguien la relaje a `LIKE 'license%'` «para tener todo junto», el centinela
    `license__cliente` —el lugar donde la Capa B deja el intento a la VISTA— se convierte en el
    segundo escondite. Y ojo con la variante que parece más prolija: en LIKE el `_` es comodín
    de un carácter, así que `'license_%'` agarra al centinela igual.

    Las variantes de caja y espacios las desalojan los TRES escritores vivos: desde este PR,
    `api/chat.py` también sanea (`_modelo_auditable` → `gateway.sanear_modelo_declarado`, que
    compara `strip().casefold()`), así que hoy no queda ningún camino por el que `License`
    llegue a la columna. El caso se clava igual, y a propósito: la primitiva tiene que seguir
    diciendo que una fila que dice `License` NO es la cadena, para las filas que ya existan en
    bases instaladas y para el día que aparezca un cuarto escritor.
    """
    casos = [
        ("license", True, "el literal exacto"),
        ("license__cliente", False, "el centinela de la Capa B"),
        ("licenses", False, "un prefijo no alcanza"),
        ("License", False, "otra caja no es el literal"),
        ("LICENSE", False, "otra caja no es el literal"),
        (" license ", False, "con espacios no es el literal"),
        ("gpt-4o", False, "un modelo cualquiera"),
    ]
    try:
        for modelo, esperado, por_que in casos:
            fila = _fila_con(sesion, modelo, [])
            valor = sesion.query(classifier.dice_licencia().label("v")).filter(
                AuditLog.id == fila.id).scalar()
            assert valor is esperado, (
                f"`dice_licencia()` contestó {valor!r} para model={modelo!r} ({por_que}); se "
                f"esperaba {esperado}. Si pasó a TRUE de más, la vitrina esconde tráfico que el "
                "officer tiene que ver; si pasó a FALSE para el literal exacto, la cadena vuelve "
                "a mezclarse con los intentos bloqueados de los usuarios.")
    finally:
        sesion.rollback()


# ══ TEST VERDUGO: el emisor real acoplado al portón ══════════════════════════════════


def _ultimas_filas_de_licencia(sesion, ids_previos: set) -> list:
    return [f for f in sesion.query(AuditLog).filter(
        AuditLog.model == MODELO_LICENCIA).all() if f.id not in ids_previos]


def test_la_forma_que_emite_el_emisor_real_no_es_purgable(sesion):
    """**El test verdugo (requisito del manager, dictamen 14-ago).**

    Desde que cayó la condición aditiva sobre `model`, la FORMA de `guardian_events` es la
    ÚNICA defensa de la evidencia de licencias en la purga. Un portón que se mide contra una
    forma escrita a mano en el test no defiende nada: defiende una idea NUESTRA de cómo escribe
    el emisor, y el día que el emisor cambie —le sacan `event_type`, lo renombran— el test
    sigue verde y las filas de licencia empiezan a morir en la purga de un cliente.

    Por eso acá no hay fixture: se llama a `emit_license_event` (el emisor REAL de la 021,
    `licensing/audit_events.py`) y se mide el portón EN SQL sobre la fila que quedó en la tabla.
    Es el mismo criterio con el que `test_audit_filtro_estado.py` siembra su eslabón, y por el
    mismo motivo: una forma que sólo existe en el test es una forma que nadie garantiza que el
    producto emita.

    Se afirman tres cosas y las tres son necesarias:

    1. el emisor dejó UNA fila y dice `license` — si no, no estamos midiendo lo que creemos;
    2. el portón estructural contesta **False** sobre ella, medido en SQL y no con el gemelo
       Python: el que borra es el `WHERE`;
    3. ninguna clase la reclama y `clase_de()` la deja en `None` — los dos caminos de acuerdo.

    Y una cuarta que es la que acopla de verdad: el primer evento trae al menos una de las
    marcas que el portón mira. Sin ese assert, un emisor que cambiara de forma podría seguir
    dando False por accidente (por ejemplo escribiendo un jsonb que no es lista) y el test no
    distinguiría «protegida por la marca» de «protegida por casualidad».

    Limpieza: `emit_license_event` hace `commit()` —avanza el head de la cadena en la misma
    transacción, no se le puede pedir que no lo haga—, así que este test no puede apoyarse en
    el `rollback` como los demás. Borra lo que emitió (filas + singleton) y vuelve a commitear:
    el `sesion` es de módulo y una fila `license` olvidada la levantaría
    `test_ningun_predicado_devuelve_filas_de_la_cadena_de_licencias`.
    """
    from src.licensing.audit_events import EVENT_SEAT_LIMIT, emit_license_event
    from src.models.license_state import LicenseRuntimeState

    previos = {f.id for f in sesion.query(AuditLog.id).filter(
        AuditLog.model == MODELO_LICENCIA)}
    # La cadena arranca en cero para que el emisor escriba EXACTAMENTE una fila. Con la fila
    # singleton ya existente y génesis 'unlicensed', el primer `license_id` dispararía ADEMÁS
    # el evento de anclaje diferido (`audit_events.py:229-236`) y el `len(...) == 1` de abajo
    # se caería por el motivo equivocado.
    sesion.query(LicenseRuntimeState).delete()
    sesion.commit()
    try:
        emit_license_event(sesion, EVENT_SEAT_LIMIT, license_id="lic_verdugo_0001",
                           seats_used=26, max_seats=25,
                           reason="seats en uso por encima del máximo licenciado")

        emitidas = _ultimas_filas_de_licencia(sesion, previos)
        assert len(emitidas) == 1, (
            f"`emit_license_event` dejó {len(emitidas)} filas `model='license'` y este test "
            "mide UNA. Si el emisor empezó a escribir más de una por evento, hay que decidir "
            "acá cuál se mide antes de seguir.")
        fila = emitidas[0]

        primero = fila.guardian_events[0]
        marcas_presentes = [m for m in classifier.MARCAS_DE_LA_CADENA if m in primero]
        assert marcas_presentes, (
            "**El emisor cambió de forma y sus filas se volvieron purgables — una purga de "
            "cliente las borraría.** El primer `guardian_event` que escribe "
            "`licensing/audit_events.py::_append_chained` ya no trae ninguna de las marcas que "
            f"el portón mira ({list(classifier.MARCAS_DE_LA_CADENA)}); lo que trae hoy es "
            f"{sorted(primero)}. Desde el dictamen del 14-ago esa forma es la ÚNICA defensa de "
            "la evidencia de licencias: no hay condición sobre `model` debajo que la salve.")

        assert _valor_del_porton(sesion, fila) is False, (
            "**El emisor cambió de forma y sus filas se volvieron purgables — una purga de "
            "cliente las borraría.** El portón estructural, evaluado EN SQL sobre la fila que "
            "acaba de escribir `emit_license_event`, contestó que es tráfico borrable. "
            "`verify_chain` leería el hueco como manipulación y el true-up perdería historial: "
            "es el incidente de confianza de FR-003 provocado por la defensa, no por el ataque.")

        assert _levantada_por(sesion, fila) == [], (
            "Una clase de retención reclama la fila que acaba de emitir el emisor real de la "
            "021: el purgador la borraría en la próxima corrida.")
        assert classifier.clase_de(fila) is None, (
            "El gemelo Python le puso clase a la fila del emisor real: el rastro de la corrida "
            "le diría al auditor que la evidencia de licencias tiene fecha de vencimiento.")
    finally:
        # No hay rollback posible: el emisor ya commiteó. Se deshace a mano.
        for fila in _ultimas_filas_de_licencia(sesion, previos):
            sesion.delete(fila)
        sesion.query(LicenseRuntimeState).delete()
        sesion.commit()
