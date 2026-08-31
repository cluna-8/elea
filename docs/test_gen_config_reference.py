"""Tests del parser de .env.example (#211, #241). Stdlib: `python3 docs/test_gen_config_reference.py`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_config_reference as g  # noqa: E402


# ── #241: banner separado de descripción ─────────────────────────────────────────

def test_section_banner_separated_from_description():
    """comentario → línea en blanco → VAR= : el comentario es un BANNER de
    sección, NO se concatena a la descripción de la variable (#241).  Un
    cambio futuro que vuelva a pegar el banner a la celda hace rojear este test."""
    rows = g.parse_env(
        [
            "# Encabezado de sección que protege al producto",
            "",
            "FOO=1",
        ]
    )
    assert len(rows) == 1
    var, _shown, desc = rows[0]
    assert var == "FOO"
    # El banner NO se concatena a la descripción — la variable no tiene
    # descripción inmediata, así que llega como "—".
    assert desc == "—"


def test_section_banner_appears_in_sections():
    """El banner de sección llega vía `parse_env_sections`, no pegado a la fila."""
    sections = g.parse_env_sections(
        [
            "# Encabezado de sección que protege al producto",
            "",
            "FOO=1",
        ]
    )
    assert len(sections) == 1
    title, body, rows = sections[0]
    assert title == "Encabezado de sección que protege al producto"
    assert body is None
    assert len(rows) == 1
    assert rows[0][0] == "FOO"
    assert rows[0][2] == "—"


def test_immediate_comment_is_description_not_banner():
    """Comentario inmediato (sin línea en blanco) es DESCRIPCIÓN, no banner."""
    sections = g.parse_env_sections(
        [
            "# desc inmediata",
            "FOO=1",
        ]
    )
    assert len(sections) == 1
    title, body, rows = sections[0]
    assert title is None
    assert body is None
    assert "desc inmediata" in rows[0][2]


def test_banner_plus_immediate_description():
    """Banner separado por blank + descripción inmediata: ambos llegan, pero
    separados — el banner como ``###``, la descripción en la celda."""
    sections = g.parse_env_sections(
        [
            "# Banner de sección",
            "",
            "# Descripción de la variable",
            "FOO=1",
        ]
    )
    assert len(sections) == 1
    title, body, rows = sections[0]
    assert title == "Banner de sección"
    assert "Descripción de la variable" in rows[0][2]
    assert "Banner de sección" not in rows[0][2]


def test_banner_title_and_body_split():
    """Un banner de varias líneas: la primera es el título (``###``), el resto
    es el cuerpo (párrafo introductorio).  Ninguna parte del banner va en la
    celda de descripción."""
    title, body, desc = g._split_banner_desc(
        ["Título del banner", "Cuerpo del banner línea 2", "Cuerpo línea 3", "", "Desc de la var"]
    )
    assert title == "Título del banner"
    assert body == "Cuerpo del banner línea 2 Cuerpo línea 3"
    assert desc == "Desc de la var"


def test_new_banner_starts_new_section():
    """Dos banners distintos → dos secciones, cada una con su ``###``."""
    sections = g.parse_env_sections(
        [
            "# Primera sección",
            "",
            "FOO=1",
            "",
            "# Segunda sección",
            "",
            "BAR=2",
        ]
    )
    assert len(sections) == 2
    assert sections[0][0] == "Primera sección"
    assert sections[1][0] == "Segunda sección"
    assert sections[0][2][0][0] == "FOO"
    assert sections[1][2][0][0] == "BAR"


def test_blank_separated_vars_without_banner_start_new_section():
    """Dos grupos de vars separados por blank, sin banner: dos secciones
    distintas (la segunda sin ``###``), para que no queden colgadas en la
    sección anterior."""
    sections = g.parse_env_sections(
        [
            "# desc de FOO",
            "FOO=1",
            "",
            "# desc de BAR",
            "BAR=2",
        ]
    )
    assert len(sections) == 2
    assert sections[0][0] is None  # sin banner
    assert sections[0][2][0][0] == "FOO"
    assert sections[1][0] is None  # sin banner
    assert sections[1][2][0][0] == "BAR"


# ── #271: un bloque de variables comentadas no se lleva puesta la sección siguiente ─

def test_bloque_de_vars_comentadas_no_funde_su_banner_con_la_seccion_siguiente():
    """El bug de #271, con la forma exacta que tiene en `.env.example`.

    Un bloque cuyas variables están TODAS comentadas no emite filas, así que su
    banner nunca se purgaba: se arrastraba y se fundía con el banner de la
    sección siguiente. Resultado en la página que se vende: un `###` cortado a
    mitad de frase, las asignaciones crudas como prosa, y —lo peor— las
    variables de la sección nueva archivadas bajo el título de la vieja.

    Es markdown perfectamente válido, así que ni `mkdocs --strict` ni el linter
    de estructura ni el drift gate lo marcan. Sólo se ve regenerando.
    """
    sections = g.parse_env_sections(
        [
            "# Licencia offline: enforcement FAIL-CLOSED",
            "# el compose apunta a la licencia dev del repo.",
            "# SENTINEL_LICENSE_TOKEN_FILE=/app/config/licenses/dev-demo.lic",
            "# SENTINEL_ALLOW_DEV_LICENSE=true    # opt-in a claves dev; SOLO dev/demo",
            "",
            "# SSO: entrar con la identidad corporativa del cliente",
            "",
            "SENTINEL_SSO_REDIRECT_URI=",
        ]
    )
    assert len(sections) == 1
    title, body, rows = sections[0]
    # La variable nueva va bajo SU título, no bajo el de la licencia.
    assert title == "SSO: entrar con la identidad corporativa del cliente"
    assert [r[0] for r in rows] == ["SENTINEL_SSO_REDIRECT_URI"]
    # Y nada del bloque comentado se filtra como prosa a la página.
    texto = f"{title} {body} {rows[0][2]}"
    assert "Licencia offline" not in texto
    assert "SENTINEL_ALLOW_DEV_LICENSE" not in texto
    assert "SENTINEL_LICENSE_TOKEN_FILE" not in texto


def test_prosa_que_empieza_con_una_asignacion_sigue_siendo_prosa():
    """El borde que hace difícil el fix de #271, y que salió midiendo, no imaginando.

    `.env.example:93` es una línea de PROSA que arranca con
    `SENTINEL_PURGE_ENABLED=false (el default) el scheduler ni arranca...` — es la
    continuación de un párrafo del banner de la purga. Un clasificador ingenuo
    («el comentario empieza con VAR=» ⇒ variable comentada) le come media frase
    al banner de una sección real. Lo que la separa de una asignación comentada
    es que la asignación termina en el valor o en un `#` inline; la prosa sigue
    con palabras.
    """
    sections = g.parse_env_sections(
        [
            "# Banner de la purga",
            "# SENTINEL_PURGE_ENABLED=false (el default) el scheduler ni arranca,",
            "# así que la caja sale configurada pero inerte.",
            "",
            "SENTINEL_PURGE_WINDOW=02:00-04:00",
        ]
    )
    assert len(sections) == 1
    title, body, _rows = sections[0]
    assert title == "Banner de la purga"
    assert "el scheduler ni arranca" in (body or ""), "la frase de prosa se perdió"
    assert "inerte" in (body or "")


def test_var_comentada_no_llega_como_prosa_a_la_descripcion():
    """Una asignación comentada no describe a nadie: no puede aparecer como texto."""
    rows = g.parse_env(
        [
            "# SENTINEL_LICENSE_TOKEN=            # alternativa: el .lic inline (JSON)",
            "OTRA=1",
        ]
    )
    assert len(rows) == 1
    assert rows[0][0] == "OTRA"
    assert "SENTINEL_LICENSE_TOKEN" not in rows[0][2]


def test_var_comentada_no_borra_el_banner_de_una_var_real_del_mismo_bloque():
    """Bloque MIXTO: si tras la variable comentada viene una real sin línea en
    blanco de por medio, el bloque sí emite fila y su banner tiene a quién
    titular — purgarlo ahí sería la regresión simétrica del fix."""
    sections = g.parse_env_sections(
        [
            "# Banner del bloque mixto",
            "",
            "# OPCIONAL_COMENTADA=x",
            "REAL=1",
        ]
    )
    assert len(sections) == 1
    title, _body, rows = sections[0]
    assert title == "Banner del bloque mixto"
    assert [r[0] for r in rows] == ["REAL"]


# ── #211: comportamiento base que no se rompe ────────────────────────────────────

def test_consecutive_vars_without_comment_stay_dash():
    rows = g.parse_env(["FOO=1", "BAR=2"])
    assert [r[0] for r in rows] == ["FOO", "BAR"]
    assert rows[0][2] == "—"
    assert rows[1][2] == "—"


def test_non_blank_junk_still_purges():
    """Línea con contenido que no es # ni VAR= SÍ rompe el bloque (límite del brief)."""
    rows = g.parse_env(
        [
            "# encabezado",
            "esto no es comentario ni var",
            "FOO=1",
        ]
    )
    assert rows[0][2] == "—"


if __name__ == "__main__":
    tests = [
        test_section_banner_separated_from_description,
        test_section_banner_appears_in_sections,
        test_immediate_comment_is_description_not_banner,
        test_banner_plus_immediate_description,
        test_banner_title_and_body_split,
        test_new_banner_starts_new_section,
        test_blank_separated_vars_without_banner_start_new_section,
        test_consecutive_vars_without_comment_stay_dash,
        test_non_blank_junk_still_purges,
        test_bloque_de_vars_comentadas_no_funde_su_banner_con_la_seccion_siguiente,
        test_prosa_que_empieza_con_una_asignacion_sigue_siendo_prosa,
        test_var_comentada_no_llega_como_prosa_a_la_descripcion,
        test_var_comentada_no_borra_el_banner_de_una_var_real_del_mismo_bloque,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"✅ {len(tests)} tests")
