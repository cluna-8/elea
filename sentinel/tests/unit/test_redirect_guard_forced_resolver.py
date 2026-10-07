"""057 T-F (A): contrato E1↔E2 del enmascarado forzado entre el guard de la extensión y el guardrail de la base.

1. El guard lee el campo entero opcional `signed_thinking` del informe (el nombre que emite la base, S14) y solo con
   destino NATIVO bloquea el `thinking` firmado con detecciones.
2. Al importarse, el guard registra en la base el resolutor de forzado (`register_forced_masking_resolver`): verifica
   el token firmado `x-redirect-authz` (`fm`) y devuelve True solo si el pedido es forzado. Sin esto la base no marca
   la señal, el informe sale con `scope = "user"` y todo pedido forzado se bloquea con `masking_required`.
3. Sin sesión de base ni diccionario del cliente que valga: la señal del cliente no cuenta, el token de un pedido
   no forzado, ausente, inválido o de un modelo que no es de la pasarela no activa el forzado."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from extensions import sentinel_guardian_policy as policy
from sentinel.engine import redirect_guard as g
from sentinel.redirect import authz

KEY = "k" * 48
MODEL = "rdx-anthropic/claude-real"
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _llave(monkeypatch):
    monkeypatch.setenv(authz.KEY_ENV, KEY)


@pytest.fixture(autouse=True)
def _registro_limpio():
    policy.clear_forced_masking_resolvers()
    yield
    policy.clear_forced_masking_resolvers()
    g.register_forced_masking_resolver()               # lo deja como lo deja el import


def _token(forced=True, model=MODEL, key=KEY):
    return authz.issue(request_id="r1", scope="t1/connection:k1", destination_id="d1", model=model,
                       provider="anthropic", credential={"api_key": "sk-destino"}, api_base=None,
                       forced_masking=forced, decision={"public_id": "pro", "face": "claude"}, key=key)


def _data(tok, model=MODEL):
    hdrs = {"X-Redirect-Authz": tok} if tok else {}
    return {"model": model, "messages": [{"role": "user", "content": "hola"}],
            "proxy_server_request": {"headers": hdrs}, "metadata": {}, "litellm_metadata": {}}


# ── 1. el campo `signed_thinking` ────────────────────────────────────────────────────────────────

def test_el_campo_del_informe_se_llama_signed_thinking_como_lo_emite_la_base():
    assert g.SIGNED_THINKING_FIELD == "signed_thinking"


def test_el_informe_real_de_la_base_con_signed_thinking_bloquea_un_nativo():
    informe = {"completed": True, "degraded": False, "detected": 2, "masked": 2, "scope": "full",
               "unanalyzable": 0, "unanalyzable_kinds": [], "signed_thinking": 1}
    assert g.signed_thinking_blocks(informe, "rdx-anthropic") is True
    assert g.signed_thinking_blocks(informe, "rdx-chatcompat") is False
    assert g.signed_thinking_blocks({**informe, "signed_thinking": 0}, "rdx-anthropic") is False
    assert g.signed_thinking_blocks({k: v for k, v in informe.items() if k != "signed_thinking"},
                                    "rdx-anthropic") is False


# ── 2. el resolutor se registra al importar ──────────────────────────────────────────────────────

def test_importar_el_guard_registra_el_resolutor_en_la_base():
    rutas = [str(ROOT), str(ROOT / "litellm"), str(ROOT / "backend")]
    code = (f"import sys\nsys.path[:0] = {rutas!r}\n"
            "import extensions.sentinel_guardian_policy as p\n"
            "assert p._FORCED_MASKING_RESOLVERS == []\n"
            "from sentinel.engine import redirect_guard\n"
            "assert len(p._FORCED_MASKING_RESOLVERS) == 1, p._FORCED_MASKING_RESOLVERS\n")
    env = {**os.environ, "LITELLM_MODE": "PRODUCTION"}
    out = subprocess.run([sys.executable, "-I", "-c", code], cwd=str(ROOT), env=env, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-800:]


def test_registrar_es_idempotente():
    g.register_forced_masking_resolver()
    g.register_forced_masking_resolver()
    assert len(policy._FORCED_MASKING_RESOLVERS) == 1


def test_se_registra_en_las_dos_copias_del_modulo_de_politica_que_pueden_convivir_en_el_motor():
    """Dentro del motor el guardrail base importa `sentinel_guardian_policy` a secas y el guard puede cargarlo como
    `extensions.sentinel_guardian_policy`: son dos objetos módulo con registros independientes."""
    sys.path.insert(0, str(ROOT / "litellm" / "extensions"))
    try:
        import sentinel_guardian_policy as plano
    finally:
        sys.path.pop(0)
    plano.clear_forced_masking_resolvers()
    try:
        g.register_forced_masking_resolver()
        assert plano.resolve_forced_masking(_data(_token(True)), None, "anthropic_messages") is True
        assert policy.resolve_forced_masking(_data(_token(True)), None, "anthropic_messages") is True
    finally:
        plano.clear_forced_masking_resolvers()


def test_con_la_instancia_del_guard_tambien_queda_registrado():
    g.RedirectGuard(guardrail_name="redirect-guard")
    assert policy.resolve_forced_masking(_data(_token(True)), None, "anthropic_messages") is True


# ── 3. el resolutor decide por el token firmado ──────────────────────────────────────────────────

def test_token_firmado_con_forzado_activa_la_senal():
    g.register_forced_masking_resolver()
    assert policy.resolve_forced_masking(_data(_token(True)), None, "anthropic_messages") is True


@pytest.mark.parametrize("data", [
    _data(None),                                              # sin token
    _data("no-es-un-token"),                                  # inválido
], ids=["sin_token", "invalido"])
def test_sin_token_valido_no_hay_forzado(data):
    g.register_forced_masking_resolver()
    assert policy.resolve_forced_masking(data, None, "anthropic_messages") is False


def test_token_sin_forzado_no_activa_la_senal():
    g.register_forced_masking_resolver()
    assert policy.resolve_forced_masking(_data(_token(False)), None, "anthropic_messages") is False


def test_token_firmado_con_otra_llave_o_para_otro_modelo_no_activa_la_senal():
    g.register_forced_masking_resolver()
    assert policy.resolve_forced_masking(_data(_token(True, key="x" * 48)), None, "anthropic_messages") is False
    assert policy.resolve_forced_masking(_data(_token(True, model="rdx-anthropic/otro")), None,
                                         "anthropic_messages") is False


def test_un_modelo_que_no_es_de_la_pasarela_no_se_fuerza_aunque_traiga_token_valido():
    """Modo sombra: la pasarela firma la decisión hipotética y no cambia el destino; no debe cambiar el pedido."""
    g.register_forced_masking_resolver()
    tok = _token(True, model="gpt-4o")
    assert policy.resolve_forced_masking(_data(tok, model="gpt-4o"), None, "anthropic_messages") is False


def test_sin_la_llave_de_la_instalacion_el_resolutor_falla_cerrado(monkeypatch):
    """`REDIRECT_INTERNAL_KEY` ausente con un token presente: no se puede verificar ⇒ se trata como forzado."""
    tok = _token(True)
    monkeypatch.delenv(authz.KEY_ENV)
    g.register_forced_masking_resolver()
    assert policy.resolve_forced_masking(_data(tok), None, "anthropic_messages") is True


def test_el_resolutor_no_deja_texto_del_pedido_en_el_log(caplog):
    g.register_forced_masking_resolver()
    data = _data(_token(True))
    data["messages"][0]["content"] = "DNI 30.123.456"
    with caplog.at_level("DEBUG"):
        policy.resolve_forced_masking(data, None, "anthropic_messages")
    assert "30.123.456" not in caplog.text


def test_la_senal_que_manda_el_cliente_no_cuenta():
    g.register_forced_masking_resolver()
    data = _data(None)
    data["sentinel_forced_masking"] = {"scope": "full"}
    data["metadata"]["sentinel_forced_masking"] = {"scope": "full"}
    assert policy.trusted_forced_masking(data, data["metadata"]) is False
