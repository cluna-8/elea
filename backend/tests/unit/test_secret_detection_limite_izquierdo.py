"""Detector de secretos — la clave `sk-…` exige límite izquierdo (057 R37; hallazgo del `claude -p` real).

`"OpenAI API Key": r"sk-[a-zA-Z0-9]{10,}"` no miraba qué había ANTES del `sk-`: cualquier palabra que termine en `sk` y siga con un guion
y diez letras (`task-implementation`, `risk-assessment`, `disk-partitioning`) contaba como clave. El pedido real de Claude Code lo
dispara en el texto fijo del clasificador del modo auto (un pedido auxiliar sin herramientas, `system[1].text`): la capa
`secret_detection` lo rechazaba con `blocked_secret` aunque el pedido no llevara ninguna credencial.

Fija: (1) las palabras corrientes con `…sk-<palabra>` ya no son clave; (2) toda clave que antes se detectaba (sola, tras `=`, `:`,
comillas, paréntesis, `Bearer`, saltos de línea, pegada a una palabra falsa) se sigue detectando; (3) en el pedido de Anthropic con
alcance completo, el texto fijo del clasificador pasa y una clave real en esa misma posición bloquea.
"""
import pytest

from s14_helpers import policy  # noqa: E402

CLAVE = "sk-abcdefghij1234567890"
CLAVE_CORTA = "sk-abcdefghij"          # el mínimo del patrón (10 alfanuméricos): sigue siendo clave

PALABRAS_CORRIENTES = [
    "task-implementation", "risk-assessment", "disk-partitioning", "ask-clarification-questions",
    "Use a sub-agent for each task-specific-analysis", "high-risk-assessments", "desk-reservations",
    "mask-generation", "TASK-IMPLEMENTATION", "Task-Implementation",
]


@pytest.mark.parametrize("texto", PALABRAS_CORRIENTES)
def test_palabra_corriente_con_sk_guion_no_es_clave(texto):
    assert policy.detect_secrets(texto) == []
    assert policy.detect_secrets(f"antes {texto} después") == []


@pytest.mark.parametrize("plantilla", [
    "{k}", " {k}", "{k} al final", "OPENAI_API_KEY={k}", "api_key: {k}", 'key="{k}"', "key='{k}'", "(clave {k})", "[{k}]",
    "línea 1\n{k}\nlínea 3", "Authorization: Bearer {k}", "export X=1;{k}", "usá {k}, por favor", "`{k}`", "<{k}>",
    "https://host/?key={k}", "_{k}", "mi-clave-{k}", "task-implementation {k}", "{k} task-implementation",
])
@pytest.mark.parametrize("clave", [CLAVE, CLAVE_CORTA, "sk-" + "A1b2C3d4E5" * 5])
def test_clave_real_se_detecta_en_cada_contexto(plantilla, clave):
    assert "OpenAI API Key" in policy.detect_secrets(plantilla.format(k=clave))


def test_los_otros_patrones_no_cambian():
    assert policy.detect_secrets("Bearer " + "a" * 20) == ["Generic Secret"]
    assert policy.detect_secrets("AIzaSy" + "a" * 33) == ["Google API Key"]
    assert policy.detect_secrets("sk-corta") == []           # menos de 10: como hoy
    assert policy.detect_secrets("sk-" + "a" * 9) == []


def _pedido_claude_code(texto_system):
    """Forma del pedido auxiliar real del clasificador del modo auto: `system` en bloques, un solo mensaje, sin herramientas."""
    return {"model": "claude-sonnet-5-5", "max_tokens": 2112,
            "system": [{"type": "text", "text": "You are a classifier."}, {"type": "text", "text": texto_system}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "Classify this action."}]}]}


def _inspect(body):
    return policy.extract_inspect_text(body, scope=policy.MASKING_SCOPE_FULL, fmt="anthropic")


def test_pedido_del_clasificador_con_palabra_corriente_no_se_bloquea():
    cuerpo = _pedido_claude_code("Block actions that are out of scope or task-implementation drift; flag risk-assessment gaps.")
    assert policy.detect_secrets(_inspect(cuerpo)) == []


def test_pedido_del_clasificador_con_clave_real_se_bloquea():
    cuerpo = _pedido_claude_code(f"Block actions that are out of scope or task-implementation drift. token {CLAVE}")
    assert policy.detect_secrets(_inspect(cuerpo)) == ["OpenAI API Key"]
