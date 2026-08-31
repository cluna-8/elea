"""Genera el TrueUpExport firmado del deployment (spec 021 US5 — FR-029).

100% LOCAL (sin egress): lee la DB del deployment, arma el export con el
historial encadenado y lo firma con la deployment key. El operador lo envía a
Sentinel fuera de banda (renovación/true-up).

Uso (dentro del container backend, o con DATABASE_URL apuntando al deployment):

    python scripts/generate_trueup.py > trueup-$(date +%F).json
"""
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from src.licensing import trueup_export  # noqa: E402


def main() -> None:
    doc = trueup_export.generate_signed_export()
    json.dump(doc, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    print(f"trueup: {doc['counter']} eventos encadenados, head {doc['hash_head'][:16]}…, "
          f"seats {doc['seats_used']}/{doc['max_seats']}", file=sys.stderr)


if __name__ == "__main__":
    main()
