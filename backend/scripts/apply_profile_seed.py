"""Aplica el seed del PERFIL de cliente (spec 020 US3 → reusa 013 US6).

Onboarding-as-data: materializa tenant + clients + connections desde el
``seed.yaml`` del perfil, idempotente (re-aplicar no duplica — claves
naturales de la 013). En el modelo v1 hay UNA instancia por cliente
(Principio VII): el tenant de la instalación es el default de la 013 y este
script le fija el ``slug`` del perfil (el UUID no cambia; dominio/DNS/
workspace derivan del slug, FR-014).

Uso (dentro del container backend):
    python scripts/apply_profile_seed.py <tenant-slug> <ruta-al-seed.yaml>
"""
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from src.database import SessionLocal  # noqa: E402
from src.models.tenant import DEFAULT_TENANT_ID, Tenant  # noqa: E402
from src.services.onboarding import seed_clients_from_config  # noqa: E402


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("uso: apply_profile_seed.py <tenant-slug> <seed.yaml>")
    slug, seed_path = sys.argv[1], sys.argv[2]
    db = SessionLocal()
    try:
        tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one()
        if tenant.slug != slug:
            print(f"tenant {tenant.id}: slug '{tenant.slug}' → '{slug}' (instancia del cliente)")
            tenant.slug = slug
            tenant.name = slug
            db.commit()
        results = seed_clients_from_config(db, tenant_slug=slug, path=seed_path)
        for r in results:
            print(f"  seed: {r}")
        print(f"✅ perfil '{slug}': {len(results)} clients sembrados (idempotente)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
