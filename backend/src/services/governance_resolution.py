"""Resolución de gobernanza por tenant (spec 027, T009).

La cascada la resuelve la librería PURA (``governance_catalog.resolve_profile``); lo que
falta —y es lo único que vive acá— es **leer las decisiones del tenant** y entregárselas
ya leídas. Mismo reparto que la cascada de contexto de la 013
(``context_resolution.py``): la resolución es una función determinista sin DB, y el I/O
queda del lado del caller, que es donde ya hay sesión.

Por qué importa que la lectura esté en UN solo lugar: la única query de este módulo
**filtra siempre por ``tenant_id``**. El antipatrón que no se replica tiene nombre y
línea: ``get_or_create_default_policy`` lee la postura con
``db.query(SecurityPolicy).first()`` —sin filtrar tenant ni ``is_active``
(``get_or_create_default_policy`` de ``api/policy.py``, repetido en ``get_active_policy``/``update_active_policy``/``delete_policy`` y clonado en ``_active_policy`` de ``api/costs.py``)—, así que la
política de un tenant puede resolverse con datos de otro. Colgar gobernanza de una
lectura así heredaría el bug (D2), y acá el dato que se lee decide **qué capas de
seguridad corren**. Constitución III: toda query de este archivo lleva el filtro de
tenant, sin excepción.

**Ausencia de datos ≠ ausencia de postura** (SC-007): un tenant recién creado, sin una
sola fila en ``governance_profiles``, ya tiene postura completa y explícita —piso activo
+ ``pii_masking=on`` + el resto ``off``— porque el último nivel de la cascada es el
``default_decision`` del registry, no una fila sembrada. Por eso la migración 012 no
siembra nada: sembrar el default de producto lo volvería un dato borrable.

Fail-closed en la lectura: cualquier motivo por el que no haya filas (tenant sin
identificar, id inválido, sesión ausente) devuelve el **conjunto vacío**, y el conjunto
vacío resuelve a los defaults de producto. Las relajaciones (``decision='off'`` sobre una
capa opcional) requieren una fila explícita, así que "no pude leer" nunca puede relajar
nada: degrada hacia más protección, jamás hacia menos.
"""
import logging
import uuid
from typing import Iterable, Mapping, Optional, Sequence, Tuple

from ..models.governance import GovernanceProfile
from .governance_catalog import OFF, ON, Profile, resolve_profile, row_get

logger = logging.getLogger("basa-secure-gateway.governance")

# La única capa que hoy declara override por-Connection: absorbe el toggle
# ``redact_enabled`` de la 013 como su decisión de nivel Connection (D8, absorber sin
# derogar). Vive acá y no como literal disperso para que agregar una segunda capa con
# override sea un cambio en un solo lugar.
_CONNECTION_OVERRIDE_LAYER = "pii_masking"


def _normalize_tenant_id(tenant_id) -> Optional[uuid.UUID]:
    """``UUID`` válido, o ``None``. Un id basura NO se propaga a la query: se descarta y
    la postura cae a los defaults de producto (fail-closed). Levantar acá convertiría un
    dato sucio en un 500 en el camino caliente de cada pedido."""
    if isinstance(tenant_id, uuid.UUID):
        return tenant_id
    if isinstance(tenant_id, str):
        try:
            return uuid.UUID(tenant_id)
        except ValueError:
            logger.warning("governance: tenant_id no parseable, se usan defaults de producto")
            return None
    return None


def load_tenant_decisions(db, tenant_id) -> Tuple[GovernanceProfile, ...]:
    """Las filas de decisión del tenant — **la única query de la feature**.

    Devuelve las filas crudas: el resolutor acepta objetos ORM tal cual (no hace falta
    traducirlas a dicts) y ya descarta por su cuenta las que no sirven —``layer_key``
    fuera del registry o de ``tier=floor``, ``scope_type`` fuera del enum—, de modo que
    una fila contrabandeada por SQL directo, saltándose el 422 del router admin, queda
    **inerte** (data-model §1.4: SC-004 es estructural).

    No se filtra por ``scope_type`` ni por capa: son ~pocas filas por tenant y traerlas
    todas de una evita N queries por capa en el camino caliente. Tampoco se escribe nada
    —ni un ``get_or_create``—: leer la postura jamás debe crear filas, porque una fila
    creada por una lectura es un default que después alguien puede borrar.
    """
    tenant = _normalize_tenant_id(tenant_id)
    if db is None or tenant is None:
        return ()
    return tuple(
        db.query(GovernanceProfile)
        .filter(GovernanceProfile.tenant_id == tenant)   # Constitución III — SIEMPRE
        .all()
    )


def _rows_of_tenant(rows, tenant: Optional[uuid.UUID]) -> Tuple:
    """Descarta toda fila que no sea del tenant recibido — el filtro de tenant, otra vez.

    Existe por el hallazgo de la verificación adversarial del Foundational: el parámetro
    ``decisions=`` de ``resolve_tenant_profile`` **saltea la query**, que era el único
    lugar donde vivía el filtro de Constitución III. Un call-site de la US2 que cachee
    filas por proceso (que es justo para lo que existe el parámetro) resolvería la postura
    del tenant A con las relajaciones del tenant B: exactamente el bug de
    ``get_or_create_default_policy`` que este módulo dice no estar replicando. El filtro
    tiene que estar **dentro** del resolutor de tenant, no en una de sus dos ramas.

    Sin tenant legible se descarta **todo**: no se puede afirmar la pertenencia de ninguna
    fila, y el conjunto vacío resuelve a los defaults de producto. Se descarta en vez de
    levantar porque esto corre en el camino caliente de cada pedido, y porque descartar
    solo puede quitar relajaciones — degrada hacia más protección, jamás hacia menos.
    """
    propias, ajenas = [], 0
    for row in rows:
        if _normalize_tenant_id(row_get(row, "tenant_id")) == tenant and tenant is not None:
            propias.append(row)
        else:
            ajenas += 1
    if ajenas:
        # Metadata-only (C1): el contador dice que hubo cruce sin nombrar a nadie.
        logger.warning("governance: %d fila(s) de decisión descartadas por tenant ajeno", ajenas)
    return tuple(propias)


def build_connection_overrides(redact_enabled) -> dict:
    """Traduce el toggle por-Connection al override tri-estado del resolutor.

    ``redact_enabled`` debe llegar **crudo de la columna**: ``None`` = sin override (la
    cascada sigue), ``True``/``False`` = decisión explícita de esa Connection. El caller
    NO puede colapsar el ``None`` a un default —el colapso que hoy hace ``custom_auth``
    (``redact_enabled if redact_enabled is not None else True``, custom_auth.py:149)
    haría que **toda** Connection sin toggle presentara un override de nivel Connection,
    tapando superficie, modo y tenant, que es justo el nivel más alto de la cascada—.
    El default lo pone el último nivel: ``default_decision`` del registry.
    """
    if redact_enabled is None:
        return {}
    return {_CONNECTION_OVERRIDE_LAYER: ON if redact_enabled else OFF}


def resolve_tenant_profile(db, tenant_id, *, mode, surface=None,
                           surface_trusted: bool = False,
                           connection_overrides: Optional[Mapping] = None,
                           decisions: Optional[Sequence] = None) -> Profile:
    """Postura efectiva del tenant para ``(modo, superficie)``. Una query + la cascada.

    - ``mode``: el token que devuelve ``map_effective_mode`` desde el ruteo **efectivo**,
      jamás el ``upstream_mode`` crudo de la Connection (D5: esa columna es la intención
      declarada, no por dónde se ruteó de verdad).
    - ``surface``: el ``tool_type`` de la Connection, o ``None`` si la superficie del
      pedido no está en el enum (API de Responses, extensión) → la cascada arranca en el
      modo.
    - ``surface_trusted``: default ``False`` a propósito. Con la superficie derivada del
      User-Agent (spoofeable) las filas que RELAJAN se tratan como heredar; solo las que
      agregan protección aplican. Pasar ``True`` es afirmar que la superficie viene del
      ``tool_type`` provisionado por el admin.
    - ``connection_overrides``: el tri-estado de ``build_connection_overrides``.
    - ``decisions``: filas ya leídas. Existe para el call-site que ya trae la postura del
      tenant en la mano (o la tiene cacheada) y no debe pagar una segunda query por
      pedido; si es ``None`` se leen acá. **No es un bypass del filtro de tenant**: pasar
      filas no exime de pasar el ``tenant_id`` al que pertenecen, y las que no coincidan
      se descartan (``_rows_of_tenant``). Un caché por proceso es precisamente el camino
      por el que las filas de un tenant terminarían decidiendo la postura de otro.
    """
    tenant = _normalize_tenant_id(tenant_id)
    rows: Iterable = decisions if decisions is not None else load_tenant_decisions(db, tenant_id)
    # Se filtra SIEMPRE, también lo que ya vino leído por el caller: el filtro es del
    # resolutor de tenant, no de una de sus dos ramas (Constitución III).
    rows = _rows_of_tenant(rows, tenant)
    return resolve_profile(mode, surface, rows,
                           surface_trusted=surface_trusted,
                           connection_overrides=connection_overrides)
