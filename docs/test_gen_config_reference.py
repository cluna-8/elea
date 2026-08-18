"""Tests del parser de .env.example (#211). Stdlib: `python3 docs/test_gen_config_reference.py`."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_config_reference as g  # noqa: E402


def test_blank_line_preserves_section_header():
    """comentario → línea en blanco → VAR= : la descripción llega. Revertir el
    `elif s:` a `else:` (purgar en blanca) hace rojear este caso."""
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
    assert "Encabezado de sección que protege al producto" in desc


def test_consecutive_vars_without_comment_stay_dash():
    rows = g.parse_env(["FOO=1", "BAR=2"])
    assert [r[0] for r in rows] == ["FOO", "BAR"]
    assert rows[0][2] == "—"
    assert rows[1][2] == "—"


def test_immediate_comment_still_binds():
    rows = g.parse_env(["# desc inmediata", "FOO=1"])
    assert "desc inmediata" in rows[0][2]


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
        test_blank_line_preserves_section_header,
        test_consecutive_vars_without_comment_stay_dash,
        test_immediate_comment_still_binds,
        test_non_blank_junk_still_purges,
    ]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"✅ {len(tests)} tests")
