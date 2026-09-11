"""sentinel_governance — catálogo de capas y resolutor PURO de gobernanza (spec 027).

Tres piezas, un solo hogar:

1. ``GOVERNANCE_LAYERS`` — el catálogo de capas **es una constante de código** (D1). Si
   el piso no vive en una tabla, no existe ``UPDATE`` que lo apague: SC-004 pasa a ser
   estructural en vez de una validación que alguien puede olvidar. La tabla ``guardians``
   sigue siendo la *instancia* configurable (credencial, ``fail_mode``, ``apply_on``),
   enlazada por ``guardian_types`` y **jamás por FK** — ``get_or_create_default_guardians``
   borra la tabla entera y re-siembra cuando hay menos de 9 filas (P2 del research), así
   que cualquier FK a ``guardians.id`` se pierde en cascada en el próximo arranque.
2. ``resolve_profile`` — la cascada determinista Connection > superficie confiable > modo
   > tenant > default de producto (D3/D5, contrato ``contracts/resolutor-perfil.md``).
3. ``build_attribution`` — la atribución honesta por pedido: ``applied_layers`` +
   ``blocked_by_layer`` (D6), que separa los tres ejes hoy conflados en el campo ``action``
   de los triggers (identidad de capa · estado de la capa · decisión sobre el pedido).
   OJO: ``apply_layers`` (contrato #8) es OTRA función —la que además EJECUTA las capas y
   devuelve el ``PolicyResult`` de 6 elementos— y llega en la US2 (T025-T028). Acá **no**
   vive como alias: un alias con firma distinta a la del contrato acepta un ``body`` donde
   el contrato promete ejecución y devuelve todo ``not_configured`` en silencio.

**Camino de import canónico**: ``from extensions import sentinel_governance`` — se agrega a
``sys.path`` la carpeta CONTENEDORA (``<repo>/litellm`` en local, ``/app/litellm_config``
en el contenedor), nunca la carpeta ``extensions``. Al final del archivo se registra el
alias ``sys.modules['sentinel_governance']`` como red de seguridad, para que un caller que
entre por el nombre plano obtenga **el mismo objeto-módulo** y no una segunda copia con
dataclasses distintas (con dos copias, ``isinstance(profile, Profile)`` empieza a fallar
sin motivo aparente al cruzar planos).

**Por qué un módulo nuevo y no dentro de ``sentinel_guardian_policy``**: hay TRES planos que
aplican política y hoy no comparten resolución (passthrough del gateway, guardrail del
motor, chat UI). Si el resolutor no es único, la 027 se implementa tres veces y SC-003 se
vuelve infalsificable (D3). El paquete ``extensions`` es el único hogar montado en ambos
planos (``docker-compose.yml`` lo monta en el backend como
``/app/litellm_config/extensions``; ``backend/src/api/gateway.py`` ya importa de ahí), y
un archivo propio evita el conflicto de merge con la reescritura de
``sentinel_guardian_policy.py`` en curso. El backend lo re-exporta delgado desde
``src/services/governance_catalog.py``.

PURA = sin DB, sin servicios, sin I/O, sin imports del backend (el contenedor del motor no
puede ver ``backend/``): las decisiones del tenant llegan **ya leídas** por el caller,
donde ya hay sesión y SQL. Cero I/O nuevo en el camino caliente.

Constraint C1: nada de lo que este módulo produce lleva texto libre, valor detectado ni
fragmento de prompt — solo **códigos del catálogo y contadores**. El patrón de los
``detail`` que hoy incluyen el nombre propio bloqueado es una fuga, y no se copia.
Constitución VII: ningún nombre de proveedor externo sale de acá hacia API, logs ni UI —
``guardian_types`` es clave de join interna contra una columna existente y nunca viaja en
``applied_layers`` (que usa ``layer_key``, identidad estable, no el nombre de display del
guardián, que es editable y white-label y rompería la atribución histórica en un rename).
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Iterable as _IterableABC, Mapping as _MappingABC
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Tuple

_LOG = logging.getLogger("sentinel.governance")

# ── Vocabularios cerrados ─────────────────────────────────────────────────────────

# Planos donde puede correr una capa. Es CONJUNTO, no escalar: el piso corre en los tres
# call-sites del resolutor a la vez, mientras las capas de proveedor solo existen en el
# motor (data-model §2.1).
PLANE_GATEWAY = "gateway"
PLANE_ENGINE = "engine"
PLANE_BACKEND = "backend"
ALL_PLANES = frozenset({PLANE_GATEWAY, PLANE_ENGINE, PLANE_BACKEND})

TIER_FLOOR = "floor"
TIER_OPTIONAL = "optional"

# Decisión de configuración (lo que vive en governance_profiles.decision). OJO: NO es lo
# mismo que la `decision` de applied_layers (allow|mask|flag|block, más abajo) — son dos
# ejes distintos que el modelo viejo confundía en un solo campo (D6).
ON = "on"
OFF = "off"
DECISIONS = frozenset({ON, OFF})

# Modos de conexión — codominio de la función de mapeo Y dominio del CHECK de
# `governance_profiles.scope_value`: el mismo token carácter a carácter, sin traducción
# intermedia (contrato #2, data-model §1.2).
MODE_SUBSCRIPTION = "subscription"
MODE_GATEWAY_MODELS = "gateway-models"
CONNECTION_MODES = (MODE_SUBSCRIPTION, MODE_GATEWAY_MODELS)

# Superficies: espejo exacto del CHECK `ck_api_keys_tool_type` de la Connection. JAMÁS el
# User-Agent, que es spoofeable por el cliente (D5). Una superficie fuera de este enum
# (API de Responses #28, extensión de navegador) cae a None → la cascada arranca en el
# modo (fallback explícito, riesgo asumido en D5).
# 'servicio' agregado en la migración 018 (spec 043 US2/US4, T002): las llaves de servicio
# del instalador (`svc.anythingllm-provider`, `svc.rag-masking`) dejan de auditarse bajo
# 'chat-ui' — tenían el tool_type equivocado, que terminaba pisando la columna `model` de
# auditoría (ver `_superficie()` en `backend/src/api/inspect.py` y diagnostico.md §3 de la 043).
SURFACES = ("claude-code", "copilot", "cursor", "claude-desktop", "chatgpt", "chat-ui", "servicio")

# Alcances de configuración (CHECK `ck_governance_profiles_scope_type`).
SCOPE_TENANT_DEFAULT = "tenant_default"
SCOPE_CONNECTION_MODE = "connection_mode"
SCOPE_SURFACE = "surface"
SCOPE_TYPES = frozenset({SCOPE_TENANT_DEFAULT, SCOPE_CONNECTION_MODE, SCOPE_SURFACE})
# Centinela del default de tenant: el UNIQUE de Postgres no deduplica NULLs, así que el
# nivel tenant necesita un valor concreto (data-model §1.2).
TENANT_DEFAULT_SCOPE_VALUE = "*"

# Origen de cada decisión resuelta — es lo que la UI muestra como "de dónde viene esto".
ORIGIN_FLOOR = "floor"
ORIGIN_CONNECTION = "connection"
ORIGIN_SURFACE = "surface"
ORIGIN_CONNECTION_MODE = "connection_mode"
ORIGIN_TENANT_DEFAULT = "tenant_default"
ORIGIN_PRODUCT_DEFAULT = "product_default"

# Estado de la capa EN ESTE PEDIDO (eje 2 de D6).
STATUS_APPLIED = "applied"
STATUS_SKIPPED = "skipped"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_REQUIRES_CREDENTIAL = "requires_credential"
STATUS_DELEGATED = "delegated"
STATUS_DEGRADED = "degraded"
LAYER_STATUSES = frozenset({
    STATUS_APPLIED, STATUS_SKIPPED, STATUS_NOT_CONFIGURED,
    STATUS_REQUIRES_CREDENTIAL, STATUS_DELEGATED, STATUS_DEGRADED,
})

# Decisión de la capa SOBRE EL PEDIDO (eje 3 de D6). Solo con status=applied.
VERDICT_ALLOW = "allow"
VERDICT_MASK = "mask"
VERDICT_FLAG = "flag"
VERDICT_BLOCK = "block"
REQUEST_VERDICTS = frozenset({VERDICT_ALLOW, VERDICT_MASK, VERDICT_FLAG, VERDICT_BLOCK})

# Las ÚNICAS claves admitidas en un elemento de applied_layers (data-model §3.1). Cualquier
# clave extra sería un canal por donde volvería a fugarse texto (C1).
ATTRIBUTION_KEYS = frozenset({"layer_code", "status", "decision", "count"})


# ── Registry de capas ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GovernanceLayer:
    """Una capa del catálogo. Frozen porque el catálogo es constante de producto: lo que
    cambia por tenant es la DECISIÓN sobre la capa, nunca la capa.

    Nota de forma: ``requires_service`` y ``delegation_reason`` van al final con default
    aunque data-model §2.1 los liste en el medio — Python exige que los campos con default
    vayan últimos. El catálogo se construye con keywords, así que el orden es indiferente.
    """

    layer_key: str                    # identidad ESTABLE — la que viaja a applied_layers
    tier: str                         # floor = inapagable, fuera de la cascada
    planes: frozenset                 # subconjunto de ALL_PLANES
    requires_credential: bool         # sin credencial → jamás se reporta aplicándose
    delegable_to_upstream: bool       # solo tiene efecto con modo efectivo 'subscription'
    default_decision: Optional[str]   # último nivel de la cascada; None para el piso
    # Enlace LÓGICO a guardians.guardian_type — NUNCA FK. Lleva nombres de proveedor
    # externo en claro: es clave de join interna y NO es publicable (Constitución VII).
    # Para cualquier salida hacia API/UI/logs se usa `to_public_dict()`, jamás `asdict()`.
    guardian_types: Tuple[str, ...]
    # Dependencia de servicio PROPIO (sidecar NLP de la 016: env var + healthcheck). Es
    # distinta de la credencial: el código puede estar en el proceso y el servicio caído
    # igual, y sin confirmarlo la capa jamás reporta aplicándose (§4.1 regla 2b). None en
    # todo el catálogo inicial; la instancia NLP lo declara al mergear la 016.
    requires_service: Optional[str] = None
    # Copy FR-013: distingue "no la aplicamos nosotros" de "estás desprotegido". Sin nombre
    # de proveedor jamás (Constitución VII).
    delegation_reason: Optional[str] = None
    # Si la capa admite el override por-Connection. Hoy solo pii_masking, que absorbe el
    # toggle `redact_enabled` existente (D8: absorber sin derogar). No está en data-model
    # §2.1 como campo, pero el contrato #2 exige "solo capas que lo declaran" y declararlo
    # en el registry es el único lugar donde no se duplica la lista.
    supports_connection_override: bool = False

    def __post_init__(self) -> None:
        # Congelar los CONTENEDORES, no solo el rebinding. `frozen=True` impide
        # `layer.planes = ...` pero no `layer.planes.add(...)`: con un `set` adentro, un
        # import cualquiera podía mutar el registry en runtime y el catálogo dejaba de ser
        # constante de producto (D1). Se normaliza a frozenset/tuple en construcción, así
        # el caller puede seguir pasando cualquier iterable sin abrir el agujero.
        try:
            object.__setattr__(self, "planes", frozenset(self.planes))
            object.__setattr__(self, "guardian_types", tuple(self.guardian_types))
        except TypeError as exc:  # planes/guardian_types no iterables
            raise ValueError(f"{self.layer_key}: planes/guardian_types no iterables") from exc

        # Invariantes del catálogo verificados en import-time: un piso con
        # default_decision sería un piso apagable por la cascada, y una capa delegable sin
        # motivo dejaría a la UI diciendo "no disponible" donde debe decir "la aplica el
        # upstream" (FR-013).
        if self.tier not in (TIER_FLOOR, TIER_OPTIONAL):
            raise ValueError(f"tier inválido para {self.layer_key}")
        if self.tier == TIER_FLOOR and self.default_decision is not None:
            raise ValueError(f"{self.layer_key}: el piso no tiene decisión")
        if self.tier == TIER_OPTIONAL and self.default_decision not in DECISIONS:
            raise ValueError(f"{self.layer_key}: default_decision debe ser on|off")
        if self.tier == TIER_FLOOR and (self.delegable_to_upstream
                                        or self.supports_connection_override):
            raise ValueError(f"{self.layer_key}: el piso no se delega ni se overridea")
        if self.delegable_to_upstream and not self.delegation_reason:
            raise ValueError(f"{self.layer_key}: delegable sin motivo (FR-013)")
        if not self.planes or not self.planes <= ALL_PLANES:
            raise ValueError(f"{self.layer_key}: planes fuera de dominio")

    @property
    def is_floor(self) -> bool:
        return self.tier == TIER_FLOOR

    def to_public_dict(self) -> dict:
        """Serialización **publicable**: lo único que puede salir hacia API, UI o logs.

        Existe por Constitución VII: ``guardian_types`` lleva nombres de proveedor externo
        en claro (son claves de join contra una columna existente, no white-label), y
        ``requires_service`` nombra un sidecar propio. Sin este método, el router admin de
        la US2 hace ``asdict(layer)`` —el camino de menor esfuerzo— y publica la lista de
        proveedores en una respuesta HTTP del producto white-label. La regla es
        estructural, no una convención: si no está acá, no sale.

        ``planes`` sale como lista ordenada porque el destino es JSON, y un ``frozenset``
        no es serializable.
        """
        return {
            "layer_key": self.layer_key,
            "tier": self.tier,
            "planes": sorted(self.planes),
            "requires_credential": self.requires_credential,
            "delegable_to_upstream": self.delegable_to_upstream,
            "delegation_reason": self.delegation_reason,
            "supports_connection_override": self.supports_connection_override,
        }


# Catálogo inicial completo (data-model §2.2), derivado del mapa real de los 9 guardianes
# sembrados + la partición de D8: **detectar/evaluar/registrar es piso; transformar es
# gobernable**. Apagar el enmascarado es una elección legítima y existente (en herramientas
# de código el masking rompe el código); apagar la intercepción, la evaluación o el registro
# no lo es nunca.
_CATALOG: Tuple[GovernanceLayer, ...] = (
    # ── Piso (tier=floor): sin decisión, sin fila posible en governance_profiles ──
    GovernanceLayer(
        layer_key="interception_audit",
        tier=TIER_FLOOR,
        planes=ALL_PLANES,
        requires_credential=False,
        delegable_to_upstream=False,
        default_decision=None,
        # Cableado estructural: no tiene fila en `guardians` porque no es un guardián
        # configurable, es la propiedad que hace del producto un firewall y no un proxy.
        guardian_types=(),
    ),
    GovernanceLayer(
        layer_key="pii_detection",
        tier=TIER_FLOOR,
        planes=ALL_PLANES,
        requires_credential=False,
        delegable_to_upstream=False,
        default_decision=None,
        # La instancia NLP (spec 016) declarará aquí su requires_service al mergear; hoy
        # lo que corre es la detección local, y la capa es piso igual: con el enmascarado
        # apagado la PII se sigue DETECTANDO y el pedido queda registrado como "detectada,
        # no enmascarada por configuración" en vez de desaparecer del relato (D8).
        guardian_types=("pii_masking", "presidio"),
    ),
    GovernanceLayer(
        layer_key="secret_detection",
        tier=TIER_FLOOR,
        planes=ALL_PLANES,
        requires_credential=False,
        delegable_to_upstream=False,
        default_decision=None,
        guardian_types=("secret_detection",),
    ),
    GovernanceLayer(
        layer_key="ai_act_evaluation",
        tier=TIER_FLOOR,
        planes=ALL_PLANES,
        requires_credential=False,
        delegable_to_upstream=False,
        default_decision=None,
        # Vive en la política compartida, no en `guardians`. El TIERING de la evaluación
        # (qué evidencia pasa a gate duro) es de la spec 018: acá es piso *como evaluación*
        # — siempre corre y siempre se registra.
        guardian_types=(),
    ),
    # ── Gobernables (tier=optional): configurables por fila en governance_profiles ──
    GovernanceLayer(
        layer_key="pii_masking",
        tier=TIER_OPTIONAL,
        planes=ALL_PLANES,
        requires_credential=False,
        delegable_to_upstream=False,
        # Masking-first (Principio I): sin ninguna fila, el tenant nace enmascarando.
        default_decision=ON,
        guardian_types=("pii_masking", "presidio"),
        # Absorbe `redact_enabled` (013 FR-014) como su decisión de nivel Connection, con
        # el NULL=heredar intacto: un mecanismo menos, no uno más (D8).
        supports_connection_override=True,
    ),
    GovernanceLayer(
        layer_key="sensitive_routing",
        tier=TIER_OPTIONAL,
        planes=frozenset({PLANE_BACKEND}),
        requires_credential=False,
        delegable_to_upstream=False,
        # Nace off en el seed y sigue naciendo off: sin vocabulario del cliente ni destino
        # local, la capa no hace nada.
        default_decision=OFF,
        guardian_types=("sensitive_routing",),
    ),
    GovernanceLayer(
        layer_key="enforcement_tier_estricto",
        tier=TIER_OPTIONAL,
        # Capa consumida SOLO por el backend (spec 018 D7, §45): pisos de retención de
        # FR-007, aserción de postura `SENTINEL_AUDIT_FAIL` y consecuencias de capas con grado.
        # El resolutor del motor la ignora por ser clave que no consume (data-model 018 §
        # «Tier de enforcement»), así que vive en el plano `backend`, igual que
        # `sensitive_routing`.
        planes=frozenset({PLANE_BACKEND}),
        # No es un guardián con proveedor: es una POSTURA de la instalación (on = estricto),
        # sin credencial externa ni delegación upstream posible.
        requires_credential=False,
        delegable_to_upstream=False,
        # Semántica D7: on = estricto; off/ausente = estándar (default de fábrica). Nace off
        # como cualquier capa gobernable que agrega rigor solo cuando el admin la enciende.
        default_decision=OFF,
        # No ata a ningún guardián sembrado —es una perilla de gobernanza, no una
        # protección con instancia—, igual que las capas de piso `interception_audit` /
        # `ai_act_evaluation` que tampoco tienen fila en `guardians`.
        guardian_types=(),
    ),
    GovernanceLayer(
        layer_key="content_moderation",
        tier=TIER_OPTIONAL,
        planes=frozenset({PLANE_ENGINE}),
        requires_credential=True,
        delegable_to_upstream=True,
        delegation_reason=(
            "En modo suscripción la moderación de contenido la aplica el servicio "
            "upstream en su propio extremo: no la ejecutamos nosotros. El pedido sigue "
            "interceptado, evaluado y registrado por el piso."
        ),
        default_decision=OFF,
        guardian_types=("openai_moderation",),
    ),
    GovernanceLayer(
        layer_key="prompt_injection",
        tier=TIER_OPTIONAL,
        planes=frozenset({PLANE_ENGINE}),
        requires_credential=True,
        delegable_to_upstream=True,
        delegation_reason=(
            "En modo suscripción los extremos upstream aplican sus propias defensas "
            "anti-inyección: no las ejecutamos nosotros. El pedido sigue interceptado, "
            "evaluado y registrado por el piso."
        ),
        default_decision=OFF,
        # Una capa, N instancias posibles: la capa es la protección conceptual, la fila de
        # `guardians` es el proveedor concreto.
        guardian_types=("lakera_prompt_injection", "llamaguard_moderations"),
    ),
    GovernanceLayer(
        layer_key="content_safety",
        tier=TIER_OPTIONAL,
        planes=frozenset({PLANE_ENGINE}),
        requires_credential=True,
        delegable_to_upstream=False,
        default_decision=OFF,
        guardian_types=("azure_content_safety",),
    ),
    GovernanceLayer(
        layer_key="provider_guardrails",
        tier=TIER_OPTIONAL,
        planes=frozenset({PLANE_ENGINE}),
        requires_credential=True,
        delegable_to_upstream=False,
        default_decision=OFF,
        guardian_types=("bedrock_guardrails",),
    ),
)

# Inmutable de verdad: MappingProxyType no admite escritura, así que ningún import puede
# agregar/quitar capas en runtime (D1 — el piso no es mutable ni por código de terceros).
GOVERNANCE_LAYERS: Mapping[str, GovernanceLayer] = MappingProxyType(
    {layer.layer_key: layer for layer in _CATALOG}
)
# Orden canónico del catálogo: piso primero, y dentro de cada tier el orden de aplicación
# real. Es lo que hace determinista el orden de applied_layers (FR-006).
LAYER_KEYS: Tuple[str, ...] = tuple(layer.layer_key for layer in _CATALOG)


def get_layer(layer_key: Optional[str]) -> Optional[GovernanceLayer]:
    """La capa, o ``None`` si la clave no existe. NO levanta: el router admin la usa para
    responder 422 ante un ``layer_key`` inventado, y el resolutor para ignorar filas
    contrabandeadas por SQL directo (data-model §1.4)."""
    if not isinstance(layer_key, str):
        return None
    return GOVERNANCE_LAYERS.get(layer_key)


def floor_layers() -> Tuple[GovernanceLayer, ...]:
    """El piso, en orden canónico. Lo que ningún alcance puede apagar."""
    return tuple(l for l in _CATALOG if l.tier == TIER_FLOOR)


def optional_layers() -> Tuple[GovernanceLayer, ...]:
    """Las capas gobernables, en orden canónico."""
    return tuple(l for l in _CATALOG if l.tier == TIER_OPTIONAL)


# ── Mapeo de modo (T008) ──────────────────────────────────────────────────────────

# Ruteo EFECTIVO → eje de la spec. Los tokens de la izquierda son los call-sites reales,
# no la columna `upstream_mode`: esa columna es la INTENCIÓN declarada de la Connection
# mientras el ruteo real lo decide la presencia de una key propia en el header de auth
# (una Connection marcada subscription-passthrough puede rutearse byok), y además el
# normalizador colapsa cualquier valor no-byok a subscription (D5). Gobernar sobre la
# intención declarada sería aplicar la política al alcance equivocado.
ROUTE_GATEWAY_PASSTHROUGH = "gateway-passthrough"  # /gw con suscripción propia
ROUTE_ENGINE_GUARDRAIL = "engine-guardrail"        # hook del motor
ROUTE_CHAT_UI = "chat-ui"                          # chat del backend
ROUTE_BYOK = "byok"                                # key del cliente contra su proveedor

_ROUTE_TO_MODE: Mapping[str, str] = MappingProxyType({
    # Al policy-path del gateway solo llega suscripción: byok se rutea al motor ANTES de
    # la política, así que hoy es constante del plano.
    ROUTE_GATEWAY_PASSTHROUGH: MODE_SUBSCRIPTION,
    ROUTE_ENGINE_GUARDRAIL: MODE_GATEWAY_MODELS,
    ROUTE_CHAT_UI: MODE_GATEWAY_MODELS,
    # byok ≠ suscripción: es la key del cliente contra el proveedor, sin protección
    # upstream contratada por nosotros.
    ROUTE_BYOK: MODE_GATEWAY_MODELS,
})


def map_effective_mode(effective_route: Optional[str]) -> str:
    """Modo de conexión desde el ruteo **efectivo**, jamás desde ``upstream_mode`` crudo.

    Ruta no mapeada (o ``None``) ⇒ ``gateway-models``: el modo SIN protección upstream, es
    decir el que resuelve MÁS capas propias. La degradación por desconocimiento va siempre
    hacia más protección, nunca hacia menos (contrato #6).
    """
    if not isinstance(effective_route, str):
        return MODE_GATEWAY_MODELS
    return _ROUTE_TO_MODE.get(effective_route.strip().lower(), MODE_GATEWAY_MODELS)


# ── Perfil resuelto ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LayerDecision:
    """Decisión resuelta para una capa, con su procedencia. El ``origin`` no es cosmética:
    es lo que permite a la UI responder "¿por qué esta capa está así?" sin re-derivar la
    cascada, y lo que hace auditable un cambio de postura."""

    layer_key: str
    decision: str   # ON | OFF — el piso siempre ON
    origin: str

    @property
    def is_on(self) -> bool:
        return self.decision == ON


@dataclass(frozen=True)
class Profile:
    """Postura resuelta para (modo, superficie) — determinista: mismos inputs, mismo
    Profile (FR-006). Incluye SIEMPRE el piso completo: no existe input que produzca un
    Profile sin él (contrato #3), y por eso SC-004 es estructural y no una validación."""

    mode: str
    surface: Optional[str]
    surface_trusted: bool
    layers: Mapping[str, LayerDecision]

    def decision_for(self, layer_key: str) -> Optional[LayerDecision]:
        return self.layers.get(layer_key)

    def is_on(self, layer_key: str) -> bool:
        """¿La capa está activa en esta postura? Una clave desconocida es False —
        fail-closed: nadie activa nada inventando un nombre."""
        decision = self.layers.get(layer_key)
        return bool(decision and decision.is_on)

    def origin_of(self, layer_key: str) -> Optional[str]:
        decision = self.layers.get(layer_key)
        return decision.origin if decision else None

    def to_dict(self) -> dict:
        """Serialización mínima para cruzar el borde de plano (el motor recibe el perfil
        resuelto en ``metadata['sentinel']``, no lee estas tablas: leerlas desde el motor es
        imposible por topología en el perfil prod — P1). Solo códigos, sin texto (C1).
        El cableado a los call-sites es de la US2."""
        return {
            "mode": self.mode,
            "surface": self.surface,
            "surface_trusted": self.surface_trusted,
            "layers": {k: {"decision": d.decision, "origin": d.origin}
                       for k, d in self.layers.items()},
        }

    @classmethod
    def from_dict(cls, data: Optional[dict], *, trusted: bool = False) -> "Profile":
        """Rehidrata un perfil serializado. **Fail-closed en dos niveles** (hallazgo A2).

        El perfil cruza al motor por ``metadata['sentinel']``, o sea dentro de un body que el
        CLIENTE controla, y el motor es alcanzable directamente (premisa de D3). Proteger
        solo el piso no alcanzaba: con la versión anterior, un body con
        ``{'layers': {'pii_masking': {'decision': 'off', 'origin': 'connection'}}}``
        apagaba el enmascarado —el control más fuerte del producto, Principio I— y encima
        la atribución lo reportaba con ``origin='connection'``, como si lo hubiera decidido
        el admin. Cualquier cliente con una key válida se auto-desprotegía.

        - ``trusted=False`` (**DEFAULT**, todo lo que venga del borde): se ignora TODA
          relajación. Una capa opcional que llegue ``off`` cae al ``default_decision`` del
          registry; **solo se aceptan decisiones que AGREGAN** (``on``). Es la misma regla
          que la cascada aplica a la superficie spoofeable (contrato #5): agregar
          protección con una señal no confiable es legal, relajarla no.
        - ``trusted=True``: rehidrata tal cual. Solo para el caller que ya autenticó el
          sobre (el ingress que él mismo serializó el perfil unas líneas antes), nunca
          para un body de cliente.

        **Requisito duro para el caller del ingress (T024/US2)**: antes de inyectar el
        perfil propio debe **BORRAR** ``metadata['sentinel']`` entrante. Sin ese borrado, un
        cliente puede sembrar campos que el ingress no sobreescriba (superficie,
        ``surface_trusted``, capas que el resolutor no toque) y esta barrera solo cubre lo
        que pasa por acá. Borrar y reinyectar es una línea; auditarlo después, no.
        """
        data = data if isinstance(data, dict) else {}
        raw = data.get("layers") if isinstance(data.get("layers"), dict) else {}
        overrides = {}
        for layer_key, value in raw.items():
            layer = get_layer(layer_key)
            if layer is None or layer.is_floor or not isinstance(value, dict):
                continue
            decision = value.get("decision")
            # `in <frozenset>` HASHEA el operando: un valor no hasheable (list/dict/set)
            # levanta TypeError. Como esto es la barrera de un body que el cliente
            # controla, un 500 disparable con {"decision": ["off"]} sería el mismo tipo de
            # agujero que la barrera viene a cerrar — de ahí el isinstance previo, espejo
            # del try/except de _coerce_verdict.
            if not isinstance(decision, str) or decision not in DECISIONS:
                continue
            # Sin sobre autenticado, una decisión que RELAJA es exactamente el ataque:
            # se descarta y la capa cae al default de producto (lo pone _build_profile).
            if not trusted and decision == OFF:
                continue
            origin = value.get("origin")
            if not isinstance(origin, str) or origin not in _ORIGINS:
                origin = ORIGIN_PRODUCT_DEFAULT
            overrides[layer_key] = LayerDecision(
                layer_key=layer_key, decision=decision, origin=origin)
        return _build_profile(
            mode=_normalize_mode(data.get("mode")),
            surface=_normalize_surface(data.get("surface")),
            surface_trusted=bool(data.get("surface_trusted")),
            resolved=overrides,
        )


_ORIGINS = frozenset({ORIGIN_FLOOR, ORIGIN_CONNECTION, ORIGIN_SURFACE,
                      ORIGIN_CONNECTION_MODE, ORIGIN_TENANT_DEFAULT,
                      ORIGIN_PRODUCT_DEFAULT})


# ── Resolutor ─────────────────────────────────────────────────────────────────────


def _first_not_none(*values):
    """Mismo contrato ya vigente en la cascada de contexto (013): None = heredar. NUNCA se
    confunde "no seteado" con "apagado"."""
    for value in values:
        if value is not None:
            return value
    return None


def _normalize_decision(value) -> Optional[str]:
    """``None`` = sin decisión (heredar). Acepta bool (el crudo de la columna
    ``redact_enabled``) y los strings del CHECK. Cualquier otra cosa es **inerte**, no un
    default: un valor basura no puede convertirse en una decisión."""
    if value is None:
        return None
    if isinstance(value, bool):
        return ON if value else OFF
    if value in DECISIONS:
        return value
    return None


def _normalize_mode(mode) -> str:
    """Modo fuera del dominio ⇒ ``gateway-models`` (más capas, nunca menos)."""
    return mode if mode in CONNECTION_MODES else MODE_GATEWAY_MODELS


def _normalize_surface(surface) -> Optional[str]:
    """Superficie fuera del enum ⇒ ``None``: la cascada arranca en el modo (fallback
    explícito de D5, mientras la Responses API y la extensión no estén en el CHECK)."""
    return surface if surface in SURFACES else None


def _row_get(row, name: str):
    """Una fila de decisión puede llegar como objeto ORM (lo más simple: pasar directo el
    resultado de ``db.query(GovernanceProfile)…all()``) o como dict (tests, y el perfil
    serializado que cruza al motor). Se soportan ambos sin que el caller traduzca."""
    if isinstance(row, _MappingABC):
        return row.get(name)
    return getattr(row, name, None)


# Dominio de `scope_value` por `scope_type` — espejo exacto de
# `ck_governance_profiles_scope_pair` (data-model §1.1/§1.2). El resolutor lo revalida
# porque una fila metida por SQL directo se salta el CHECK igual que se salta el 422.
_SCOPE_VALUE_DOMAIN: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    SCOPE_TENANT_DEFAULT: (TENANT_DEFAULT_SCOPE_VALUE,),
    SCOPE_CONNECTION_MODE: CONNECTION_MODES,
    SCOPE_SURFACE: SURFACES,
})


def _index_config(config) -> dict:
    """Indexa las filas de decisión por (scope_type, scope_value, layer_key).

    Acá vive la **defensa en profundidad** de FR-003/SC-004: se descarta toda fila cuyo
    ``layer_key`` no exista en el registry o sea de piso. Una fila contrabandeada por SQL
    directo —saltándose el 422 del router— queda inerte, porque el piso no se lee de la
    config: se construye adentro (contrato #3).

    Y se DESCARTA, no se repara, la fila cuyo ``scope_value`` no pertenezca al dominio de
    su ``scope_type``: antes, un ``scope_type='tenant_default'`` con
    ``scope_value='claude-code'`` —fila que viola ``ck_governance_profiles_scope_pair`` y
    por lo tanto solo puede existir si alguien la metió por SQL directo— se REESCRIBÍA a
    ``'*'`` y terminaba relajando el masking para todo el tenant. data-model §1.4 apoya
    SC-004 en que el resolutor **ignore** lo inválido: reparar una fila imposible es
    inventar una decisión que ningún admin tomó.
    """
    indexed: dict = {}
    rows = config if isinstance(config, _IterableABC) and not isinstance(config, (str, bytes)) else ()
    for row in rows:
        layer = get_layer(_row_get(row, "layer_key"))
        if layer is None or layer.is_floor:
            continue
        scope_type = _row_get(row, "scope_type")
        if scope_type not in SCOPE_TYPES:
            continue
        decision = _normalize_decision(_row_get(row, "decision"))
        if decision is None:
            continue
        scope_value = _row_get(row, "scope_value")
        if scope_value not in _SCOPE_VALUE_DOMAIN[scope_type]:
            continue  # par (scope_type, scope_value) imposible ⇒ fila inerte, no reparada
        indexed[(scope_type, scope_value, layer.layer_key)] = decision
    return indexed


def _build_profile(*, mode: str, surface: Optional[str], surface_trusted: bool,
                   resolved: Mapping[str, LayerDecision]) -> Profile:
    """Ensambla el Profile poniendo el piso PRIMERO y desde el registry. Las decisiones
    resueltas solo pueden hablar de capas opcionales, así que el piso no es sobreescribible
    por construcción — no por una validación que alguien pueda saltear."""
    layers: dict = {}
    for layer in _CATALOG:
        if layer.is_floor:
            layers[layer.layer_key] = LayerDecision(
                layer_key=layer.layer_key, decision=ON, origin=ORIGIN_FLOOR)
        else:
            layers[layer.layer_key] = resolved.get(layer.layer_key) or LayerDecision(
                layer_key=layer.layer_key,
                decision=layer.default_decision,
                origin=ORIGIN_PRODUCT_DEFAULT,
            )
    return Profile(mode=mode, surface=surface, surface_trusted=surface_trusted,
                   layers=MappingProxyType(layers))


def resolve_profile(mode, surface, config, *, surface_trusted: bool,
                    connection_overrides: Optional[Mapping] = None) -> Profile:
    """Resuelve la postura para (modo, superficie) — PURA y determinista (contrato #2).

    Precedencia canónica, de mayor a menor (FR-006)::

        piso (siempre, fuera de la cascada)
          Connection (override por-key, solo capas que lo declaran)
            > superficie confiable > modo de conexión > tenant_default > default de producto

    - ``config``: filas de decisión del tenant (objetos ORM o dicts con ``scope_type``,
      ``scope_value``, ``layer_key``, ``decision``). **Ausencia de fila = heredar**; volver
      a heredar es DELETE de la fila, no una ``decision='inherit'``.
    - ``connection_overrides``: TRI-ESTADO, propagado desde el valor CRUDO de la columna —
      ``None`` = sin override (la cascada sigue), ``on``/``off``/bool = decisión explícita.
      El caller NO puede colapsar el None a un default: si lo hace, toda Connection sin
      toggle presentaría un override de nivel Connection que taparía superficie, modo y
      tenant. El default lo pone el ÚLTIMO nivel (``default_decision`` del registry).
    - ``surface_trusted``: si la superficie viene del ``tool_type`` de la Connection (dato
      provisionado por el admin) o del User-Agent (spoofeable). Ver la regla de relajación
      abajo.

    **Relajar exige superficie confiable** (D5 refinada): una decisión de superficie que
    AGREGA (``on``) aplica siempre — agregar protección con una señal no confiable es
    legal. Una que RELAJA (``off``) aplica solo con ``surface_trusted=True``; si no, se
    trata como heredar. Así el caso insignia de D8 (masking off para herramientas de
    código) es expresable sin abrir vector de evasión: spoofear el User-Agent no consigue
    relajación alguna, y cambiar el ``tool_type`` requiere al admin.
    """
    mode = _normalize_mode(mode)
    surface = _normalize_surface(surface)
    surface_trusted = bool(surface_trusted)
    rows = _index_config(config)
    overrides = connection_overrides if isinstance(connection_overrides, _MappingABC) else {}

    resolved: dict = {}
    for layer in optional_layers():
        key = layer.layer_key

        # Nivel 1 — Connection. Una Connection es más fina que una superficie, así que gana
        # a todo. Solo para capas que lo declaran (hoy pii_masking vía redact_enabled).
        connection = (_normalize_decision(overrides.get(key))
                      if layer.supports_connection_override else None)

        # Nivel 2 — superficie, con la regla de relajación.
        raw_surface = rows.get((SCOPE_SURFACE, surface, key)) if surface else None
        if raw_surface == OFF and not surface_trusted:
            raw_surface = None  # relajación desde señal spoofeable ⇒ heredar

        # Niveles 3 y 4 — modo y tenant. El nivel 5 (default de producto) lo pone
        # _build_profile, para que el piso y el default salgan del mismo lugar.
        by_mode = rows.get((SCOPE_CONNECTION_MODE, mode, key))
        by_tenant = rows.get((SCOPE_TENANT_DEFAULT, TENANT_DEFAULT_SCOPE_VALUE, key))

        decision = _first_not_none(connection, raw_surface, by_mode, by_tenant)
        if decision is None:
            continue  # sin decisión en ningún nivel → default de producto
        # El origen se lee del MISMO orden que _first_not_none: el primer nivel que trajo
        # un valor es el que manda y el que se reporta.
        origin = next(o for value, o in (
            (connection, ORIGIN_CONNECTION),
            (raw_surface, ORIGIN_SURFACE),
            (by_mode, ORIGIN_CONNECTION_MODE),
            (by_tenant, ORIGIN_TENANT_DEFAULT),
        ) if value is not None)
        resolved[key] = LayerDecision(layer_key=key, decision=decision, origin=origin)

    return _build_profile(mode=mode, surface=surface, surface_trusted=surface_trusted,
                          resolved=resolved)


# ── Atribución por pedido ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LayerVerdict:
    """Lo que el call-site YA computó para una capa en este pedido.

    Existe porque la ejecución real de las capas (llamar al detector, enmascarar, evaluar
    AI-Act) vive hoy en la política del gateway/guardrail y esta feature no la reescribe:
    lo que 027 aporta es la ATRIBUCIÓN honesta. El caller ejecuta y reporta; este módulo
    decide qué se puede afirmar de cada capa y lo codifica.

    ``decision`` es el eje "qué decidió la capa sobre el pedido" (allow|mask|flag|block);
    ``count`` el nº de ocurrencias. Se valida en construcción: es la barrera que garantiza
    C1 — por acá no puede pasar un valor detectado ni un fragmento de prompt, solo códigos
    de un vocabulario cerrado y enteros.
    """

    decision: str
    count: Optional[int] = None

    def __post_init__(self) -> None:
        if self.decision not in REQUEST_VERDICTS:
            raise ValueError("decision fuera del vocabulario cerrado (allow|mask|flag|block)")
        if self.count is not None:
            object.__setattr__(self, "count", int(self.count))


@dataclass(frozen=True)
class Attribution:
    """Las dos columnas nuevas de ``audit_logs``, ya con su forma final.

    ``applied_layers`` es una lista de dicts lista para el JSONB; ``blocked_by_layer`` es
    el escalar indexable que hace un bloqueo atribuible con una query trivial, sin abrir
    el JSONB (D6).
    """

    applied_layers: List[dict] = field(default_factory=list)
    blocked_by_layer: Optional[str] = None


def _has_credential(layer: GovernanceLayer, credentials) -> bool:
    if not layer.requires_credential:
        return True
    if isinstance(credentials, _MappingABC):
        return bool(credentials.get(layer.layer_key))
    return layer.layer_key in set(credentials or ())


def _has_service(layer: GovernanceLayer, services) -> bool:
    if not layer.requires_service:
        return True
    if isinstance(services, _MappingABC):
        return bool(services.get(layer.requires_service))
    return layer.requires_service in set(services or ())


def _in_evidence(layer_key: str, recently_applied) -> bool:
    """¿Esta capa VENÍA aplicándose dentro de la ventana de evidencia? (§4.1 regla 4).
    Metadata-only: entra un conjunto de ``layer_key``, nunca payload."""
    if isinstance(recently_applied, _MappingABC):
        return bool(recently_applied.get(layer_key))
    return layer_key in set(recently_applied or ())


# Contador de veredictos ilegibles, por capa. Bounded por construcción (solo se cuentan
# claves del registry, o sea ≤ len(LAYER_KEYS)) y **metadata-only**: la clave es un
# layer_key del catálogo y el valor un entero. El valor basura JAMÁS se guarda ni se
# loguea — ese es justo el patrón de fuga que C1 prohíbe.
_MALFORMED_VERDICTS: Dict[str, int] = {}

# Motivo estructurado del descarte (vocabulario cerrado, no texto libre).
REASON_VERDICT_UNREADABLE = "verdict_unreadable"


def malformed_verdict_counters() -> Dict[str, int]:
    """Copia del contador de veredictos ilegibles — la señal de que un call-site está
    reportando con un vocabulario distinto al del contrato. Sin esto, la degradación es
    silenciosa y el bug vive para siempre."""
    return dict(_MALFORMED_VERDICTS)


def reset_malformed_verdict_counters() -> None:
    """Solo para los tests: el contador es global por proceso."""
    _MALFORMED_VERDICTS.clear()


def _note_malformed_verdict(layer_key: str) -> None:
    _MALFORMED_VERDICTS[layer_key] = _MALFORMED_VERDICTS.get(layer_key, 0) + 1
    # Log estructurado SIN texto: código de capa + motivo del vocabulario cerrado.
    _LOG.warning("governance.verdict_unreadable",
                 extra={"layer_code": layer_key, "reason": REASON_VERDICT_UNREADABLE})


def _coerce_verdict(raw) -> Tuple[Optional[LayerVerdict], bool]:
    """**La única puerta** por la que un veredicto entra a la atribución (hallazgo A3).

    Devuelve ``(veredicto|None, legible)``. Antes solo se convertía cuando el veredicto
    era un ``Mapping``: cualquier otro objeto —uno duck-typed con ``.decision``, o
    directamente un ``str``— pasaba sin validar y su contenido podía terminar dentro de
    ``applied_layers``, que es exactamente el patrón de fuga de ``guardian_service.py:268``
    (el ``detail`` con el nombre propio bloqueado) que C1 prohíbe; un ``str`` además
    reventaba con ``AttributeError`` en el camino caliente.

    Ahora TODO veredicto pasa por ``LayerVerdict``, que valida contra los vocabularios
    cerrados. Lo que no se puede convertir se trata como **veredicto ausente**: ni se deja
    pasar, ni se propaga la excepción. La excepción tampoco se propaga cuando el token es
    del tipo correcto pero no del vocabulario (``'blocked'`` en vez de ``'block'``, un
    ``count`` que es lista): ``build_attribution`` corre en el camino de auditoría de CADA
    pedido, así que un call-site con un token levemente distinto tumbaba el request o
    disparaba el ``try/except`` que dropea la auditoría — justo el agujero que la 027
    existe para cerrar.
    """
    if raw is None:
        return None, True
    if isinstance(raw, LayerVerdict):
        return raw, True
    if isinstance(raw, _MappingABC):
        try:
            return LayerVerdict(decision=raw.get("decision"), count=raw.get("count")), True
        except (ValueError, TypeError):
            pass
        # Rescate acotado: si la DECISIÓN es un token válido y lo único ilegible es el
        # `count`, tirar el veredicto entero perdería un bloqueo realmente emitido y
        # rompería el bicondicional de data-model §3.2 (blocked_by_layer ⟺ hubo bloqueo),
        # que es SC-005. El count se descarta —jamás entra un valor sin validar al JSONB—
        # pero la decisión se conserva. Un token de decisión inválido sí se descarta
        # entero: ahí no se puede afirmar qué decidió la capa.
        try:
            return LayerVerdict(decision=raw.get("decision")), False
        except (ValueError, TypeError):
            return None, False
    # str, objetos duck-typed, enteros, lo que sea: ilegible. No se intenta adivinar.
    return None, False


def build_attribution(profile: Profile, verdicts: Optional[Mapping] = None, *,
                      credentials=(), services=(), recently_applied=()) -> Attribution:
    """Construye la atribución honesta del pedido a partir del perfil + los veredictos.

    ``verdicts`` mapea ``layer_key`` → ``LayerVerdict`` (o dict equivalente) para las capas
    que el call-site EJECUTÓ. Una capa deseada sin veredicto queda ``not_configured``: no
    podemos afirmar que corrió, y afirmarlo es exactamente la mentira que 027 elimina.
    ``credentials`` son las capas con credencial cargada; ``services`` los servicios
    propios confirmados (sidecar de la 016).

    ``applied_layers`` es **exhaustiva sobre el perfil**: TODA capa aparece con su status,
    también las que no corrieron. Sin eso, "no la aplicamos" y "no corrió" vuelven a ser
    indistinguibles (SC-003/SC-005).

    ``recently_applied`` es la ventana de evidencia de §4.1 regla 4 (capas que VENÍAN
    aplicándose): metadata-only, solo ``layer_key``. Sirve para distinguir "nunca se
    confirmó" de "se cayó", que es la diferencia entre ``not_configured`` y ``degraded``.

    **Dos vocabularios, no uno** — se documenta acá porque confundirlos es el error fácil:
    ``estado_efectivo`` (data-model §4.1) describe la POSTURA de la capa por (plano,
    superficie) y se calcula al consultar; el ``status`` de ``applied_layers`` (§3.1)
    describe qué le pasó a la capa EN ESTE PEDIDO. No son el mismo conjunto. El mapeo::

        estado_efectivo          →  status de applied_layers
        ─────────────────────────────────────────────────────
        aplicandose              →  applied      (con veredicto del call-site)
        requiere_credencial      →  requires_credential
        delegada                 →  delegated
        degradada                →  degraded     (venía aplicándose y dejó de confirmarse)
        no_disponible            →  not_configured  (§3.1 no tiene 'no_disponible': en el
                                    eje por-pedido "no hay información" ES not_configured)
        (sin equivalente)        →  skipped      (apagada por DECISIÓN — no existe en §4.1,
                                    donde una capa no deseada cae al default fail-closed)

    Orden del chain (comentado línea por línea abajo): un bloqueo nunca se pierde, la
    delegación es propiedad del MODO —no del deseo ni de la credencial—, la credencial
    faltante solo se reporta si la capa está deseada (una capa apagada por decisión no
    genera un falso "te falta credencial"), y un veredicto explícito jamás se degrada a
    ``skipped``.

    D8 queda codificado en la atribución, no en una frase: con ``pii_masking=off`` la
    detección corre igual (piso) y el resultado lleva ``pii_detection: applied`` con su
    contador + ``pii_masking: skipped``. Esa combinación **es** el registro "PII detectada,
    no enmascarada por configuración"; la frase humana la renderiza la UI desde los códigos
    (C1: el JSONB jamás lleva texto).

    El cableado a los tres call-sites —y la variante que además EJECUTA las capas, con la
    firma ``(profile, body, analyze)`` del contrato #8— es de la US2 (T025-T028).
    """
    verdicts = verdicts if isinstance(verdicts, _MappingABC) else {}
    applied_layers: List[dict] = []
    blocked_by_layer: Optional[str] = None

    for layer_key in LAYER_KEYS:
        layer = GOVERNANCE_LAYERS[layer_key]
        desired = profile.is_on(layer_key)
        # Barrera única de C1: todo veredicto se normaliza acá o no entra (ver
        # _coerce_verdict). Lo ilegible se cuenta y se trata como ausente — nunca tumba
        # la auditoría del pedido.
        verdict, readable = _coerce_verdict(verdicts.get(layer_key))
        if not readable:
            _note_malformed_verdict(layer_key)

        if verdict is not None and verdict.decision == VERDICT_BLOCK:
            # Un BLOQUEO jamás se pierde. Antes, el chain miraba `not desired` antes que el
            # veredicto: una capa apagada cuyo call-site igual bloqueó quedaba `skipped` y
            # `blocked_by_layer=None`, o sea un pedido bloqueado SIN atribución — rompía el
            # bicondicional de data-model §3.2 y con él SC-005. Que la capa haya bloqueado
            # es la evidencia más fuerte posible de que corrió.
            status = STATUS_APPLIED
        elif layer.delegable_to_upstream and profile.mode == MODE_SUBSCRIPTION:
            # La delegación es propiedad del MODO, no del deseo ni de la credencial: en
            # suscripción la protección la aplica el extremo upstream, así que pedir una
            # credencial que no sirve es mentirle al admin (FR-013). Antes esta rama iba
            # DESPUÉS de la credencial, y la misma capa reportaba PEOR estado cuando el
            # admin la encendía (requires_credential) que cuando la dejaba apagada
            # (delegated).
            status = STATUS_DELEGATED
        elif desired and not _has_credential(layer, credentials):
            status = STATUS_REQUIRES_CREDENTIAL
        elif desired and not _has_service(layer, services):
            # §4.1 regla 2b: el código puede estar en el proceso y el servicio propio caído
            # igual, así que sin confirmarlo jamás "aplicándose". Pero no es siempre
            # `degraded`: degradarse es DEJAR de aplicarse. Sin evidencia previa nunca
            # estuvo arriba, y eso en el eje por-pedido es `not_configured` (el
            # `no_disponible` de §4.1; ver el mapeo de vocabularios en el docstring).
            status = (STATUS_DEGRADED if _in_evidence(layer_key, recently_applied)
                      else STATUS_NOT_CONFIGURED)
        elif verdict is not None:
            # Un veredicto explícito nunca se degrada a `skipped`: si el call-site la
            # ejecutó y reportó, corrió — aunque el perfil la diera por apagada. Reportar
            # `skipped` ahí sería la misma mentira que 027 elimina, con el signo invertido.
            status = STATUS_APPLIED
        elif not desired:
            status = STATUS_SKIPPED
        else:
            status = STATUS_NOT_CONFIGURED

        entry = {"layer_code": layer_key, "status": status,
                 "decision": verdict.decision if status == STATUS_APPLIED else None}
        if status == STATUS_APPLIED and verdict.count is not None:
            entry["count"] = verdict.count
        applied_layers.append(entry)

        # Primer bloqueo en orden canónico del catálogo. blocked_by_layer es SIEMPRE un
        # layer_key del registry, jamás el nombre de display del guardián: ese nombre es
        # editable y white-label, y un rename del cliente rompería la atribución histórica.
        if blocked_by_layer is None and entry["decision"] == VERDICT_BLOCK:
            blocked_by_layer = layer_key

    return Attribution(applied_layers=applied_layers, blocked_by_layer=blocked_by_layer)


# NO existe `apply_layers = build_attribution`, y la ausencia es deliberada. El contrato #8
# define `apply_layers(profile, body, analyze) -> PolicyResult` (6 elementos): la variante
# que además EJECUTA las capas. El alias tenía otra firma, así que `apply_layers(profile,
# body)` interpretaba el BODY como si fuera el mapa de veredictos y devolvía todo
# `not_configured` en silencio — un call-site cableado contra el contrato habría reportado
# "ninguna capa configurada" en cada pedido sin fallar nunca. La función real llega en la
# US2 (T025-T028), construida SOBRE build_attribution, cuando los call-sites se cableen.
# Hasta entonces, que el nombre no exista es la señal correcta: rompe fuerte y temprano.


# ── Identidad del módulo ──────────────────────────────────────────────────────────
# Camino canónico: `from extensions import sentinel_governance` (en sys.path va la carpeta
# CONTENEDORA: <repo>/litellm en local, /app/litellm_config en el contenedor). Pero los
# tres planos entran por caminos distintos y alguno puede llegar con el nombre plano
# (`from sentinel_governance import ...`, el mecanismo histórico de gateway.py). Sin este
# alias, cada camino crea un objeto-módulo propio con SUS dataclasses: dos clases `Profile`
# distintas, y un `isinstance(profile, Profile)` que falla al cruzar planos sin motivo
# aparente. `setdefault` en ambos sentidos ⇒ un solo objeto gane quien gane la carrera.
_THIS_MODULE = sys.modules[__name__]
sys.modules.setdefault("sentinel_governance", _THIS_MODULE)
sys.modules.setdefault("extensions.sentinel_governance", _THIS_MODULE)
_EXT_PKG = sys.modules.get("extensions")
if _EXT_PKG is not None and not hasattr(_EXT_PKG, "sentinel_governance"):
    setattr(_EXT_PKG, "sentinel_governance", _THIS_MODULE)
