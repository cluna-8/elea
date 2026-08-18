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
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"✅ {len(tests)} tests")
