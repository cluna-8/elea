"""Tests del gate de drift. Stdlib pura, como el gate: corre en cualquier checkout
sin instalar nada (`python3 docs/tools/test_drift_gate.py`) y también bajo pytest.

Qué protege: cada caso de acá salió de un falso positivo MEDIDO en la calibración,
no de imaginar qué podría romperse. Un gate de honestidad que miente en su primera
corrida no se vuelve a usar, así que las decisiones que lo callaron son justo las
que hay que blindar.
"""
from __future__ import annotations

import ast
import re
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import drift_gate as dg  # noqa: E402

# `VAR=` al principio de la línea, con o sin `#` delante. A propósito NO es la
# expresión del gate: si el test reusara su parser, comprobaría que la función
# coincide consigo misma.
_ASIGNACION = re.compile(r"^\s*(#\s*)?([A-Z][A-Z0-9_]*)=")


def test_normaliza_quita_montaje_y_unifica_parametros():
    assert dg.normalizar("/api/v1/users/{user_id}") == "/users/{}"
    assert dg.normalizar("/gw/") == "/gw"
    # `{user_id}` y `{id}` son la misma ruta: comparar nombres de parámetro daría
    # deriva donde sólo hay una diferencia de estilo entre el código y el openapi.
    assert dg.normalizar("/x/{id}") == dg.normalizar("/x/{otro}")


def test_punteado_resuelve_la_cadena_completa():
    """El bug que este test cierra: `os.environ.get("X")` tiene `get` como último
    atributo, así que mirar sólo el atributo descartaba lecturas reales de entorno
    y las reportaba como variables muertas."""
    expr = lambda src: ast.parse(src, mode="eval").body.func  # noqa: E731
    assert dg._punteado(expr('os.environ.get("X")')) == "os.environ.get"
    assert dg._punteado(expr('os.getenv("X")')) == "os.getenv"
    assert dg._punteado(expr('_env_int("X", 1)')) == "_env_int"
    for fuente in ('os.environ.get("X")', 'os.getenv("X")', '_env_int("X", 1)'):
        assert "env" in dg._punteado(expr(fuente)).lower()


def test_contrato_distingue_razones_de_identificadores():
    """`blocked_*`/`rejected_*` viajan al cliente; `audit_logs` o `license_id` son
    nombres de campo internos. Mezclarlos convertía el eje en ruido."""
    for razon in ("blocked_by_policy", "rejected_saturated", "blocked_secret"):
        assert dg.CONTRACT_RE.match(razon), razon
    for interno in ("audit_logs", "audit_log_id", "license_id", "license_status"):
        assert not dg.CONTRACT_RE.match(interno), interno
        assert interno not in dg.ESTADOS_LICENCIA, interno
    for estado in ("license_expired", "license_grace", "license_over_seat"):
        assert estado in dg.ESTADOS_LICENCIA, estado


def test_contrato_excluye_los_que_coinciden_por_forma_pero_no_son_estado():
    """`blocked_by_layer` es nombre de COLUMNA (guarda qué capa bloqueó, su valor
    nunca es el string "blocked_by_layer"); `blocked_topics` es clave de config de
    un Guardian seed con `is_active=False`. Los dos matchean CONTRACT_RE por forma
    y ninguno es un compliance_status real — se colaron en la primera pasada de la
    tabla del ítem 3 del backlog y se verificaron falsos antes de publicar."""
    literales = dg.contratos_del_codigo()
    for falso in ("blocked_by_layer", "blocked_topics"):
        assert dg.CONTRACT_RE.match(falso), f"{falso} debería matchear la forma"
        assert falso not in literales, f"{falso} se coló como contrato real"


def test_rutas_ocultas_no_cuentan_como_deriva():
    """`include_in_schema=False` es una decisión del backend, no un olvido: el router
    `/internal` se excluye del openapi a propósito y el gate debe respetarlo."""
    rutas = dg.rutas_del_codigo()
    assert rutas, "el extractor de rutas no devolvió nada — revisá backend/src/api"
    assert not [r for r in rutas if r.startswith("/internal")], \
        "una ruta de /internal se coló: include_in_schema=False dejó de honrarse"


def test_env_incluye_helpers_tipados_y_el_plano_motor():
    env = dg.env_del_codigo()
    # Helper tipado: services/engine_gate.py lo lee con `_env_int`, no con os.getenv.
    assert env.get("BASA_ENGINE_MAX_CONCURRENCY") == "app"
    # os.environ.get directo — el caso del bug de `_punteado`.
    assert env.get("NLP_ANALYZER_URL") == "app"
    # Plano motor: litellm/config.yaml interpola con `os.environ/VAR`.
    assert env.get("OPENAI_API_KEY") == "app"
    # Perilla de compose: no es superficie de configuración del producto.
    assert env.get("BACKEND_IMAGE") == "orquestacion"


def test_insumo_ausente_falla_cerrado_no_pasa_en_silencio():
    """El bug que este test cierra: `rutas_del_contrato()`/`env_declaradas()` devolvían
    `{}`/`set()` cuando faltaba su archivo fuente, así que un openapi.json borrado
    reportaba PASS con 0 mentiras — el gate parecía sano por no tener con qué
    comparar. Ahora las dos funciones levantan `InsumoAusenteError`, y `main()` sale
    con código ≠ 0 en vez de imprimir una tabla vacía y feliz."""
    real_openapi = dg.OPENAPI
    try:
        dg.OPENAPI = dg.REPO / "no-existe" / "openapi.json"
        with pytest_raises(dg.InsumoAusenteError):
            dg.rutas_del_contrato()
    finally:
        dg.OPENAPI = real_openapi

    real_env = dg.ENV_EXAMPLE
    try:
        dg.ENV_EXAMPLE = dg.REPO / "no-existe" / ".env.example"
        with pytest_raises(dg.InsumoAusenteError):
            dg.env_declaradas()
    finally:
        dg.ENV_EXAMPLE = real_env


def pytest_raises(excepcion):
    """Mini `pytest.raises` de una línea — el resto del archivo ya corre sin pytest
    (stdlib pura, `if __name__ == "__main__"` al final), así que no se suma la
    dependencia solo para este caso."""

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, tipo, valor, tb):
            if tipo is None:
                raise AssertionError(f"se esperaba {excepcion.__name__}, no se levantó nada")
            return issubclass(tipo, excepcion)

    return _Ctx()


def test_veredicto_tiene_forma_estable():
    v = dg.construir_veredicto()
    assert v["veredicto"] in {"PASS", "FAIL"}
    assert set(v["resumen"]) == {"documentado_no_existe", "existe_no_documentado", "solo_compose"}
    assert all({"eje", "categoria", "item", "detalle"} <= set(h) for h in v["hallazgos"])
    # FAIL ⟺ hay al menos una mentira. El resto son huecos y no bloquean.
    assert (v["veredicto"] == "FAIL") == (v["resumen"]["documentado_no_existe"] > 0)


def test_rutas_en_paridad_con_el_openapi_publicado():
    """Regresión viva: si alguien agrega un endpoint y no regenera el openapi, o lo
    borra y la referencia sigue prometiéndolo, esto se pone rojo."""
    mentiras = [h for h in dg.construir_veredicto()["hallazgos"]
                if h["eje"] == "rutas" and h["categoria"] == "documentado_no_existe"]
    assert not mentiras, f"el openapi promete rutas que el backend no sirve: {mentiras}"


# ── #266: routers montados desde fuera de `api/` ─────────────────────────────────

@contextmanager
def _arbol_backend(fuentes: dict[str, str]):
    """Monta un backend de laboratorio y apunta el gate ahí.

    Deliberadamente sintético y no un assert sobre el árbol real: un test que hardcodea
    «hoy `sso/api.py` existe» envejece con la próxima decisión de organización y falla
    por una razón que no es la suya. Acá la topología es el sujeto del test.
    """
    originales = (dg.REPO, dg.API_DIR)
    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        for relativo, fuente in fuentes.items():
            destino = raiz / relativo
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(fuente, encoding="utf-8")
        dg.REPO, dg.API_DIR = raiz, raiz / "backend" / "src" / "api"
        try:
            yield
        finally:
            dg.REPO, dg.API_DIR = originales


_SUBPAQUETE = {
    "backend/src/api/__init__.py": (
        "from fastapi import APIRouter\n"
        "from .users import router as users_router\n"
        "from ..sso.api import router as sso_router\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(users_router)\n"
        "api_router.include_router(sso_router)\n"
    ),
    "backend/src/api/users.py": (
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/users')\n"
        "@router.get('/{user_id}')\n"
        "def leer(user_id): ...\n"
    ),
    "backend/src/sso/api.py": (
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/auth/sso')\n"
        "@router.get('/login')\n"
        "def login(): ...\n"
    ),
}


def test_router_en_subpaquete_con_prefijo_propio_entra_al_escaneo():
    """El openapi sale de la app VIVA —ve cualquier router montado—, el gate lee fuentes.

    Mientras el eje A globeaba sólo `api/*.py` (no recursivo), un router en un paquete
    hermano quedaba invisible y sus rutas REALES salían reportadas como mentira del
    openapi: el gate acusando al código honesto, que es la dirección que enseña a
    ignorarlo. Salió en #266 con `sso/api.py` y su `prefix="/auth/sso"` propio.
    """
    with _arbol_backend(_SUBPAQUETE):
        rutas = dg.rutas_del_codigo()

    assert "/auth/sso/login" in rutas, f"el router del subpaquete no entró: {sorted(rutas)}"
    assert rutas["/auth/sso/login"] == {"GET"}
    # El camino viejo sigue vivo: esto no reemplaza el glob de `api/`, lo amplía.
    assert "/users/{}" in rutas, sorted(rutas)


def test_router_declarado_pero_nunca_montado_no_cuenta_como_ruta_del_codigo():
    """Por qué se deriva de los puntos de montaje y no de un `**/*.py` más ancho.

    Un router que nadie incluye no sirve tráfico: contarlo inventaría deriva al revés
    —«el código la tiene y el openapi no»— por una ruta que ningún cliente puede llamar.
    """
    huerfano = dict(_SUBPAQUETE)
    huerfano["backend/src/legacy/api.py"] = (
        "from fastapi import APIRouter\n"
        "router = APIRouter(prefix='/legacy')\n"
        "@router.get('/muerto')\n"
        "def muerto(): ...\n"
    )
    with _arbol_backend(huerfano):
        rutas = dg.rutas_del_codigo()

    assert "/auth/sso/login" in rutas, "el montado sí tiene que estar"
    assert "/legacy/muerto" not in rutas, "un router sin montar no es una ruta del backend"


# ── #271: el gate y el generador tienen que estar de acuerdo en «declarada» ──────

def _vars_de_la_referencia_generada() -> set[str]:
    """Las variables que el generador de la referencia realmente emite a la página."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import gen_config_reference as gen  # noqa: PLC0415

    lineas = dg.ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    return {fila[0] for _t, _b, filas in gen.parse_env_sections(lineas) for fila in filas}


def test_gate_y_generador_coinciden_en_que_es_una_variable_declarada():
    """El bug de #271: dos herramientas leían `.env.example` con dos definiciones
    distintas de «declarada» y nadie las comparaba.

    El gate aceptaba `# VAR=` y el generador no, así que una variable comentada
    satisfacía al gate —que la daba por documentada y se callaba— y jamás llegaba
    a la referencia que se le muestra al cliente. En ese hueco vivían las cinco
    variables de la licencia offline, entre ellas `BASA_ALLOW_DEV_LICENSE`, la que
    habilita claves de licencia de desarrollo.

    Este test es el que impide que las dos definiciones se vuelvan a separar: no
    comprueba una lista de nombres (que envejece con cada variable nueva), sino
    que los dos conjuntos sean el MISMO sobre el `.env.example` real.
    """
    del_gate = dg.env_declaradas()
    de_la_pagina = _vars_de_la_referencia_generada()
    assert del_gate == de_la_pagina, (
        "el gate y la referencia no coinciden — "
        f"sólo en el gate: {sorted(del_gate - de_la_pagina)} · "
        f"sólo en la página: {sorted(de_la_pagina - del_gate)}"
    )


@contextmanager
def _env_example(contenido: str):
    """Apunta el gate a un `.env.example` de laboratorio, para ejercitar
    `env_declaradas()` —la función de producción— sobre líneas elegidas."""
    original = dg.ENV_EXAMPLE
    with tempfile.TemporaryDirectory() as tmp:
        falso = Path(tmp) / ".env.example"
        falso.write_text(contenido, encoding="utf-8")
        dg.ENV_EXAMPLE = falso
        try:
            yield
        finally:
            dg.ENV_EXAMPLE = original


def test_una_variable_comentada_no_cuenta_como_declarada():
    """`# VAR=` no llega a la referencia, así que no puede contar como documentada."""
    with _env_example("# BASA_ALLOW_DEV_LICENSE=true    # opt-in a claves dev\nREAL=1\n"):
        declaradas = dg.env_declaradas()
    assert declaradas == {"REAL"}, declaradas


def test_en_el_archivo_real_ninguna_variable_solo_comentada_cuenta_como_declarada():
    """El mismo invariante sobre el `.env.example` REAL, pero DERIVADO del archivo.

    La versión anterior de este caso fijaba los cuatro nombres que estaban comentados
    el día que se escribió. Eso es un ancla de CONTENIDO: el día que se decida
    documentar una de esas variables —una decisión de producto, perfectamente
    legítima— el test se pone rojo por una razón que no es la suya, y encima no
    cubre a la variable comentada que aparezca mañana. Acá el conjunto sale del
    archivo, así que el test sigue al archivo en vez de pedirle que no cambie.

    Ojo con el caso mixto: una variable puede aparecer comentada en un bloque de
    ejemplo Y declarada de verdad más abajo. Sólo las que están ÚNICAMENTE
    comentadas tienen que estar ausentes.
    """
    comentadas, sin_comentar = set(), set()
    for linea in dg.ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        if (m := _ASIGNACION.match(linea)):
            (comentadas if m.group(1) else sin_comentar).add(m.group(2))
    solo_comentadas = comentadas - sin_comentar

    # Sin esto el test se volvería vacuo en silencio si algún día no quedara
    # ninguna comentada: seguiría verde sin ejercitar nada.
    assert solo_comentadas, (
        ".env.example ya no tiene ninguna variable sólo comentada: este caso dejó "
        "de cubrir algo sobre el archivo real y hay que replantearlo"
    )

    coladas = solo_comentadas & dg.env_declaradas()
    assert not coladas, (
        f"{sorted(coladas)} están sólo comentadas en .env.example y el gate las da "
        "por declaradas — así es como una variable se pierde de la referencia que "
        "se le muestra al cliente sin que nadie se entere"
    )


def test_prosa_que_empieza_con_una_asignacion_no_cuenta_como_declarada():
    """`.env.example:93` es una FRASE que arranca con `BASA_PURGE_ENABLED=false`.

    Con el `#?` viejo, cualquier línea de prosa con esa forma entraba al conjunto
    de declaradas. Es la dirección peligrosa: una variable nombrada al pasar en un
    párrafo podía tapar un hueco real, o inventar una mentira que rompiera CI sin
    que nadie hubiera declarado nada.
    """
    with _env_example(
        "# Banner de la purga\n"
        "# BASA_PURGE_ENABLED=false (el default) el scheduler ni arranca,\n"
        "# así que la caja sale configurada pero inerte.\n"
        "\n"
        "BASA_PURGE_WINDOW=02:00-04:00\n"
    ):
        declaradas = dg.env_declaradas()
    assert declaradas == {"BASA_PURGE_WINDOW"}, declaradas


def _mentiras_de_config() -> set[str]:
    return {h["item"] for h in dg.construir_veredicto()["hallazgos"]
            if h["eje"] == "config" and h["categoria"] == "documentado_no_existe"}


def test_comentar_una_variable_no_puede_inventar_una_mentira():
    """Direccionalidad del fix de #271, medida con señal REAL en las dos ramas.

    Las MENTIRAS son `declaradas - código`, así que estrechar `declaradas` sólo
    puede quitar mentiras, nunca agregarlas: por eso #271 no rompe CI sea cual sea
    el contenido de `.env.example`. Un test que midiera esto sobre el árbol de hoy
    sería VACUO —hoy el conjunto de mentiras está vacío y la aserción se cumpliría
    sola—, así que se mide sobre un `.env.example` de laboratorio que sí produce
    una: la misma variable, declarada y comentada.
    """
    # Declarada de verdad y sin ningún plano que la lea ⇒ MENTIRA, y el gate rompe.
    with _env_example("VARIABLE_QUE_NADIE_LEE=1\n"):
        assert "VARIABLE_QUE_NADIE_LEE" in _mentiras_de_config()
        assert dg.construir_veredicto()["veredicto"] == "FAIL"

    # La MISMA variable, comentada: ya no está declarada, así que no puede mentir.
    with _env_example("# VARIABLE_QUE_NADIE_LEE=1\n"):
        assert "VARIABLE_QUE_NADIE_LEE" not in _mentiras_de_config()


def test_las_mentiras_reportadas_son_exactamente_declaradas_menos_codigo():
    """El eje de config tiene que REPORTAR lo que su definición dice, no callarse.

    Sobre un `.env.example` de laboratorio con una mentira plantada, para que la
    igualdad tenga contenido (sobre el árbol real los dos lados son vacíos y la
    aserción no probaría nada).
    """
    with _env_example("VARIABLE_QUE_NADIE_LEE=1\nOTRA_QUE_NADIE_LEE=2\n"):
        declaradas, codigo = dg.env_declaradas(), dg.env_del_codigo()
        esperadas = declaradas - codigo.keys()
        assert esperadas, "el laboratorio tenía que plantar al menos una mentira"
        assert _mentiras_de_config() == esperadas


if __name__ == "__main__":
    fallos = 0
    for nombre, fn in sorted(globals().items()):
        if not nombre.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            print(f"  ok   {nombre}")
        except AssertionError as exc:
            fallos += 1
            print(f"  FAIL {nombre}: {exc}")
    print(f"\n{'FALLÓ' if fallos else 'VERDE'} — {fallos} fallo(s)")
    raise SystemExit(1 if fallos else 0)
