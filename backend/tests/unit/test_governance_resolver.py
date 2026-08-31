"""Unit del registry + resolutor puro de gobernanza (spec 027, T003/T004/T007/T008).

Lo que estos tests protegen no es "que la función devuelva lo esperado", sino los tres
invariantes de los que dependen criterios de éxito enteros:

- **SC-004 es estructural**: no existe input —config vacía, ``None``, filas
  contrabandeadas con ``layer_key`` de piso, filas con capas inexistentes— que produzca un
  ``Profile`` sin el piso completo. Se testea como PROPIEDAD sobre un barrido de configs,
  no con un caso feliz.
- **La relajación exige superficie confiable** (D5 refinada): agregar protección con una
  señal spoofeable es legal; relajarla no. Si esto se rompe, spoofear el User-Agent apaga
  el enmascarado.
- **C1 en la atribución**: por ``applied_layers`` solo pasan códigos de vocabularios
  cerrados y enteros. Un solo campo de texto libre ahí es una fuga de PII a una columna
  con retención de años.

Contrato: specs/027-governance-configurable-enforcement/contracts/resolutor-perfil.md
"""
import dataclasses
import itertools
import json
from types import MappingProxyType

import pytest

# Camino de import CANÓNICO: en sys.path va la carpeta CONTENEDORA (<repo>/litellm en
# local, /app/litellm_config en el contenedor), nunca la carpeta `extensions`. El backend
# entra por `src/services/governance_catalog.py`, que llega al MISMO objeto-módulo gracias
# al alias de sys.modules del final de sentinel_governance (ver test de identidad más abajo).
from extensions import sentinel_governance as gov


FLOOR_KEYS = tuple(layer.layer_key for layer in gov.floor_layers())
OPTIONAL_KEYS = tuple(layer.layer_key for layer in gov.optional_layers())


def _row(scope_type, scope_value, layer_key, decision):
    return {"scope_type": scope_type, "scope_value": scope_value,
            "layer_key": layer_key, "decision": decision}


class _OrmRow:
    """Fila estilo SQLAlchemy: el resolutor debe aceptar el resultado de la query tal cual,
    sin que el caller lo traduzca a dicts."""

    def __init__(self, scope_type, scope_value, layer_key, decision):
        self.scope_type = scope_type
        self.scope_value = scope_value
        self.layer_key = layer_key
        self.decision = decision


def _resolve(config=None, *, mode=gov.MODE_GATEWAY_MODELS, surface=None,
             surface_trusted=False, connection_overrides=None):
    return gov.resolve_profile(mode, surface, config, surface_trusted=surface_trusted,
                               connection_overrides=connection_overrides)


# ── Registry ──────────────────────────────────────────────────────────────────────


def test_catalogo_completo_11_capas_4_de_piso():
    # spec 018 T016: `enforcement_tier_estricto` se suma como 7ª capa opcional (backend-only).
    assert len(gov.GOVERNANCE_LAYERS) == 11
    assert len(FLOOR_KEYS) == 4
    assert len(OPTIONAL_KEYS) == 7
    assert set(FLOOR_KEYS) == {"interception_audit", "pii_detection",
                               "secret_detection", "ai_act_evaluation"}
    assert set(OPTIONAL_KEYS) == {"pii_masking", "sensitive_routing", "content_moderation",
                                  "prompt_injection", "content_safety", "provider_guardrails",
                                  "enforcement_tier_estricto"}
    # Orden canónico: piso primero (determinismo del orden de applied_layers).
    assert gov.LAYER_KEYS[:4] == FLOOR_KEYS


def test_defaults_de_producto_dan_postura_completa_sin_seed():
    """SC-007: un tenant recién creado, sin una sola fila, ya tiene postura explícita —
    piso activo + masking on + resto off. Sembrar filas convertiría el default de producto
    en un dato borrable."""
    assert gov.GOVERNANCE_LAYERS["pii_masking"].default_decision == gov.ON
    for key in OPTIONAL_KEYS:
        if key != "pii_masking":
            assert gov.GOVERNANCE_LAYERS[key].default_decision == gov.OFF
    for key in FLOOR_KEYS:
        assert gov.GOVERNANCE_LAYERS[key].default_decision is None


def test_enforcement_tier_estricto_es_capa_backend_only_gobernable():
    """spec 018 T016 (D7): la capa de tier es OPCIONAL, backend-only, nace `off` (= estándar),
    no ata a ningún guardián y no se delega ni admite override por Connection.

    Es la clave que el backend consulta para los pisos de retención (FR-007), la aserción de
    `SENTINEL_AUDIT_FAIL` y las consecuencias de las capas con grado. El motor la ignora."""
    layer = gov.GOVERNANCE_LAYERS["enforcement_tier_estricto"]
    assert layer.tier == gov.TIER_OPTIONAL
    assert layer.default_decision == gov.OFF          # off/ausente = estándar
    assert layer.planes == frozenset({gov.PLANE_BACKEND})
    assert layer.guardian_types == ()                 # posición de gobernanza, no guardián
    assert layer.requires_credential is False
    assert layer.delegable_to_upstream is False
    assert layer.delegation_reason is None
    assert layer.supports_connection_override is False


def test_solo_pii_masking_admite_override_por_connection():
    """El toggle per-key existente se absorbe como decisión de UNA capa (D8), no como un
    override universal."""
    declaran = [k for k in gov.LAYER_KEYS
                if gov.GOVERNANCE_LAYERS[k].supports_connection_override]
    assert declaran == ["pii_masking"]


def test_registry_inmutable():
    with pytest.raises(TypeError):
        gov.GOVERNANCE_LAYERS["pii_detection"] = None
    with pytest.raises(TypeError):
        del gov.GOVERNANCE_LAYERS["secret_detection"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        gov.GOVERNANCE_LAYERS["pii_masking"].default_decision = gov.OFF


def test_el_piso_no_es_construible_como_apagable():
    """La invariante de catálogo se verifica en construcción: un piso con decisión, o
    delegable, o con override por Connection, no compila."""
    base = dict(layer_key="x", tier=gov.TIER_FLOOR, planes=gov.ALL_PLANES,
                requires_credential=False, delegable_to_upstream=False,
                default_decision=None, guardian_types=())
    with pytest.raises(ValueError):
        gov.GovernanceLayer(**{**base, "default_decision": gov.OFF})
    with pytest.raises(ValueError):
        gov.GovernanceLayer(**{**base, "supports_connection_override": True})
    with pytest.raises(ValueError):
        gov.GovernanceLayer(**{**base, "delegable_to_upstream": True,
                               "delegation_reason": "motivo"})


# Nombres de proveedor externo que NO pueden salir hacia API, UI ni logs (Constitución
# VII). Se barren tanto el copy de delegación como el dict publicable.
PROVEEDORES_PROHIBIDOS = ("openai", "anthropic", "azure", "aws", "bedrock", "lakera",
                          "presidio", "litellm", "llamaguard", "google", "claude", "gpt")


def test_capas_delegables_tienen_motivo_marca_neutro():
    """FR-013 + Constitución VII: el copy distingue "no la aplicamos nosotros" de "estás
    desprotegido", y jamás nombra a un proveedor."""
    prohibidos = PROVEEDORES_PROHIBIDOS
    delegables = [l for l in gov.GOVERNANCE_LAYERS.values() if l.delegable_to_upstream]
    assert {l.layer_key for l in delegables} == {"content_moderation", "prompt_injection"}
    for layer in delegables:
        motivo = layer.delegation_reason.lower()
        assert "no la" in motivo or "no las" in motivo   # "no lo aplicamos nosotros"
        assert "registrado" in motivo                    # "…pero el piso sigue"
        for nombre in prohibidos:
            assert nombre not in motivo
    for layer in gov.GOVERNANCE_LAYERS.values():
        if not layer.delegable_to_upstream:
            assert layer.delegation_reason is None


def test_to_public_dict_no_deja_salir_un_solo_nombre_de_proveedor():
    """Constitución VII. ``guardian_types`` y ``requires_service`` son claves de join
    internas con nombres de proveedor en claro; el router admin de la US2 va a serializar
    capas y el camino de menor esfuerzo (``asdict``) las publicaría en una respuesta HTTP
    del producto white-label. Si no está en ``to_public_dict``, no sale."""
    esperado = {"layer_key", "tier", "planes", "requires_credential",
                "delegable_to_upstream", "delegation_reason", "supports_connection_override"}
    for layer in gov.GOVERNANCE_LAYERS.values():
        publico = layer.to_public_dict()
        assert set(publico) == esperado
        assert "guardian_types" not in publico and "requires_service" not in publico
        # Barrido literal sobre el dict entero serializado, no solo sobre las claves.
        blob = repr(publico).lower()
        for nombre in PROVEEDORES_PROHIBIDOS:
            assert nombre not in blob, f"{layer.layer_key} publica '{nombre}'"
        assert isinstance(publico["planes"], list)   # JSON-serializable, no frozenset


def test_to_public_dict_omite_lo_que_asdict_publicaria():
    """La contracara: ``asdict`` SÍ lleva los nombres — por eso existe el método público."""
    crudo = repr(dataclasses.asdict(gov.GOVERNANCE_LAYERS["provider_guardrails"])).lower()
    assert "bedrock" in crudo
    assert "bedrock" not in repr(gov.GOVERNANCE_LAYERS["provider_guardrails"].to_public_dict()).lower()


def test_los_contenedores_del_registry_son_inmutables():
    """`frozen=True` protege el rebinding, no el CONTENIDO: con un `set` adentro,
    `layer.planes.add(...)` mutaba el catálogo en runtime y dejaba de ser constante de
    producto (D1)."""
    layer = gov.GOVERNANCE_LAYERS["pii_masking"]
    assert isinstance(layer.planes, frozenset)
    assert isinstance(layer.guardian_types, tuple)
    with pytest.raises(AttributeError):
        layer.planes.add("otro-plano")
    # Se sigue aceptando cualquier iterable en construcción: se congela adentro.
    construida = gov.GovernanceLayer(
        layer_key="x", tier=gov.TIER_OPTIONAL, planes={gov.PLANE_ENGINE},
        requires_credential=False, delegable_to_upstream=False, default_decision=gov.OFF,
        guardian_types=["a", "b"])
    assert construida.planes == frozenset({gov.PLANE_ENGINE})
    assert construida.guardian_types == ("a", "b")


def test_get_layer_no_levanta_ante_clave_inventada():
    assert gov.get_layer("no_existe") is None
    assert gov.get_layer(None) is None
    assert gov.get_layer(123) is None
    assert gov.get_layer("pii_masking").tier == gov.TIER_OPTIONAL


# ── Propiedad: el piso está SIEMPRE, con toda config imaginable ────────────────────


def _configs_hostiles():
    """Barrido de configs: vacías, nulas, basura, y filas maliciosas que intentan apagar
    el piso por todos los alcances y con todos los tipos de dato."""
    configs = [None, [], (), "no soy una lista", 42, [{}], [None], [_OrmRow(None, None, None, None)]]
    alcances = [(gov.SCOPE_TENANT_DEFAULT, "*"),
                (gov.SCOPE_CONNECTION_MODE, gov.MODE_SUBSCRIPTION),
                (gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS),
                (gov.SCOPE_SURFACE, "claude-code"),
                ("scope_inventado", "lo-que-sea")]
    # Filas que intentan apagar cada capa de piso en cada alcance (el vector de SQL directo).
    for (scope_type, scope_value), layer_key in itertools.product(alcances, FLOOR_KEYS):
        configs.append([_row(scope_type, scope_value, layer_key, gov.OFF)])
        configs.append([_OrmRow(scope_type, scope_value, layer_key, False)])
    # Capas inexistentes y decisiones fuera del CHECK.
    configs.append([_row(gov.SCOPE_TENANT_DEFAULT, "*", "capa_inventada", gov.OFF)])
    configs.append([_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", "inherit")])
    configs.append([_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", "DROP TABLE")])
    # Todas las filas hostiles juntas.
    configs.append([r for c in configs if isinstance(c, list) for r in c if isinstance(r, dict)])
    return configs


@pytest.mark.parametrize("config", _configs_hostiles())
@pytest.mark.parametrize("mode", [gov.MODE_SUBSCRIPTION, gov.MODE_GATEWAY_MODELS, None, "raro"])
@pytest.mark.parametrize("surface_trusted", [True, False])
def test_propiedad_el_piso_siempre_esta_y_esta_encendido(config, mode, surface_trusted):
    profile = _resolve(config, mode=mode, surface="claude-code",
                       surface_trusted=surface_trusted,
                       connection_overrides={k: False for k in gov.LAYER_KEYS})
    for layer_key in FLOOR_KEYS:
        decision = profile.decision_for(layer_key)
        assert decision is not None, f"{layer_key} desapareció del Profile"
        assert decision.decision == gov.ON
        assert decision.origin == gov.ORIGIN_FLOOR
        assert profile.is_on(layer_key)


def test_el_profile_cubre_el_catalogo_entero():
    profile = _resolve()
    assert tuple(profile.layers.keys()) == gov.LAYER_KEYS


def test_perfil_inyectado_no_puede_relajar_ninguna_capa():
    """Hallazgo A2. El perfil cruza al motor por ``metadata['sentinel']``, o sea dentro de un
    body que el CLIENTE controla, y el motor es alcanzable directo (D3). Proteger solo el
    piso no alcanzaba: cualquier key válida apagaba el enmascarado (Principio I) y la
    atribución lo reportaba con ``origin='connection'``, como si lo hubiera decidido el
    admin. Sin ``trusted``, ninguna relajación se rehidrata."""
    envenenado = {"mode": gov.MODE_GATEWAY_MODELS, "surface": None, "surface_trusted": True,
                  "layers": {k: {"decision": gov.OFF, "origin": "connection"} for k in gov.LAYER_KEYS}}

    profile = gov.Profile.from_dict(envenenado)          # default = NO confiable
    for layer_key in FLOOR_KEYS:
        assert profile.is_on(layer_key)
    assert profile.is_on("pii_masking"), "un body de cliente apagó el enmascarado"
    assert profile.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT


def test_perfil_inyectado_si_puede_agregar_proteccion():
    """La regla es la misma que la de la superficie spoofeable (contrato #5): agregar
    protección desde una señal no confiable es legal; relajar no."""
    profile = gov.Profile.from_dict({
        "mode": gov.MODE_GATEWAY_MODELS,
        "layers": {"content_safety": {"decision": gov.ON, "origin": "surface"},
                   "pii_masking": {"decision": gov.OFF, "origin": "connection"}}})
    assert profile.is_on("content_safety")      # agrega → entra
    assert profile.is_on("pii_masking")         # relaja → se ignora


def test_perfil_de_sobre_autenticado_se_rehidrata_tal_cual():
    """``trusted=True`` es solo para el caller que YA autenticó el sobre (el ingress que
    serializó el perfil él mismo unas líneas antes), jamás para un body de cliente."""
    serializado = _resolve([_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)]).to_dict()
    profile = gov.Profile.from_dict(serializado, trusted=True)
    assert not profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_TENANT_DEFAULT
    for layer_key in FLOOR_KEYS:   # el piso sigue siendo irrepresentable como apagado
        assert profile.is_on(layer_key)


def test_from_dict_confiable_tampoco_apaga_el_piso():
    envenenado = {"layers": {k: {"decision": gov.OFF, "origin": "floor"} for k in FLOOR_KEYS}}
    profile = gov.Profile.from_dict(envenenado, trusted=True)
    for layer_key in FLOOR_KEYS:
        assert profile.is_on(layer_key)


def test_from_dict_es_no_confiable_por_defecto_incluso_posicionalmente():
    """``trusted`` es keyword-only: nadie lo activa sin querer pasando un posicional."""
    with pytest.raises(TypeError):
        gov.Profile.from_dict({}, True)


# ── Tri-estado del override por Connection ────────────────────────────────────────


def test_override_none_no_tapa_la_cascada():
    """El bug que este contrato previene: si el caller colapsa el NULL a un default, TODA
    Connection sin toggle presenta un override de nivel Connection que tapa superficie,
    modo y tenant."""
    config = [_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)]
    profile = _resolve(config, connection_overrides={"pii_masking": None})
    assert not profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_TENANT_DEFAULT

    # Sin la clave siquiera: mismo resultado (ausencia == None).
    assert _resolve(config, connection_overrides={}).origin_of("pii_masking") == \
        gov.ORIGIN_TENANT_DEFAULT
    assert _resolve(config, connection_overrides=None).origin_of("pii_masking") == \
        gov.ORIGIN_TENANT_DEFAULT


@pytest.mark.parametrize("crudo,esperado", [
    (True, gov.ON), (False, gov.OFF), (gov.ON, gov.ON), (gov.OFF, gov.OFF),
])
def test_override_explicito_gana_a_todo(crudo, esperado):
    config = [_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF),
              _row(gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS, "pii_masking", gov.ON),
              _row(gov.SCOPE_SURFACE, "claude-code", "pii_masking", gov.OFF)]
    profile = _resolve(config, surface="claude-code", surface_trusted=True,
                       connection_overrides={"pii_masking": crudo})
    assert profile.decision_for("pii_masking").decision == esperado
    assert profile.origin_of("pii_masking") == gov.ORIGIN_CONNECTION


def test_override_sobre_capa_que_no_lo_declara_es_inerte():
    profile = _resolve(connection_overrides={"content_moderation": True,
                                             "secret_detection": False})
    assert not profile.is_on("content_moderation")
    assert profile.origin_of("content_moderation") == gov.ORIGIN_PRODUCT_DEFAULT
    assert profile.is_on("secret_detection")  # piso, intocable


def test_override_con_valor_basura_es_inerte_no_default():
    """Un valor que no es on/off/bool/None no puede convertirse en decisión."""
    config = [_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)]
    profile = _resolve(config, connection_overrides={"pii_masking": "quizás"})
    assert not profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_TENANT_DEFAULT


# ── Regla de relajación: agregar siempre, relajar solo con superficie confiable ────


def test_superficie_off_aplica_solo_si_es_confiable():
    """Caso insignia de D8: masking off para herramientas de código. Legal con el
    tool_type de la Connection; inerte si la superficie salió del User-Agent."""
    config = [_row(gov.SCOPE_SURFACE, "claude-code", "pii_masking", gov.OFF)]

    confiable = _resolve(config, surface="claude-code", surface_trusted=True)
    assert not confiable.is_on("pii_masking")
    assert confiable.origin_of("pii_masking") == gov.ORIGIN_SURFACE

    spoofeable = _resolve(config, surface="claude-code", surface_trusted=False)
    assert spoofeable.is_on("pii_masking"), "spoofear el UA consiguió relajación"
    assert spoofeable.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT


@pytest.mark.parametrize("trusted", [True, False])
def test_superficie_on_aplica_siempre(trusted):
    """Agregar protección con una señal no confiable es legal — no abre vector alguno."""
    config = [_row(gov.SCOPE_TENANT_DEFAULT, "*", "content_moderation", gov.OFF),
              _row(gov.SCOPE_SURFACE, "cursor", "content_moderation", gov.ON)]
    profile = _resolve(config, surface="cursor", surface_trusted=trusted)
    assert profile.is_on("content_moderation")
    assert profile.origin_of("content_moderation") == gov.ORIGIN_SURFACE


def test_superficie_no_confiable_que_relaja_hereda_el_nivel_inferior():
    """No es "se ignora la fila y gana el default de producto": es HEREDAR, así que el
    modo debajo sigue mandando."""
    config = [_row(gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS, "prompt_injection", gov.ON),
              _row(gov.SCOPE_SURFACE, "copilot", "prompt_injection", gov.OFF)]
    profile = _resolve(config, surface="copilot", surface_trusted=False)
    assert profile.is_on("prompt_injection")
    assert profile.origin_of("prompt_injection") == gov.ORIGIN_CONNECTION_MODE


def test_superficie_fuera_del_enum_cae_al_modo():
    """Responses API / extensión de navegador: sin superficie en el CHECK, la cascada
    arranca en el modo (fallback explícito de D5)."""
    config = [_row(gov.SCOPE_SURFACE, "responses-api", "pii_masking", gov.OFF),
              _row(gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS, "pii_masking", gov.ON)]
    profile = _resolve(config, surface="responses-api", surface_trusted=True)
    assert profile.surface is None
    assert profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_CONNECTION_MODE


@pytest.mark.parametrize("scope_type,scope_value", [
    # Viola ck_governance_profiles_scope_pair: solo puede existir metida por SQL directo,
    # y es el vector del caso insignia al revés — "relajar el masking sin pasar por el
    # router" (el 422 y el CHECK se saltean juntos).
    (gov.SCOPE_TENANT_DEFAULT, "claude-code"),
    (gov.SCOPE_TENANT_DEFAULT, None),
    (gov.SCOPE_TENANT_DEFAULT, ""),
    (gov.SCOPE_CONNECTION_MODE, "*"),
    (gov.SCOPE_CONNECTION_MODE, "subscription-passthrough"),
    (gov.SCOPE_SURFACE, "*"),
    (gov.SCOPE_SURFACE, "navegador"),
])
def test_fila_contrabandeada_con_scope_value_invalido_se_descarta(scope_type, scope_value):
    """data-model §1.4 apoya SC-004 en que el resolutor IGNORE lo inválido. Antes, el
    nivel tenant REPARABA el ``scope_value`` reescribiéndolo a ``'*'``: una fila imposible
    terminaba relajando el enmascarado para todo el tenant. Reparar es inventar una
    decisión que ningún admin tomó."""
    config = [_row(scope_type, scope_value, "pii_masking", gov.OFF)]
    profile = _resolve(config, surface="claude-code", surface_trusted=True)
    assert profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT


def test_la_fila_valida_de_cada_alcance_si_aplica():
    """La contracara del test de arriba: el descarte no puede comerse las filas legítimas."""
    for scope_type, scope_value in ((gov.SCOPE_TENANT_DEFAULT, "*"),
                                    (gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS),
                                    (gov.SCOPE_SURFACE, "claude-code")):
        config = [_row(scope_type, scope_value, "pii_masking", gov.OFF)]
        assert not _resolve(config, surface="claude-code",
                            surface_trusted=True).is_on("pii_masking")


# ── Precedencia completa entre los 5 niveles ──────────────────────────────────────


def test_precedencia_completa_de_los_cinco_niveles():
    tenant = _row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)
    modo = _row(gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS, "pii_masking", gov.ON)
    superficie = _row(gov.SCOPE_SURFACE, "claude-code", "pii_masking", gov.OFF)

    # 5. default de producto (sin ninguna fila)
    p = _resolve([], surface="claude-code", surface_trusted=True)
    assert (p.decision_for("pii_masking").decision, p.origin_of("pii_masking")) == \
        (gov.ON, gov.ORIGIN_PRODUCT_DEFAULT)

    # 4. tenant_default tapa al producto
    p = _resolve([tenant], surface="claude-code", surface_trusted=True)
    assert (p.decision_for("pii_masking").decision, p.origin_of("pii_masking")) == \
        (gov.OFF, gov.ORIGIN_TENANT_DEFAULT)

    # 3. modo tapa al tenant
    p = _resolve([tenant, modo], surface="claude-code", surface_trusted=True)
    assert (p.decision_for("pii_masking").decision, p.origin_of("pii_masking")) == \
        (gov.ON, gov.ORIGIN_CONNECTION_MODE)

    # 2. superficie confiable tapa al modo
    p = _resolve([tenant, modo, superficie], surface="claude-code", surface_trusted=True)
    assert (p.decision_for("pii_masking").decision, p.origin_of("pii_masking")) == \
        (gov.OFF, gov.ORIGIN_SURFACE)

    # 1. Connection tapa todo
    p = _resolve([tenant, modo, superficie], surface="claude-code", surface_trusted=True,
                 connection_overrides={"pii_masking": True})
    assert (p.decision_for("pii_masking").decision, p.origin_of("pii_masking")) == \
        (gov.ON, gov.ORIGIN_CONNECTION)


def test_fila_de_otro_modo_no_contamina():
    config = [_row(gov.SCOPE_CONNECTION_MODE, gov.MODE_SUBSCRIPTION, "content_safety", gov.ON)]
    assert not _resolve(config, mode=gov.MODE_GATEWAY_MODELS).is_on("content_safety")
    assert _resolve(config, mode=gov.MODE_SUBSCRIPTION).is_on("content_safety")


def test_filas_orm_y_dicts_resuelven_igual():
    args = (gov.SCOPE_TENANT_DEFAULT, "*", "sensitive_routing", gov.ON)
    assert _resolve([_row(*args)]).is_on("sensitive_routing")
    assert _resolve([_OrmRow(*args)]).is_on("sensitive_routing")


def test_determinismo():
    config = [_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF),
              _row(gov.SCOPE_SURFACE, "cursor", "content_safety", gov.ON)]
    a = _resolve(config, surface="cursor", surface_trusted=True)
    b = _resolve(config, surface="cursor", surface_trusted=True)
    assert a.to_dict() == b.to_dict()


# ── Mapeo de modo (T008) ──────────────────────────────────────────────────────────


def test_tokens_canonicos_identicos_al_check_de_la_tabla():
    """Carácter a carácter: el codominio del mapeo ES el dominio de
    governance_profiles.scope_value, sin traducción intermedia."""
    assert gov.CONNECTION_MODES == ("subscription", "gateway-models")


def test_mapeo_desde_el_ruteo_efectivo():
    assert gov.map_effective_mode(gov.ROUTE_GATEWAY_PASSTHROUGH) == gov.MODE_SUBSCRIPTION
    assert gov.map_effective_mode(gov.ROUTE_ENGINE_GUARDRAIL) == gov.MODE_GATEWAY_MODELS
    assert gov.map_effective_mode(gov.ROUTE_CHAT_UI) == gov.MODE_GATEWAY_MODELS
    # byok ≠ suscripción: es la key del cliente, sin protección upstream contratada.
    assert gov.map_effective_mode(gov.ROUTE_BYOK) == gov.MODE_GATEWAY_MODELS


@pytest.mark.parametrize("ruta", [
    None, "", "   ", "ruta-nueva-sin-mapear", 42, ["engine-guardrail"],
    # El valor CRUDO de upstream_mode: es la intención declarada, no el ruteo real, así que
    # no puede colarse como modo (D5).
    "subscription-passthrough", "byok-declarado",
])
def test_ruta_no_mapeada_degrada_hacia_mas_capas(ruta):
    assert gov.map_effective_mode(ruta) == gov.MODE_GATEWAY_MODELS


def test_modo_invalido_en_el_resolutor_degrada_igual():
    for modo in (None, "", "subscription-passthrough", "byok", 7):
        assert _resolve([], mode=modo).mode == gov.MODE_GATEWAY_MODELS


# ── Atribución por pedido ─────────────────────────────────────────────────────────


def _attr(profile, verdicts=None, **kw):
    return gov.build_attribution(profile, verdicts, **kw)


def test_applied_layers_es_exhaustiva_y_ordenada():
    """SC-003/SC-005: sin exhaustividad, "no la aplicamos" y "no corrió" vuelven a ser
    indistinguibles."""
    profile = _resolve([])
    attribution = _attr(profile, {"interception_audit": gov.LayerVerdict(gov.VERDICT_ALLOW)})
    codigos = [e["layer_code"] for e in attribution.applied_layers]
    assert codigos == list(gov.LAYER_KEYS)


def test_elemento_solo_tiene_las_cuatro_claves_permitidas_y_nada_de_texto():
    """C1: por acá solo pasan códigos de vocabularios cerrados y enteros."""
    profile = _resolve([])
    verdicts = {"interception_audit": gov.LayerVerdict(gov.VERDICT_ALLOW),
                "pii_detection": gov.LayerVerdict(gov.VERDICT_FLAG, count=3),
                "secret_detection": gov.LayerVerdict(gov.VERDICT_ALLOW),
                "ai_act_evaluation": gov.LayerVerdict(gov.VERDICT_ALLOW),
                "pii_masking": {"decision": gov.VERDICT_MASK, "count": 3}}
    for entry in _attr(profile, verdicts).applied_layers:
        assert set(entry).issubset(gov.ATTRIBUTION_KEYS)
        assert {"layer_code", "status", "decision"} <= set(entry)
        assert entry["layer_code"] in gov.LAYER_KEYS
        assert entry["status"] in gov.LAYER_STATUSES
        assert entry["decision"] is None or entry["decision"] in gov.REQUEST_VERDICTS
        if "count" in entry:
            assert isinstance(entry["count"], int) and entry["status"] == gov.STATUS_APPLIED


def test_decision_es_none_cuando_el_status_no_es_applied():
    profile = _resolve([_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)])
    for entry in _attr(profile, {"pii_detection": gov.LayerVerdict(gov.VERDICT_FLAG, 2)}).applied_layers:
        if entry["status"] != gov.STATUS_APPLIED:
            assert entry["decision"] is None
            assert "count" not in entry


def test_firma_de_d8_pii_detectada_no_enmascarada_por_configuracion():
    """Con el enmascarado apagado la PII no desaparece del relato: queda detectada,
    contada y explícitamente no enmascarada (FR-002)."""
    profile = _resolve([_row(gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)])
    entries = {e["layer_code"]: e for e in
               _attr(profile, {"pii_detection": gov.LayerVerdict(gov.VERDICT_FLAG, count=3)}).applied_layers}
    assert entries["pii_detection"] == {"layer_code": "pii_detection",
                                        "status": gov.STATUS_APPLIED,
                                        "decision": gov.VERDICT_FLAG, "count": 3}
    assert entries["pii_masking"]["status"] == gov.STATUS_SKIPPED
    assert entries["pii_masking"]["decision"] is None


def test_blocked_by_layer_es_coherente_con_applied_layers():
    profile = _resolve([])
    attribution = _attr(profile, {
        "ai_act_evaluation": gov.LayerVerdict(gov.VERDICT_ALLOW),
        "secret_detection": gov.LayerVerdict(gov.VERDICT_BLOCK, count=1),
    })
    assert attribution.blocked_by_layer == "secret_detection"
    entry = next(e for e in attribution.applied_layers if e["layer_code"] == "secret_detection")
    assert entry["decision"] == gov.VERDICT_BLOCK and entry["status"] == gov.STATUS_APPLIED
    # Sin bloqueo, el escalar es None (índice parcial: los bloqueos son la excepción).
    assert _attr(profile, {"secret_detection": gov.LayerVerdict(gov.VERDICT_ALLOW)}).blocked_by_layer is None


def test_capa_deseada_sin_veredicto_no_se_reporta_aplicada():
    """La mentira que 027 elimina: si el call-site no reportó ejecución, no podemos
    afirmar que corrió."""
    profile = _resolve([])
    entries = {e["layer_code"]: e for e in _attr(profile).applied_layers}
    assert entries["pii_masking"]["status"] == gov.STATUS_NOT_CONFIGURED
    assert entries["interception_audit"]["status"] == gov.STATUS_NOT_CONFIGURED


def test_credencial_faltante_solo_se_reporta_si_la_capa_esta_deseada():
    """§4.1 regla 1: una capa apagada por decisión cae a skipped, no a un falso "te falta
    credencial"."""
    apagada = _resolve([], mode=gov.MODE_GATEWAY_MODELS)
    entries = {e["layer_code"]: e for e in _attr(apagada).applied_layers}
    assert entries["content_safety"]["status"] == gov.STATUS_SKIPPED

    deseada = _resolve([_row(gov.SCOPE_TENANT_DEFAULT, "*", "content_safety", gov.ON)],
                       mode=gov.MODE_GATEWAY_MODELS)
    entries = {e["layer_code"]: e for e in _attr(deseada).applied_layers}
    assert entries["content_safety"]["status"] == gov.STATUS_REQUIRES_CREDENTIAL
    # Con credencial y sin evidencia de ejecución: not_configured, jamás applied.
    entries = {e["layer_code"]: e for e in
               _attr(deseada, credentials={"content_safety": True}).applied_layers}
    assert entries["content_safety"]["status"] == gov.STATUS_NOT_CONFIGURED


def test_un_bloqueo_jamas_queda_sin_atribucion():
    """Bicondicional de data-model §3.2 + SC-005. Antes el chain miraba ``not desired``
    ANTES del veredicto: una capa apagada cuyo call-site igual bloqueó quedaba ``skipped``
    con ``blocked_by_layer=None`` — un pedido bloqueado sin capa a la que atribuirlo."""
    apagada = _resolve([])   # sensitive_routing nace off
    assert not apagada.is_on("sensitive_routing")
    attribution = _attr(apagada, {"sensitive_routing": gov.LayerVerdict(gov.VERDICT_BLOCK, 1)})
    assert attribution.blocked_by_layer == "sensitive_routing"
    entry = next(e for e in attribution.applied_layers
                 if e["layer_code"] == "sensitive_routing")
    assert entry["status"] == gov.STATUS_APPLIED
    assert entry["decision"] == gov.VERDICT_BLOCK


def test_todo_bloqueo_en_applied_layers_tiene_su_escalar():
    """El bicondicional se verifica en ambos sentidos, sobre todas las capas."""
    for layer_key in gov.LAYER_KEYS:
        attribution = _attr(_resolve([], mode=gov.MODE_SUBSCRIPTION),
                            {layer_key: gov.LayerVerdict(gov.VERDICT_BLOCK)})
        bloqueos = [e["layer_code"] for e in attribution.applied_layers
                    if e["decision"] == gov.VERDICT_BLOCK]
        assert bloqueos == [layer_key]
        assert attribution.blocked_by_layer == layer_key


def test_veredicto_explicito_no_se_degrada_a_skipped():
    """Si el call-site la ejecutó y reportó, corrió — aunque el perfil la diera por
    apagada. Reportar ``skipped`` ahí es la misma mentira de 027 con el signo invertido."""
    apagada = _resolve([])
    entries = {e["layer_code"]: e for e in
               _attr(apagada, {"sensitive_routing": gov.LayerVerdict(gov.VERDICT_ALLOW)}).applied_layers}
    assert entries["sensitive_routing"]["status"] == gov.STATUS_APPLIED
    assert entries["sensitive_routing"]["decision"] == gov.VERDICT_ALLOW


def test_delegacion_gana_a_la_credencial_faltante():
    """FR-013. La delegación es propiedad del MODO, no del deseo ni de la credencial:
    antes, la MISMA capa reportaba PEOR estado cuando el admin la ENCENDÍA
    (``requires_credential``, y la UI le pedía una credencial que no le sirve) que cuando
    la dejaba apagada (``delegated``)."""
    deseada = _resolve([_row(gov.SCOPE_TENANT_DEFAULT, "*", "content_moderation", gov.ON)],
                       mode=gov.MODE_SUBSCRIPTION)
    assert deseada.is_on("content_moderation")
    entries = {e["layer_code"]: e for e in _attr(deseada).applied_layers}
    assert entries["content_moderation"]["status"] == gov.STATUS_DELEGATED
    # Y sin delegación (modo pasarela) sí se pide la credencial.
    en_pasarela = _resolve([_row(gov.SCOPE_TENANT_DEFAULT, "*", "content_moderation", gov.ON)],
                           mode=gov.MODE_GATEWAY_MODELS)
    entries = {e["layer_code"]: e for e in _attr(en_pasarela).applied_layers}
    assert entries["content_moderation"]["status"] == gov.STATUS_REQUIRES_CREDENTIAL


def test_delegacion_solo_con_modo_suscripcion():
    suscripcion = _resolve([], mode=gov.MODE_SUBSCRIPTION)
    entries = {e["layer_code"]: e for e in _attr(suscripcion).applied_layers}
    assert entries["prompt_injection"]["status"] == gov.STATUS_DELEGATED
    assert entries["content_moderation"]["status"] == gov.STATUS_DELEGATED
    # No delegable: sigue siendo skipped aunque el modo sea suscripción.
    assert entries["content_safety"]["status"] == gov.STATUS_SKIPPED

    pasarela = _resolve([], mode=gov.MODE_GATEWAY_MODELS)
    entries = {e["layer_code"]: e for e in _attr(pasarela).applied_layers}
    assert entries["prompt_injection"]["status"] == gov.STATUS_SKIPPED


def test_el_piso_jamas_se_reporta_skipped():
    """El piso no es representable como apagado, ni siquiera en la atribución."""
    profile = _resolve([_row(gov.SCOPE_TENANT_DEFAULT, "*", k, gov.OFF) for k in FLOOR_KEYS],
                       mode=gov.MODE_SUBSCRIPTION)
    entries = {e["layer_code"]: e for e in _attr(profile).applied_layers}
    for layer_key in FLOOR_KEYS:
        assert entries[layer_key]["status"] != gov.STATUS_SKIPPED


def test_layer_verdict_rechaza_texto_libre():
    """La barrera de C1 es la construcción del veredicto: un "detalle" humano no entra."""
    with pytest.raises(ValueError):
        gov.LayerVerdict(decision="Nombre personalizado bloqueado: Juan Pérez")
    with pytest.raises(ValueError):
        gov.LayerVerdict(decision=None)
    assert gov.LayerVerdict(gov.VERDICT_MASK, count="4").count == 4


def test_helpers_de_credencial_y_servicio():
    """requires_service es distinto de requires_credential: el código puede estar en el
    proceso y el servicio propio caído igual (§4.1 regla 2b). Ninguna capa del catálogo
    inicial lo declara — lo hará la instancia NLP al mergear la 016."""
    assert all(l.requires_service is None for l in gov.GOVERNANCE_LAYERS.values())
    con_servicio = gov.GovernanceLayer(
        layer_key="x", tier=gov.TIER_OPTIONAL, planes=frozenset({gov.PLANE_ENGINE}),
        requires_credential=False, delegable_to_upstream=False, default_decision=gov.ON,
        guardian_types=(), requires_service="nlp")
    assert gov._has_service(con_servicio, ()) is False
    assert gov._has_service(con_servicio, ("nlp",)) is True
    assert gov._has_service(con_servicio, {"nlp": False}) is False
    sin_credencial = gov.GOVERNANCE_LAYERS["content_safety"]
    assert gov._has_credential(sin_credencial, ()) is False
    assert gov._has_credential(sin_credencial, ("content_safety",)) is True


class _VeredictoImpostor:
    """Objeto duck-typed: tiene ``.decision`` y ``.count``, así que el código viejo lo
    dejaba pasar sin validar y su contenido terminaba dentro de ``applied_layers``."""

    def __init__(self, decision, count=None):
        self.decision = decision
        self.count = count


@pytest.fixture(autouse=True)
def _contador_limpio():
    gov.reset_malformed_verdict_counters()
    yield
    gov.reset_malformed_verdict_counters()


@pytest.mark.parametrize("basura", [
    # Hallazgo A3: la barrera solo convertía Mappings. Todo lo demás entraba crudo.
    _VeredictoImpostor("Nombre personalizado bloqueado: Juan Pérez"),
    _VeredictoImpostor(gov.VERDICT_BLOCK, count=1),
    "block",
    "Se detectó el DNI 12345678Z en el prompt",
    42,
    ["block"],
    object(),
])
def test_veredicto_no_convertible_se_trata_como_ausente_y_no_fuga(basura):
    """C1: un objeto que no pasa por ``LayerVerdict`` no puede aportar NADA a
    ``applied_layers``. Y un ``str`` además reventaba con AttributeError en el camino
    caliente de cada pedido."""
    profile = _resolve([])
    attribution = _attr(profile, {"pii_detection": basura})
    entry = next(e for e in attribution.applied_layers if e["layer_code"] == "pii_detection")
    assert entry["status"] == gov.STATUS_NOT_CONFIGURED
    assert entry["decision"] is None and "count" not in entry
    assert attribution.blocked_by_layer is None
    # Nada del objeto basura sobrevivió en la estructura que va al JSONB.
    blob = repr(attribution.applied_layers)
    for fragmento in ("Juan", "Pérez", "12345678Z", "Nombre personalizado"):
        assert fragmento not in blob
    assert gov.malformed_verdict_counters() == {"pii_detection": 1}


@pytest.mark.parametrize("crudo", [
    {"decision": "blocked"},          # token levemente distinto — el caso real
    {"decision": "BLOCK"},
    {"decision": None},
])
def test_veredicto_con_decision_ilegible_no_tumba_la_auditoria(crudo):
    """``build_attribution`` corre en el camino de auditoría de CADA pedido: propagar el
    ValueError de ``LayerVerdict`` tumbaba el request, o disparaba el try/except que
    dropea la auditoría — justo el escenario que la spec quiere imposibilitar.

    Con la DECISIÓN ilegible el veredicto se descarta entero: no se puede afirmar qué
    decidió la capa, así que la honestidad es reportarla como ausente."""
    profile = _resolve([])
    attribution = _attr(profile, {"secret_detection": crudo})
    entry = next(e for e in attribution.applied_layers if e["layer_code"] == "secret_detection")
    assert entry["status"] == gov.STATUS_NOT_CONFIGURED
    assert entry["decision"] is None
    # Degradado con constancia: el contador es la señal de que un call-site reporta con
    # otro vocabulario. Metadata-only — la clave es un layer_key, el valor un entero.
    assert gov.malformed_verdict_counters() == {"secret_detection": 1}
    assert all(isinstance(v, int) for v in gov.malformed_verdict_counters().values())


@pytest.mark.parametrize("count_basura", [["dos"], object(), "tres", {"n": 1}])
def test_count_ilegible_no_se_lleva_puesta_la_decision(count_basura):
    """Rescate acotado: si la decisión ES del vocabulario y lo único ilegible es el
    ``count``, tirar el veredicto entero perdería un **bloqueo realmente emitido** y
    rompería el bicondicional de data-model §3.2 (``blocked_by_layer`` ⟺ hubo bloqueo),
    que es SC-005. El count se descarta —nunca entra sin validar al JSONB— pero la
    decisión sobrevive, y queda constancia en el contador."""
    profile = _resolve([])
    attribution = _attr(profile, {"secret_detection": {"decision": gov.VERDICT_BLOCK,
                                                       "count": count_basura}})
    entry = next(e for e in attribution.applied_layers if e["layer_code"] == "secret_detection")
    assert entry["status"] == gov.STATUS_APPLIED
    assert entry["decision"] == gov.VERDICT_BLOCK
    assert "count" not in entry                       # el valor ilegible NO llega al JSONB
    assert attribution.blocked_by_layer == "secret_detection"   # el bloqueo no se perdió
    assert gov.malformed_verdict_counters() == {"secret_detection": 1}
    # C1: nada del valor basura sobrevive en la atribución serializada.
    assert "dos" not in json.dumps(attribution.applied_layers, default=str)


def test_el_pedido_se_sigue_auditando_entero_pese_al_veredicto_ilegible():
    profile = _resolve([])
    attribution = _attr(profile, {"pii_detection": "flag",
                                  "secret_detection": gov.LayerVerdict(gov.VERDICT_ALLOW)})
    assert [e["layer_code"] for e in attribution.applied_layers] == list(gov.LAYER_KEYS)
    entries = {e["layer_code"]: e for e in attribution.applied_layers}
    assert entries["secret_detection"]["status"] == gov.STATUS_APPLIED


# ── Regla 2b: servicio propio no confirmado (§4.1) ────────────────────────────────


def _con_requires_service(monkeypatch, layer_key="pii_masking", service="nlp"):
    """El catálogo inicial no declara ``requires_service`` (lo hará la instancia NLP al
    mergear la 016), así que la rama se ejercita sobre una copia del registry."""
    modificada = dataclasses.replace(gov.GOVERNANCE_LAYERS[layer_key],
                                     requires_service=service)
    monkeypatch.setattr(gov, "GOVERNANCE_LAYERS",
                        MappingProxyType({**gov.GOVERNANCE_LAYERS, layer_key: modificada}))


def test_servicio_no_confirmado_sin_evidencia_previa_es_not_configured(monkeypatch):
    """§4.1 regla 2b: ``no_disponible``/``not_configured`` salvo que VINIERA aplicándose.
    Antes emitía ``degraded`` incondicionalmente — degradarse es DEJAR de aplicarse, y sin
    evidencia previa la capa nunca estuvo arriba."""
    _con_requires_service(monkeypatch)
    profile = _resolve([])
    entries = {e["layer_code"]: e for e in _attr(profile, services=()).applied_layers}
    assert entries["pii_masking"]["status"] == gov.STATUS_NOT_CONFIGURED


def test_servicio_caido_tras_venir_aplicandose_si_es_degraded(monkeypatch):
    _con_requires_service(monkeypatch)
    profile = _resolve([])
    entries = {e["layer_code"]: e for e in
               _attr(profile, services=(), recently_applied=("pii_masking",)).applied_layers}
    assert entries["pii_masking"]["status"] == gov.STATUS_DEGRADED


def test_servicio_confirmado_vuelve_al_camino_normal(monkeypatch):
    _con_requires_service(monkeypatch)
    profile = _resolve([])
    entries = {e["layer_code"]: e for e in
               _attr(profile, {"pii_masking": gov.LayerVerdict(gov.VERDICT_MASK, 1)},
                     services=("nlp",)).applied_layers}
    assert entries["pii_masking"]["status"] == gov.STATUS_APPLIED


# ── Contrato del nombre `apply_layers` y unicidad del módulo ──────────────────────


def test_apply_layers_no_existe_todavia():
    """Contrato #8 define ``apply_layers(profile, body, analyze) -> PolicyResult`` (6
    elementos): la variante que EJECUTA las capas. El alias a ``build_attribution`` tenía
    otra firma — ``apply_layers(profile, body)`` interpretaba el BODY como el mapa de
    veredictos y devolvía todo ``not_configured`` en SILENCIO. Que el nombre no exista es
    la señal correcta hasta la US2 (T025-T028): rompe fuerte y temprano."""
    assert not hasattr(gov, "apply_layers")


def test_hay_un_solo_objeto_modulo_pase_quien_pase():
    """Con dos objetos-módulo (uno por camino de import) hay dos clases ``Profile``
    distintas, y un ``isinstance(profile, Profile)`` empieza a fallar al cruzar planos sin
    motivo aparente. El alias de ``sys.modules`` lo hace imposible."""
    import sentinel_governance as plano   # el nombre por el que entra la puerta del backend

    assert plano is gov
    assert plano.Profile is gov.Profile
    assert isinstance(_resolve([]), plano.Profile)
