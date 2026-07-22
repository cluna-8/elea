"""Unit de la resolución de gobernanza por tenant (spec 027, T009).

Estos tests cubren la mitad que el resolutor puro no puede cubrir: **de dónde salen las
filas**. Tres cosas que, si se rompen, rompen criterios de éxito enteros:

- **SC-007**: un tenant sin una sola fila ya tiene postura completa. Si esto falla, el
  producto necesita datos sembrados para estar protegido, y un dato sembrado es un dato
  borrable.
- **Constitución III**: la query filtra por ``tenant_id``. El bug vivo de
  ``get_or_create_default_policy`` (``.first()`` sin filtrar tenant, policy.py:34) es
  exactamente lo que acá se testea que NO pasa — con filas de dos tenants en la misma
  tabla, no con un mock que dice que sí.
- **La lectura nunca relaja**: sin filas legibles la postura cae a los defaults de
  producto, que son los más protectores disponibles. Fail-closed también en el I/O.

Se usa SQLite en memoria con la tabla real del modelo (no un mock de sesión): lo que
importa verificar es que la query descarta filas que **están físicamente ahí**, y eso un
mock no lo demuestra.
"""
import sys
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from extensions import basa_governance
from src.models.governance import GovernanceProfile
from src.services import governance_catalog as gov
from src.services.governance_resolution import (
    build_connection_overrides,
    load_tenant_decisions,
    resolve_tenant_profile,
)

TENANT_A = uuid.UUID("aaaaaaaa-0000-0000-0000-0000000000aa")
TENANT_B = uuid.UUID("bbbbbbbb-0000-0000-0000-0000000000bb")

FLOOR_KEYS = tuple(layer.layer_key for layer in gov.floor_layers())
OPTIONAL_KEYS = tuple(layer.layer_key for layer in gov.optional_layers())


@pytest.fixture()
def db():
    """Sesión sobre SQLite en memoria con la tabla real de ``governance_profiles``.

    Se crea SOLO esa tabla (no ``Base.metadata.create_all``): la FK a ``tenants`` no se
    aplica porque SQLite no fuerza claves foráneas por defecto, y lo que se ejercita acá
    es el filtro del servicio, no la integridad referencial (eso lo dan los CHECKs y el
    UNIQUE de Postgres, verificados en la migración 012).
    """
    engine = create_engine("sqlite://")
    GovernanceProfile.__table__.create(bind=engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _fila(db, tenant_id, scope_type, scope_value, layer_key, decision):
    db.add(GovernanceProfile(
        tenant_id=tenant_id, scope_type=scope_type, scope_value=scope_value,
        layer_key=layer_key, decision=decision, updated_by="admin-test",
    ))
    db.commit()


def _resolver(db, tenant_id=TENANT_A, *, mode=gov.MODE_GATEWAY_MODELS, surface=None,
              surface_trusted=False, connection_overrides=None):
    return resolve_tenant_profile(db, tenant_id, mode=mode, surface=surface,
                                  surface_trusted=surface_trusted,
                                  connection_overrides=connection_overrides)


# ── El catálogo es UN objeto-módulo (D1/D3) ───────────────────────────────────────


def test_catalogo_es_un_unico_objeto_modulo():
    """Un solo camino de import ⇒ un solo catálogo en memoria.

    Reemplaza al T004 original ("el espejo del catálogo está sincronizado"): con la
    implementación única de ``extensions/basa_governance.py`` ya no hay espejo que
    comparar, así que el test degeneró a comparar algo consigo mismo. Lo que sí puede
    romperse —y se rompió: lo encontró la verificación adversarial del Foundational— es
    que el MISMO archivo se cargue dos veces por dos caminos de import distintos
    (``extensions.basa_governance`` y el nombre plano ``basa_governance``). Cada carga
    define sus propias dataclasses: ``a.Profile is b.Profile`` da False, un
    ``isinstance(profile, Profile)`` de la US2 falla cruzando planos, y hay dos
    ``GOVERNANCE_LAYERS`` — el "catálogo único" deja de ser único, que es la premisa de
    SC-003 y de todo D1.
    """
    # La puerta del backend y el import canónico devuelven EL MISMO objeto, no una copia.
    assert gov.GOVERNANCE_LAYERS is basa_governance.GOVERNANCE_LAYERS
    assert gov.Profile is basa_governance.Profile
    assert gov.LayerVerdict is basa_governance.LayerVerdict
    assert gov.LayerDecision is basa_governance.LayerDecision
    assert gov.GovernanceLayer is basa_governance.GovernanceLayer

    # Y el alias plano —la red de seguridad del setdefault— apunta al mismo módulo, no a
    # una segunda carga.
    cargados = {name: mod for name, mod in sys.modules.items()
                if name in ("basa_governance", "extensions.basa_governance")}
    assert len({id(mod) for mod in cargados.values()}) == 1, sorted(cargados)


def test_las_capas_del_profile_son_las_del_catalogo_compartido():
    """El perfil que resuelve el backend habla del mismo catálogo que el motor: si
    aparecieran dos registries, acá se vería como un set de claves distinto."""
    profile = gov.resolve_profile(gov.MODE_GATEWAY_MODELS, None, (), surface_trusted=False)
    assert isinstance(profile, basa_governance.Profile)
    assert set(profile.layers) == set(basa_governance.LAYER_KEYS)


def test_reexport_cubre_lo_que_los_call_sites_de_us2_necesitan():
    """La regla del módulo es "importar siempre desde acá"; si falta un nombre, el dev
    escribe el literal a mano y vuelve la duplicación de taxonomía que documenta D5."""
    for nombre in ("ROUTE_GATEWAY_PASSTHROUGH", "ROUTE_ENGINE_GUARDRAIL",
                   "ROUTE_CHAT_UI", "ROUTE_BYOK", "ATTRIBUTION_KEYS",
                   "map_effective_mode", "build_attribution"):
        assert nombre in gov.__all__, nombre
        assert getattr(gov, nombre) is getattr(basa_governance, nombre), nombre

    # Y las rutas mapean al modo que espera la tabla, sin traducción intermedia.
    assert gov.map_effective_mode(gov.ROUTE_GATEWAY_PASSTHROUGH) in gov.CONNECTION_MODES
    assert gov.map_effective_mode("ruta-que-no-existe") == gov.MODE_GATEWAY_MODELS


# ── SC-007: postura completa sin ninguna fila ─────────────────────────────────────


def test_tenant_sin_filas_resuelve_piso_completo_y_defaults_del_registry(db):
    """El default de producto sale del REGISTRY, no de datos sembrados: por eso la
    migración 012 no siembra nada."""
    profile = _resolver(db)

    # El piso, completo y siempre ON — con origen 'floor', no 'product_default': no es un
    # default que la cascada podría haber pisado, es una capa fuera de la cascada.
    for layer_key in FLOOR_KEYS:
        assert profile.is_on(layer_key), layer_key
        assert profile.origin_of(layer_key) == gov.ORIGIN_FLOOR

    # Las opcionales, con el default del catálogo y su procedencia declarada.
    for layer_key in OPTIONAL_KEYS:
        expected = gov.GOVERNANCE_LAYERS[layer_key].default_decision
        assert profile.decision_for(layer_key).decision == expected, layer_key
        assert profile.origin_of(layer_key) == gov.ORIGIN_PRODUCT_DEFAULT

    # Masking-first (Principio I): el tenant nace enmascarando sin que nadie configure nada.
    assert profile.is_on("pii_masking")


def test_tenant_sin_filas_no_lee_nada_y_no_escribe_nada(db):
    """Leer la postura jamás debe crear filas: un default creado por una lectura es un
    default que después alguien puede borrar (por eso no hay ``get_or_create`` acá)."""
    assert load_tenant_decisions(db, TENANT_A) == ()
    _resolver(db)
    assert db.query(GovernanceProfile).count() == 0


# ── Constitución III: el filtro de tenant, con datos de dos tenants en la tabla ────


def test_filas_de_otro_tenant_no_se_leen(db):
    _fila(db, TENANT_B, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)
    _fila(db, TENANT_B, gov.SCOPE_TENANT_DEFAULT, "*", "content_safety", gov.ON)

    assert load_tenant_decisions(db, TENANT_A) == ()
    assert len(load_tenant_decisions(db, TENANT_B)) == 2


def test_la_postura_de_un_tenant_no_se_resuelve_con_datos_de_otro(db):
    """El antipatrón de ``get_or_create_default_policy`` (``.first()`` sin filtrar tenant)
    devolvería acá la fila de B y apagaría el enmascarado de A."""
    _fila(db, TENANT_B, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)

    profile_a = _resolver(db, TENANT_A)
    assert profile_a.is_on("pii_masking")
    assert profile_a.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT

    profile_b = _resolver(db, TENANT_B)
    assert not profile_b.is_on("pii_masking")
    assert profile_b.origin_of("pii_masking") == gov.ORIGIN_TENANT_DEFAULT


# ── Precedencia end-to-end, desde filas reales ────────────────────────────────────


def test_tenant_default_manda_cuando_es_el_unico_nivel_con_fila(db):
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "content_safety", gov.ON)

    profile = _resolver(db)
    assert profile.is_on("content_safety")
    assert profile.origin_of("content_safety") == gov.ORIGIN_TENANT_DEFAULT


def test_modo_de_conexion_gana_al_tenant_default(db):
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "content_safety", gov.ON)
    _fila(db, TENANT_A, gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS,
          "content_safety", gov.OFF)

    profile = _resolver(db, mode=gov.MODE_GATEWAY_MODELS)
    assert not profile.is_on("content_safety")
    assert profile.origin_of("content_safety") == gov.ORIGIN_CONNECTION_MODE

    # La fila de modo es de ESE modo: en el otro, el tenant_default vuelve a mandar.
    otro = _resolver(db, mode=gov.MODE_SUBSCRIPTION)
    assert otro.is_on("content_safety")
    assert otro.origin_of("content_safety") == gov.ORIGIN_TENANT_DEFAULT


def test_superficie_confiable_gana_al_modo_y_al_tenant(db):
    """Caso insignia de D8: enmascarado apagado para herramientas de código, con el
    ``tool_type`` de la Connection como origen (dato provisionado por el admin)."""
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.ON)
    _fila(db, TENANT_A, gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS,
          "pii_masking", gov.ON)
    _fila(db, TENANT_A, gov.SCOPE_SURFACE, "claude-code", "pii_masking", gov.OFF)

    profile = _resolver(db, surface="claude-code", surface_trusted=True)
    assert not profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_SURFACE

    # Otra superficie del mismo tenant no hereda la relajación.
    otra = _resolver(db, surface="chat-ui", surface_trusted=True)
    assert otra.is_on("pii_masking")
    assert otra.origin_of("pii_masking") == gov.ORIGIN_CONNECTION_MODE


def test_cascada_completa_con_override_de_connection(db):
    """Los cinco niveles a la vez: gana la Connection, y el origen lo dice."""
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)
    _fila(db, TENANT_A, gov.SCOPE_CONNECTION_MODE, gov.MODE_GATEWAY_MODELS,
          "pii_masking", gov.OFF)
    _fila(db, TENANT_A, gov.SCOPE_SURFACE, "claude-code", "pii_masking", gov.OFF)

    profile = _resolver(db, surface="claude-code", surface_trusted=True,
                        connection_overrides=build_connection_overrides(True))
    assert profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_CONNECTION


# ── Relajar exige superficie confiable (D5 refinada) ──────────────────────────────


def test_superficie_spoofeable_no_puede_relajar(db):
    """Con la superficie derivada del User-Agent, la fila que RELAJA se trata como
    heredar: spoofear el UA no apaga el enmascarado."""
    _fila(db, TENANT_A, gov.SCOPE_SURFACE, "claude-code", "pii_masking", gov.OFF)

    spoofeable = _resolver(db, surface="claude-code", surface_trusted=False)
    assert spoofeable.is_on("pii_masking")
    assert spoofeable.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT


def test_superficie_spoofeable_si_puede_agregar(db):
    """Agregar protección con una señal no confiable es legal — la asimetría es el punto."""
    _fila(db, TENANT_A, gov.SCOPE_SURFACE, "claude-code", "content_safety", gov.ON)

    profile = _resolver(db, surface="claude-code", surface_trusted=False)
    assert profile.is_on("content_safety")
    assert profile.origin_of("content_safety") == gov.ORIGIN_SURFACE


# ── Defensa en profundidad sobre filas contrabandeadas ────────────────────────────


def test_fila_de_piso_escrita_por_sql_directo_es_inerte(db):
    """El router admin devuelve 422 ante un ``layer_key`` de piso, pero la tabla no tiene
    CHECK sobre ``layer_key`` (a propósito, D1): una fila escrita saltándose la API no
    puede apagar el piso, porque el piso se construye adentro del Profile."""
    for layer_key in FLOOR_KEYS:
        _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", layer_key, gov.OFF)

    # Las filas EXISTEN en la tabla del tenant...
    assert len(load_tenant_decisions(db, TENANT_A)) == len(FLOOR_KEYS)
    # ...y no tienen ningún efecto.
    profile = _resolver(db)
    for layer_key in FLOOR_KEYS:
        assert profile.is_on(layer_key), layer_key
        assert profile.origin_of(layer_key) == gov.ORIGIN_FLOOR


def test_fila_con_capa_inexistente_es_inerte(db):
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "capa_inventada", gov.OFF)

    profile = _resolver(db)
    assert profile.decision_for("capa_inventada") is None
    assert set(profile.layers) == set(gov.LAYER_KEYS)


# ── Fail-closed de la lectura ─────────────────────────────────────────────────────


@pytest.mark.parametrize("tenant_id", [None, "no-es-un-uuid", 42])
def test_tenant_no_identificable_cae_a_defaults_de_producto(db, tenant_id):
    """Sin tenant legible no hay filas, y sin filas no hay relajación posible: la
    degradación va siempre hacia más protección."""
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)

    assert load_tenant_decisions(db, tenant_id) == ()
    profile = _resolver(db, tenant_id)
    assert profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT


def test_sin_sesion_de_db_hay_postura_igual(db):
    """El caller sin sesión (o con la sesión caída) resuelve el piso + defaults, nunca
    una excepción en el camino caliente."""
    profile = resolve_tenant_profile(None, TENANT_A, mode=gov.MODE_SUBSCRIPTION)
    for layer_key in FLOOR_KEYS:
        assert profile.is_on(layer_key)
    assert profile.is_on("pii_masking")


def test_tenant_id_en_texto_resuelve_igual_que_en_uuid(db):
    """Los call-sites llevan el tenant como str en varios caminos (headers, metadata del
    motor): que un str válido resuelva distinto sería una fuga de postura silenciosa."""
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)

    assert len(load_tenant_decisions(db, str(TENANT_A))) == 1
    assert not _resolver(db, str(TENANT_A)).is_on("pii_masking")


# ── Tri-estado del override por-Connection ────────────────────────────────────────


def test_build_connection_overrides_tri_estado():
    """``None`` = sin override (la cascada sigue). Si esto colapsara a un default, toda
    Connection sin toggle taparía superficie, modo y tenant (custom_auth.py:149)."""
    assert build_connection_overrides(None) == {}
    assert build_connection_overrides(True) == {"pii_masking": gov.ON}
    assert build_connection_overrides(False) == {"pii_masking": gov.OFF}


def test_connection_sin_toggle_no_tapa_la_superficie(db):
    _fila(db, TENANT_A, gov.SCOPE_SURFACE, "claude-code", "pii_masking", gov.OFF)

    profile = _resolver(db, surface="claude-code", surface_trusted=True,
                        connection_overrides=build_connection_overrides(None))
    assert not profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_SURFACE


# ── Reuso de filas ya leídas (sin segunda query) ──────────────────────────────────


def test_decisions_precargadas_evitan_la_query(db):
    """El call-site que ya tiene la postura en la mano no paga una segunda query por
    pedido; el resolutor acepta las filas ORM tal cual, sin traducción.

    Pasar filas NO exime de pasar el tenant al que pertenecen: sin sesión, pero con el
    tenant declarado, el filtro se sigue aplicando (ver los dos tests de abajo)."""
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)
    filas = load_tenant_decisions(db, TENANT_A)

    profile = resolve_tenant_profile(None, TENANT_A, mode=gov.MODE_GATEWAY_MODELS,
                                     decisions=filas)
    assert not profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_TENANT_DEFAULT


def test_decisions_precargadas_de_otro_tenant_no_deciden_la_postura(db):
    """Hallazgo de la verificación adversarial: ``decisions=`` salteaba el ÚNICO filtro de
    tenant de la feature. Un call-site de la US2 que cachee filas por proceso resolvería
    la postura de A con las relajaciones de B — el bug de ``get_or_create_default_policy``
    que este módulo dice no replicar (Constitución III)."""
    _fila(db, TENANT_B, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)
    filas_de_b = load_tenant_decisions(db, TENANT_B)
    assert len(filas_de_b) == 1  # las filas EXISTEN...

    profile = resolve_tenant_profile(None, TENANT_A, mode=gov.MODE_GATEWAY_MODELS,
                                     decisions=filas_de_b)
    # ...y no relajan nada del tenant A: cae al default de producto.
    assert profile.is_on("pii_masking")
    assert profile.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT


def test_decisions_precargadas_sin_tenant_legible_se_descartan(db):
    """Sin tenant no se puede afirmar la pertenencia de ninguna fila, así que se descartan
    todas: la degradación va hacia más protección, nunca hacia menos."""
    _fila(db, TENANT_A, gov.SCOPE_TENANT_DEFAULT, "*", "pii_masking", gov.OFF)
    filas = load_tenant_decisions(db, TENANT_A)

    for tenant_id in (None, "no-es-un-uuid"):
        profile = resolve_tenant_profile(None, tenant_id, mode=gov.MODE_GATEWAY_MODELS,
                                         decisions=filas)
        assert profile.is_on("pii_masking"), tenant_id
        assert profile.origin_of("pii_masking") == gov.ORIGIN_PRODUCT_DEFAULT


def test_decisions_precargadas_como_dicts_tambien_se_filtran(db):
    """El perfil serializado cruza planos como dicts: el filtro lee la fila con el MISMO
    lector que el resolutor (``row_get``), así que dict y ORM se tratan igual."""
    ajena = {"tenant_id": str(TENANT_B), "scope_type": gov.SCOPE_TENANT_DEFAULT,
             "scope_value": "*", "layer_key": "pii_masking", "decision": gov.OFF}
    propia = dict(ajena, tenant_id=str(TENANT_A))

    assert resolve_tenant_profile(None, TENANT_A, mode=gov.MODE_GATEWAY_MODELS,
                                  decisions=[ajena]).is_on("pii_masking")
    assert not resolve_tenant_profile(None, TENANT_A, mode=gov.MODE_GATEWAY_MODELS,
                                      decisions=[propia]).is_on("pii_masking")
