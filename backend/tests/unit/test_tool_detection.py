"""Detección de herramienta por User-Agent (spec 019 US1 T008, FR-004).

`detect_tool` vive en la librería compartida `basa_guardian_policy` (la misma que usa
el `custom_auth` del motor); acá se verifica la semántica portada del demo (`_TOOL_UA`):
primer match gana, degradación honesta a "Desconocido" sin crashear.
"""
import pytest

from extensions import basa_guardian_policy as policy


@pytest.mark.parametrize("ua,expected", [
    ("claude-cli/1.2.3", "Claude Code"),
    ("GitHubCopilotChat/0.x", "GitHub Copilot"),
    ("Mozilla/5.0 (VS Code 1.9)", "VS Code"),
    ("Cursor/0.4 electron", "Cursor"),
    ("aider/0.5", "aider"),
    ("curl/8.1", "curl"),
    ("SomeRandomAgent/9", "Desconocido"),   # degrada honesto, no crashea
    ("", "Desconocido"),
    (None, "Desconocido"),
])
def test_detect_tool(ua, expected):
    assert policy.detect_tool(ua) == expected


def test_detect_tool_first_match_wins_claude_before_curl():
    # El orden de _TOOL_UA es semántica observable: 'claude' antes que 'curl'.
    assert policy.detect_tool("claude-code via curl") == "Claude Code"


def test_detect_tool_never_crashes_on_weird_input():
    for weird in ("   ", "🤖", "x" * 5000):
        assert isinstance(policy.detect_tool(weird), str)
