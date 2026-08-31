"""Puerta del backend al catálogo y al resolutor de gobernanza (spec 027, D1/D3).

Este módulo **no implementa nada**: re-exporta la librería compartida
``extensions.sentinel_governance``. La implementación vive en ``litellm/extensions/`` por una
razón de topología, no de gusto: el contenedor del motor monta ese paquete y **no puede
importar ``backend/``** (ni ver su código, ni su base — P1 del research: en el perfil prod
el motor corre contra una base propia). Si el catálogo viviera en ``backend/src/services``
habría que espejarlo en el motor, y un espejo es una segunda implementación esperando a
desincronizarse — exactamente lo que D3 prohíbe: **un resolutor, tres call-sites**
(passthrough del gateway, guardrail del motor, chat UI). Con dos implementaciones, SC-003
("la postura resuelta es la misma en todos los planos") se vuelve infalsificable.

El paquete está montado en **ambos** planos (``docker-compose.yml`` lo monta en el backend
como ``/app/litellm_config/extensions``, y en el motor como ``/app/extensions``), así que
el invariante se preserva sin espejo: el backend entra por esta puerta y el motor importa
el mismo archivo.

**Mecanismo de import — un solo camino canónico** (hallazgo de la verificación adversarial
del Foundational): se agrega al ``sys.path`` la carpeta **CONTENEDORA** del paquete
(``/app/litellm_config`` en el contenedor, ``<repo>/litellm`` en local) y se importa
``from extensions import sentinel_governance`` — el mismo camino que ya usa
``backend/tests/conftest.py``. La versión anterior agregaba la carpeta ``extensions`` y
hacía un import PLANO (``from sentinel_governance import ...``): con eso, el mismo archivo se
cargaba **dos veces** —``extensions.sentinel_governance`` y ``sentinel_governance`` conviviendo en
``sys.modules``, con dataclasses distintas— y ``a.Profile is b.Profile`` daba False. Era
literalmente lo que el docstring declaraba prohibido: dos ``GOVERNANCE_LAYERS`` en memoria
significan que el "catálogo único" no es único, y un ``isinstance(profile, Profile)`` de la
US2 fallaría cruzando caminos sin motivo aparente.

Como red de seguridad, tras el import se registra el alias plano con
``sys.modules.setdefault``: si alguien (código legado, un call-site del motor) importa
``sentinel_governance`` a secas **después**, recibe **este mismo objeto-módulo** en vez de
cargar una segunda copia. ``setdefault`` y no asignación: si el nombre plano ya estaba
tomado, pisarlo escondería el problema en vez de exponerlo — el test
``test_catalogo_es_un_unico_objeto_modulo`` es el que lo grita.

Regla para el resto del backend: **importar siempre desde acá**, nunca de
``extensions.sentinel_governance`` ni del nombre plano. Por eso se re-exporta también el
vocabulario de rutas (``ROUTE_*``) que los tres call-sites de la US2 le pasan a
``map_effective_mode``: sin el re-export, el dev escribe el literal a mano, y la
duplicación de taxonomía es justo el origen del problema que documenta D5.

Nota: ``Profile.to_dict`` / ``Profile.to_public_dict`` viajan como **métodos** del
``Profile``, no como funciones del módulo — no hay nada que re-exportar para ellos.
"""
import os
import sys

# ── Librería PURA compartida ──────────────────────────────────────────────────────
# Se agrega la carpeta CONTENEDORA del paquete ``extensions`` (no la carpeta
# ``extensions`` misma): el import canónico es ``from extensions import sentinel_governance``,
# idéntico al de conftest.py y al que usan los tests del resolutor puro. Un solo camino ⇒
# un solo objeto-módulo ⇒ un solo catálogo.
for _container in ("/app/litellm_config",
                   os.path.join(os.path.dirname(__file__), "..", "..", "..", "litellm"),
                   "/app"):
    if os.path.isdir(os.path.join(_container, "extensions")):
        _abs = os.path.abspath(_container)
        if _abs not in sys.path:
            sys.path.insert(0, _abs)
        break

from extensions import sentinel_governance  # noqa: E402

# Red de seguridad: quien importe el nombre plano recibe ESTE módulo, no una segunda copia.
sys.modules.setdefault("sentinel_governance", sentinel_governance)

from extensions.sentinel_governance import (  # noqa: E402
    # Catálogo (D1): constante de código, MappingProxyType — no hay UPDATE que apague el
    # piso, así que SC-004 es estructural y no una validación que alguien puede olvidar.
    GOVERNANCE_LAYERS,
    LAYER_KEYS,
    GovernanceLayer,
    get_layer,
    floor_layers,
    optional_layers,
    # Resolutor puro (D3) y su resultado.
    Profile,
    LayerDecision,
    resolve_profile,
    map_effective_mode,
    # Atribución por pedido (D6): las dos columnas nuevas de audit_logs, ya con su forma.
    Attribution,
    LayerVerdict,
    build_attribution,
    ATTRIBUTION_KEYS,
    # Lector de filas del resolutor. Se re-exporta —privado arriba, público acá— porque el
    # filtro de tenant de ``governance_resolution`` tiene que leer una fila EXACTAMENTE
    # como la lee el resolutor (objeto ORM o dict, indistinto): un segundo lector sería
    # una segunda semántica de "fila", y las dos se desincronizarían.
    _row_get as row_get,
    # Vocabularios cerrados. Se re-exportan porque el router admin, el servicio de estado
    # y los tests los necesitan, y escribir los literales a mano en cada archivo es cómo
    # el producto terminó con tres taxonomías de superficie conviviendo (D5).
    TIER_FLOOR,
    TIER_OPTIONAL,
    ON,
    OFF,
    DECISIONS,
    MODE_SUBSCRIPTION,
    MODE_GATEWAY_MODELS,
    CONNECTION_MODES,
    SURFACES,
    # Rutas efectivas: el dominio de ``map_effective_mode``. Los tres call-sites de la US2
    # (passthrough del gateway, guardrail del motor, chat UI) + byok entran por acá.
    ROUTE_GATEWAY_PASSTHROUGH,
    ROUTE_ENGINE_GUARDRAIL,
    ROUTE_CHAT_UI,
    ROUTE_BYOK,
    SCOPE_TENANT_DEFAULT,
    SCOPE_CONNECTION_MODE,
    SCOPE_SURFACE,
    SCOPE_TYPES,
    TENANT_DEFAULT_SCOPE_VALUE,
    ORIGIN_FLOOR,
    ORIGIN_CONNECTION,
    ORIGIN_SURFACE,
    ORIGIN_CONNECTION_MODE,
    ORIGIN_TENANT_DEFAULT,
    ORIGIN_PRODUCT_DEFAULT,
    STATUS_APPLIED,
    STATUS_SKIPPED,
    STATUS_NOT_CONFIGURED,
    STATUS_REQUIRES_CREDENTIAL,
    STATUS_DELEGATED,
    STATUS_DEGRADED,
    LAYER_STATUSES,
    VERDICT_ALLOW,
    VERDICT_MASK,
    VERDICT_FLAG,
    VERDICT_BLOCK,
    REQUEST_VERDICTS,
    PLANE_GATEWAY,
    PLANE_ENGINE,
    PLANE_BACKEND,
    ALL_PLANES,
)

__all__ = [
    "sentinel_governance",
    "GOVERNANCE_LAYERS", "LAYER_KEYS", "GovernanceLayer", "get_layer",
    "floor_layers", "optional_layers",
    "Profile", "LayerDecision", "resolve_profile", "map_effective_mode",
    "Attribution", "LayerVerdict", "build_attribution", "ATTRIBUTION_KEYS",
    "row_get",
    "TIER_FLOOR", "TIER_OPTIONAL", "ON", "OFF", "DECISIONS",
    "MODE_SUBSCRIPTION", "MODE_GATEWAY_MODELS", "CONNECTION_MODES", "SURFACES",
    "ROUTE_GATEWAY_PASSTHROUGH", "ROUTE_ENGINE_GUARDRAIL", "ROUTE_CHAT_UI", "ROUTE_BYOK",
    "SCOPE_TENANT_DEFAULT", "SCOPE_CONNECTION_MODE", "SCOPE_SURFACE", "SCOPE_TYPES",
    "TENANT_DEFAULT_SCOPE_VALUE",
    "ORIGIN_FLOOR", "ORIGIN_CONNECTION", "ORIGIN_SURFACE", "ORIGIN_CONNECTION_MODE",
    "ORIGIN_TENANT_DEFAULT", "ORIGIN_PRODUCT_DEFAULT",
    "STATUS_APPLIED", "STATUS_SKIPPED", "STATUS_NOT_CONFIGURED",
    "STATUS_REQUIRES_CREDENTIAL", "STATUS_DELEGATED", "STATUS_DEGRADED",
    "LAYER_STATUSES",
    "VERDICT_ALLOW", "VERDICT_MASK", "VERDICT_FLAG", "VERDICT_BLOCK", "REQUEST_VERDICTS",
    "PLANE_GATEWAY", "PLANE_ENGINE", "PLANE_BACKEND", "ALL_PLANES",
]
