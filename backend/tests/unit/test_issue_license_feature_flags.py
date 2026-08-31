"""`issue_license.py --feature-flags` — el emisor que habilita features (T018, 017 US2).

Por qué existe: hasta ahora el script hardcodeaba `"feature_flags": []`, así que la
ÚNICA forma de emitir una licencia con features era `issue_dev_license.py`, que
regenera el par Ed25519 y sobreescribe el keyset entero (guarda del 27-jul). El E2E
de SSO necesita el flag `sso`; la vía es ésta, no la destructiva.

El test que manda es `test_la_licencia_emitida_habilita_la_feature_de_verdad`: no
mira el JSON, corre el **verificador real** del producto y pregunta lo mismo que
pregunta el gate del router (`feature_enabled("sso")`). Un cambio que rompa la firma,
el orden canónico o el round-trip de los flags lo pone rojo.
"""
import json
import pathlib
import subprocess
import sys

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SRC))

import issue_license  # noqa: E402
from licensing import verifier as verifier_mod  # noqa: E402

KID = "sentinel-test-flags"
TENANT = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def firmante(tmp_path):
    """Par Ed25519 efímero + keyset propio. Nunca toca el keyset embebido del
    producto — que es justamente el pecado del script destructivo."""
    priv = Ed25519PrivateKey.generate()
    key_path = tmp_path / "signing.pem"
    key_path.write_bytes(priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    pub_pem = priv.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    keyset_path = tmp_path / "keyset.pem"
    keyset_path.write_text(f"# key_id: {KID}\n{pub_pem}")
    return key_path, keyset_path


def _emitir(firmante, tmp_path, *extra):
    key_path, keyset_path = firmante
    out = tmp_path / "salida.lic"
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "issue_license.py"),
         "--key", str(key_path), "--kid", KID,
         "--lic-id", "lic_test_0001", "--tenant-id", TENANT,
         "--distributor-id", "d_sentinel", "--pool-id", "pool_test",
         "--max-seats", "5", "--expiry", "2099-01-01T00:00:00Z",
         "--keyset", str(keyset_path), "--out", str(out), "--force", *extra],
        capture_output=True, text=True,
    )
    return proc, out


# --- el parser, aislado -------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    (["sso"], ["sso"]),
    (["sso,monitor"], ["sso", "monitor"]),          # separado por comas
    (["sso", "monitor"], ["sso", "monitor"]),        # repetido
    ([" sso , monitor "], ["sso", "monitor"]),       # espacios alrededor: se limpian
    (["sso,,monitor"], ["sso", "monitor"]),          # vacío intermedio: se descarta
    (["sso,sso"], ["sso"]),                          # idempotente
    ([], []),
    (None, []),
])
def test_parse_feature_flags(entrada, esperado):
    assert issue_license.parse_feature_flags(entrada) == esperado


@pytest.mark.parametrize("malo", ["SSO", "Sso", "sso extra", "ssó", "s so"])
def test_un_flag_que_el_producto_no_podria_consultar_se_rechaza(malo):
    """`feature_enabled` compara por igualdad exacta contra literales en minúscula.
    Aceptar 'SSO' emitiría una licencia válida y firmada con la feature APAGADA —
    el no-op silencioso que sólo se descubre en la instalación del cliente."""
    with pytest.raises(SystemExit) as exc:
        issue_license.parse_feature_flags([malo])
    assert "no es un flag válido" in str(exc.value)


# --- el emisor de punta a punta, contra el verificador REAL --------------------

def test_la_licencia_emitida_habilita_la_feature_de_verdad(firmante, tmp_path):
    """El gate del router pregunta `token.feature_enabled("sso")`. Esto pregunta lo
    mismo, sobre el `.lic` que el script acaba de firmar, con el verificador del
    producto — no leyendo el JSON."""
    proc, out = _emitir(firmante, tmp_path, "--feature-flags", "sso")
    assert proc.returncode == 0, proc.stderr

    _key_path, keyset_path = firmante
    keyset = verifier_mod.SentinelPublicKeySet.from_pem_file(str(keyset_path))
    token = verifier_mod.verify_license_blob(
        out.read_text(encoding="utf-8"), keyset, expected_tenant_id=TENANT)

    assert token.feature_enabled("sso") is True
    assert token.feature_enabled("monitor") is False   # lo que no se pidió, no entra


def test_sin_el_argumento_la_licencia_sale_sin_features(firmante, tmp_path):
    """El default sigue siendo la lista vacía: agregar el argumento no puede
    habilitar features de callado en las licencias que ya se emiten así."""
    proc, out = _emitir(firmante, tmp_path)
    assert proc.returncode == 0, proc.stderr

    _key_path, keyset_path = firmante
    keyset = verifier_mod.SentinelPublicKeySet.from_pem_file(str(keyset_path))
    token = verifier_mod.verify_license_blob(
        out.read_text(encoding="utf-8"), keyset, expected_tenant_id=TENANT)

    assert token.feature_flags == ()
    assert token.feature_enabled("sso") is False


def test_el_operador_ve_los_flags_en_el_resumen(firmante, tmp_path):
    """Señal positiva: emitir una licencia sin ver qué features quedaron habilitadas
    es cómo se llega a la instalación del cliente con el SSO apagado.

    Alcance honesto: esto pinea que el resumen LISTA los flags, no de dónde los saca.
    El código los imprime desde el token re-verificado a propósito —misma lectura que
    hará el producto—, pero con el emisor sano ambas fuentes coinciden, así que un
    test no puede distinguirlas; mutar la fuente deja esta aserción verde (medido).
    Quien cubre el round-trip de verdad es
    `test_la_licencia_emitida_habilita_la_feature_de_verdad`.
    """
    proc, _out = _emitir(firmante, tmp_path, "--feature-flags", "sso,monitor")
    assert proc.returncode == 0, proc.stderr
    assert "feature_flags=['sso', 'monitor']" in proc.stdout


def test_el_emisor_no_escribe_el_keyset(firmante, tmp_path):
    """La razón de ser de este script frente al destructivo: el keyset se lee para
    verificar y no se toca. Si esto se rompe, el script se volvió el footgun que
    vino a reemplazar."""
    _key_path, keyset_path = firmante
    antes = keyset_path.read_bytes()
    proc, _out = _emitir(firmante, tmp_path, "--feature-flags", "sso")
    assert proc.returncode == 0, proc.stderr
    assert keyset_path.read_bytes() == antes


def test_los_flags_viajan_en_el_payload_firmado_no_al_lado(firmante, tmp_path):
    """`feature_flags` es parte del payload canónico que se firma (token.py los
    lista en los campos canónicos): si viajara fuera de la firma, cualquiera podría
    habilitarse features editando el `.lic`."""
    proc, out = _emitir(firmante, tmp_path, "--feature-flags", "sso")
    assert proc.returncode == 0, proc.stderr

    documento = json.loads(out.read_text(encoding="utf-8"))
    assert documento["feature_flags"] == ["sso"]

    documento["feature_flags"] = ["sso", "monitor"]      # manipulación
    manipulado = json.dumps(documento, ensure_ascii=False, indent=2) + "\n"
    _key_path, keyset_path = firmante
    keyset = verifier_mod.SentinelPublicKeySet.from_pem_file(str(keyset_path))
    with pytest.raises(Exception):
        verifier_mod.verify_license_blob(manipulado, keyset, expected_tenant_id=TENANT)
