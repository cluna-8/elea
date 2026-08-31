"""FR-016: ningun pyproject.toml declara dependencia hacia el paquete hermano."""
import tomllib
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parent.parent

PACKAGES = {
    "sentinel_admin_signer": CLI_ROOT / "sentinel_admin_signer" / "pyproject.toml",
    "sentinel_admin": CLI_ROOT / "sentinel_admin" / "pyproject.toml",
}


def _load(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def test_signer_pyproject_has_no_dependency_on_admin():
    data = _load(PACKAGES["sentinel_admin_signer"])
    deps = data["project"].get("dependencies", [])
    assert not any("sentinel-admin" in dep or "sentinel_admin" in dep for dep in deps)
    assert data["project"]["name"] == "sentinel-admin-signer"


def test_admin_pyproject_has_no_dependency_on_signer():
    data = _load(PACKAGES["sentinel_admin"])
    deps = data["project"].get("dependencies", [])
    assert not any("sentinel-admin-signer" in dep or "sentinel_admin_signer" in dep for dep in deps)
    assert data["project"]["name"] == "sentinel-admin"
