"""Emite una licencia firmada para una instalación concreta. Parametrizado y NO destructivo.

Por qué existe (2026-07-27): la única herramienta de emisión era `issue_dev_license.py`, y
es un footgun. Tiene el payload hardcodeado (50 seats, kid fijo) y **regenera el par Ed25519
sobrescribiendo el keyset público completo con una sola clave**. Correrlo en una instalación
viva invalida su licencia en caliente (kid desconocido → estado `invalid` → 403 en TODAS las
altas). Y está horneado en la imagen de producción, así que un
`docker compose exec backend python scripts/issue_dev_license.py` bien intencionado tumba el
alta de usuarios del cliente.

Este script, en cambio:
  - toma TODO por argumento (nada hardcodeado),
  - firma con una clave privada YA EXISTENTE (jamás genera un par),
  - NUNCA escribe el keyset público,
  - verifica la licencia recién emitida contra el keyset ANTES de escribirla a disco, así
    que no se puede producir un `.lic` que la instalación vaya a rechazar.

El hogar definitivo de esto es la CLI `sentinel-admin` de la spec 026 (que documenta este mismo
footgun); mientras esa no exista, esto es el procedimiento reproducible mínimo.

Uso (reemitir el piloto de la Cámara con más asientos):

    python backend/scripts/issue_license.py \
      --key backend/scripts/license_out/signing_key_sentinel-dev-2026b.pem \
      --kid sentinel-dev-2026b \
      --lic-id lic_piloto_camara_0002 \
      --tenant-id 00000000-0000-0000-0000-000000000001 \
      --distributor-id d_sentinel --pool-id pool_pilotos_sentinel \
      --max-seats 300 --expiry 2026-10-21T00:00:00Z \
      --out backend/scripts/license_out/camara-comercio-300.lic

Habilitar una feature (el SSO del E2E de la 017 US2):

    python backend/scripts/issue_license.py \
      --key <privada del kid> --kid sentinel-dev-2026b \
      --lic-id lic_dev_sso_0001 \
      --tenant-id 00000000-0000-0000-0000-000000000001 \
      --distributor-id d_sentinel --pool-id pool_sentinel_dev \
      --max-seats 50 --expiry 2099-01-01T00:00:00Z \
      --feature-flags sso \
      --out backend/scripts/license_out/dev-sso.lic

Sin `--feature-flags` la licencia sale con la lista VACÍA, y una feature ausente es
OFF fail-closed: el router de SSO devuelve 403 aunque el código esté en `main`.

Notas de operación aprendidas del piloto:
  - Reusar un kid que YA está en el keyset embebido. Un kid nuevo exige rebuild de la imagen,
    porque el keyset se lee del path horneado (el compose no setea
    SENTINEL_LICENSE_PUBLIC_KEYS_FILE).
  - `--not-before` por default es "ahora - 1h": el reloj de la VM del cliente puede ir
    atrasado, y un not_before futuro deja la licencia `invalid` y bloquea todas las altas.
  - Un "seat" es una Connection (fila APIKey) activa, NO una persona. Una persona con dos
    herramientas consume dos. Dimensionar con holgura: ampliar en caliente funciona pero
    tiene una ventana de ~5 min con 402 intermitentes (un thread de reconciliación por
    worker de uvicorn).
"""
import argparse
import base64
import json
import pathlib
import re
import sys
from datetime import datetime, timedelta, timezone

# El paquete `licensing` es la fuente de verdad de la forma canónica y de la verificación:
# firmar con una copia local del algoritmo es cómo se emiten licencias que no validan.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from licensing import token as token_mod  # noqa: E402
from licensing import verifier as verifier_mod  # noqa: E402

DEFAULT_KEYSET = pathlib.Path(__file__).resolve().parents[1] / "src" / "keys" / "sentinel_public_keys.pem"

# Forma de un flag consultable por el producto: los consumidores usan literales en
# minúscula y el chequeo es por igualdad exacta.
_FLAG_RE = re.compile(r"[a-z0-9_-]+")


def parse_feature_flags(values) -> list:
    """`--feature-flags sso,monitor` (repetible) → `["sso", "monitor"]`.

    `LicenseToken.feature_enabled` compara por igualdad EXACTA (`flag in
    feature_flags`, token.py), y todos los consumidores del código consultan
    literales en minúscula (`SSO_FLAG = "sso"`). Un flag con mayúsculas, espacio
    interior o acento produce una licencia que se emite, firma y VERIFICA bien, y
    que sin embargo deja la feature apagada para siempre — un no-op silencioso que
    sólo se descubre en el cliente. Por eso esto rechaza en vez de normalizar: no
    adivina qué quiso escribir el operador, le dice que lo escriba bien.

    No hay allowlist de flags a propósito: la lista de features vive en quien las
    consulta, y hornearla acá haría que un flag nuevo exija tocar el emisor.
    """
    flags = []
    for value in values or []:
        for bruto in value.split(","):
            flag = bruto.strip()
            if not flag:
                continue
            if not _FLAG_RE.fullmatch(flag):
                sys.exit(
                    f"❌ --feature-flags: {flag!r} no es un flag válido.\n"
                    "   Se admite [a-z0-9_-]+ (minúsculas). El chequeo del producto es por\n"
                    "   igualdad exacta, así que 'SSO' o 'sso ' emitirían una licencia\n"
                    "   válida con la feature APAGADA."
                )
            if flag not in flags:      # idempotente: repetir un flag no lo duplica
                flags.append(flag)
    return flags


def _iso(value: str, field: str) -> str:
    """Normaliza a ISO 8601 con timezone — el verificador rechaza los naive."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(f"❌ --{field} no es ISO 8601: {value!r}")
    if parsed.tzinfo is None:
        sys.exit(f"❌ --{field} debe llevar zona horaria (usá el sufijo Z)")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    p = argparse.ArgumentParser(description="Emite una licencia firmada (no destructivo).")
    p.add_argument("--key", required=True, help="privada Ed25519 (PEM) del kid a usar")
    p.add_argument("--kid", required=True, help="kid, TIENE que existir ya en el keyset")
    p.add_argument("--lic-id", required=True)
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--distributor-id", required=True)
    p.add_argument("--pool-id", required=True)
    p.add_argument("--max-seats", required=True, type=int)
    p.add_argument("--expiry", required=True, help="ISO 8601 con Z")
    p.add_argument("--not-before", default=None,
                   help="ISO 8601 con Z (default: ahora - 1h, por si el reloj del cliente atrasa)")
    p.add_argument("--grace-days", type=int, default=14)
    p.add_argument("--feature-flags", action="append", default=[], metavar="FLAG[,FLAG...]",
                   help="features que habilita la licencia (repetible o separado por comas). "
                        "Sin esto la licencia sale SIN features: el SSO, por ejemplo, "
                        "fail-closea con 403 aunque el código esté en main.")
    p.add_argument("--keyset", default=str(DEFAULT_KEYSET),
                   help="keyset público contra el que se VERIFICA antes de escribir")
    p.add_argument("--out", required=True)
    p.add_argument("--force", action="store_true", help="sobrescribir el .lic de salida si existe")
    a = p.parse_args()

    if a.max_seats < 1:
        sys.exit("❌ --max-seats tiene que ser >= 1")

    out = pathlib.Path(a.out)
    if out.exists() and not a.force:
        sys.exit(f"❌ {out} ya existe. Usá --force si de verdad querés reemplazarlo.")

    not_before = _iso(a.not_before, "not-before") if a.not_before else (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat().replace("+00:00", "Z")

    feature_flags = parse_feature_flags(a.feature_flags)

    payload = {
        "schema": token_mod.SUPPORTED_SCHEMA,
        "lic_id": a.lic_id,
        "kid": a.kid,
        "tenant_id": a.tenant_id,
        "distributor_id": a.distributor_id,
        "pool_id": a.pool_id,
        "max_seats": a.max_seats,
        "not_before": not_before,
        "expiry": _iso(a.expiry, "expiry"),
        "grace_days": a.grace_days,
        "feature_flags": feature_flags,
        "issued_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    priv = serialization.load_pem_private_key(pathlib.Path(a.key).read_bytes(), password=None)
    if not isinstance(priv, Ed25519PrivateKey):
        sys.exit("❌ la clave no es Ed25519")

    signature = priv.sign(token_mod.canonical_payload_bytes(payload))
    # CON padding: el verificador usa `base64.urlsafe_b64decode`, que exige los '='
    # (quitarlos produce un .lic que se rechaza como "firma no es base64url").
    blob = json.dumps(
        {**payload, "sig": base64.urlsafe_b64encode(signature).decode()},
        ensure_ascii=False, indent=2,
    ) + "\n"

    # Verificación ANTES de escribir: si el kid no está en el keyset o la firma no cuadra,
    # la instalación rechazaría el fichero. Mejor fallar acá que en la sede del cliente.
    keyset = verifier_mod.SentinelPublicKeySet.from_pem_file(a.keyset)
    verified = verifier_mod.verify_license_blob(blob, keyset, expected_tenant_id=a.tenant_id)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(blob, encoding="utf-8")
    print(f"✅ licencia emitida y verificada: {out}")
    # `LicenseToken` usa los nombres CONCEPTUALES de la spec (license_id/key_id), no los
    # del wire format (lic_id/kid).
    print(f"   license_id={verified.license_id} key_id={verified.key_id} "
          f"max_seats={verified.max_seats}")
    print(f"   not_before={payload['not_before']} expiry={payload['expiry']} "
          f"grace_days={a.grace_days}")
    # Del token VERIFICADO, no de los argumentos: es la única lectura que prueba que los
    # flags sobrevivieron la firma y el re-parseo tal como el producto los va a consultar.
    print(f"   feature_flags={list(verified.feature_flags) or '[] (ninguna feature habilitada)'}")
    print("   El keyset público NO se tocó.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
