"""Genera el config/env reference del sitio (spec 022 US5, FR-017) desde .env.example.

UNA fuente de verdad para las variables: este script parsea el .env.example de la raíz
(comentarios inmediatamente arriba de cada VAR = descripción) y emite la página
markdown. Jamás se edita la página a mano (el check de deriva regenera y diffea).

Uso: python3 docs/gen_config_reference.py  (desde la raíz del repo)
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / ".env.example"
DEST = REPO / "docs" / "docs" / "api-reference" / "configuration.md"


def parse_env(lines):
    """Parsea líneas de .env.example → list[(var, default_mostrado, descripcion)].

    Una línea en blanco no purga el comentario acumulado (#211): un encabezado de
    sección separado de su variable por una vacía tiene que llegar a la página.
    """
    rows, pending_comment = [], []
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            pending_comment.append(s.lstrip("# ").rstrip())
        elif m := re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", s):
            var, default = m.group(1), m.group(2)
            desc = " ".join(c for c in pending_comment if c) or "—"
            secretish = re.search(r"(secret|key|password|token)", var, re.I)
            shown = "*(secreto — generado por instalación)*" if secretish and default else (f"`{default}`" if default else "—")
            rows.append((var, shown, desc.replace("|", "\\|")))
            pending_comment = []
        elif s:
            pending_comment = []
    return rows


def generate(src=SRC, dest=DEST):
    rows = parse_env(src.read_text().splitlines())
    out = [
        "# Configuración (variables de entorno)",
        "",
        "!!! info \"Página generada — no editar a mano\"",
        "    Esta referencia se genera del `.env.example` del producto (una sola fuente de",
        "    verdad). Los valores marcados como secretos los genera cada instalación — jamás",
        "    hay defaults sensibles.",
        "",
        "| Variable | Default | Descripción |",
        "|---|---|---|",
    ]
    out += [f"| `{v}` | {d} | {c} |" for v, d, c in rows]
    dest.write_text("\n".join(out) + "\n")
    return rows


if __name__ == "__main__":
    rows = generate()
    print(f"✅ {DEST.relative_to(REPO)}: {len(rows)} variables desde .env.example", file=sys.stderr)
