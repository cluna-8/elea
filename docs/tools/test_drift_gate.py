"""Tests del gate de drift. Stdlib pura, como el gate: corre en cualquier checkout
sin instalar nada (`python3 docs/tools/test_drift_gate.py`) y también bajo pytest.

Qué protege: cada caso de acá salió de un falso positivo MEDIDO en la calibración,
no de imaginar qué podría romperse. Un gate de honestidad que miente en su primera
corrida no se vuelve a usar, así que las decisiones que lo callaron son justo las
que hay que blindar.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import drift_gate as dg  # noqa: E402


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
