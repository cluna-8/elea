"""FR-016: ningun pyproject.toml declara dependencia hacia el paquete hermano."""
import tomllib
from pathlib import Path

CLI_ROOT = Path(__file__).resolve().parent.parent

PACKAGES = {
    "basa_admin_signer": CLI_ROOT / "basa_admin_signer" / "pyproject.toml",
    "basa_admin": CLI_ROOT / "basa_admin" / "pyproject.toml",
}


def _load(path: Path) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def test_signer_pyproject_has_no_dependency_on_admin():
    data = _load(PACKAGES["basa_admin_signer"])
    deps = data["project"].get("dependencies", [])
    assert not any("basa-admin" in dep or "basa_admin" in dep for dep in deps)
    assert data["project"]["name"] == "basa-admin-signer"


def test_admin_pyproject_has_no_dependency_on_signer():
    data = _load(PACKAGES["basa_admin"])
    deps = data["project"].get("dependencies", [])
    assert not any("basa-admin-signer" in dep or "basa_admin_signer" in dep for dep in deps)
    assert data["project"]["name"] == "basa-admin"
