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


# Una VARIABLE comentada (`# VAR=valor`, con o sin comentario al final) no es
# prosa: no describe a nadie y no puede terminar como texto de la página.
#
# El borde que obliga a ser preciso acá (#271): `.env.example:93` es una línea de
# PROSA que empieza con `SENTINEL_PURGE_ENABLED=false (el default) el scheduler ni
# arranca...`. Clasificarla como variable comentada le comería media frase al
# banner de la sección de purga. Lo que las separa es que una asignación real
# termina en el valor o en un comentario inline `#`; la prosa sigue con palabras.
_VAR_COMENTADA_RE = re.compile(r"^([A-Z][A-Z0-9_]*)=(\S*)\s*(#.*)?$")


def _split_banner_desc(lines):
    """Reparte líneas de comentario acumuladas en (banner_title, banner_body, desc).

    Un bloque de comentarios separado de la variable por una línea en blanco es
    un BANNER de sección (#241): la primera línea del banner es el TÍTULO que va
    como ``###``; el resto del banner es el CUERPO que va como párrafo
    introductorio antes de la tabla.  Los comentarios inmediatamente arriba de
    la variable (sin línea en blanco de por medio) son su DESCRIPCIÓN y van en
    la celda de la tabla — nunca concatenados al banner.
    """
    if not lines:
        return None, None, "—"
    # Última línea vacía = frontera entre banner y descripción.
    split = 0
    for i in range(len(lines) - 1, -1, -1):
        if lines[i] == "":
            split = i + 1
            break
    banner_parts = [c for c in lines[:split] if c]
    desc_parts = [c for c in lines[split:] if c]
    if banner_parts:
        banner_title = banner_parts[0]
        banner_body = " ".join(banner_parts[1:]) if len(banner_parts) > 1 else None
    else:
        banner_title = None
        banner_body = None
    desc = " ".join(desc_parts) if desc_parts else "—"
    return banner_title, banner_body, desc


def parse_env(lines):
    """Parsea líneas de .env.example → list[(var, default_mostrado, descripcion)].

    Una línea en blanco no purga el comentario acumulado (#211): un encabezado de
    sección separado de su variable por una vacía tiene que llegar a la página.

    Desde #241 los comentarios separados por una línea en blanco se clasifican
    como BANNER de sección y NO se incluyen en la descripción de la variable.
    """
    rows, pending_comment = [], []
    solo_vars_comentadas = False
    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            contenido = s.lstrip("# ").rstrip()
            if _VAR_COMENTADA_RE.match(contenido):
                solo_vars_comentadas = True
                continue
            pending_comment.append(contenido)
        elif m := re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", s):
            var, default = m.group(1), m.group(2)
            _title, _body, desc = _split_banner_desc(pending_comment)
            secretish = re.search(r"(secret|key|password|token)", var, re.I)
            shown = "*(secreto — generado por instalación)*" if secretish and default else (f"`{default}`" if default else "—")
            rows.append((var, shown, desc.replace("|", "\\|")))
            pending_comment = []
            solo_vars_comentadas = False
        elif not s:
            # Línea en blanco: la registra como separador dentro del bloque
            # acumulado para que _split_banner_desc pueda distinguir el banner
            # (antes del blank) de la descripción (después del blank).  No
            # purga: #211 garantiza que un header separado por una vacía siga
            # llegando a la página — ahora como banner, no como descripción.
            #
            # La excepción (#271): si el bloque que termina acá sólo tuvo
            # variables COMENTADAS, no va a emitir ninguna fila, así que su
            # banner quedó huérfano. Arrastrarlo lo funde con el banner de la
            # sección siguiente.
            if solo_vars_comentadas:
                pending_comment = []
                solo_vars_comentadas = False
            elif pending_comment:
                pending_comment.append("")
        else:
            pending_comment = []
            solo_vars_comentadas = False
    return rows


def parse_env_sections(lines):
    """Parsea .env.example → list[(title, body, list[(var, default, desc)])].

    Cada tupla es una SECCIÓN: ``title`` es la primera línea del banner (o
    ``None`` si no hay), ``body`` es el resto del banner (o ``None``) y la
    lista de filas que pertenecen a esa sección.  Las filas son las mismas
    tuplas ``(var, default, desc)`` de ``parse_env``.

    Una nueva sección inicia cuando un comentario-banner distinto del actual
    aparece, o cuando una línea en blanco marca un nuevo bloque de variables
    sin banner (sección sin ``###``).
    """
    sections, pending_comment = [], []
    current_title = None
    current_body = None
    current_rows = []
    last_had_blank = False
    section_has_banner = False
    solo_vars_comentadas = False

    def _flush_section():
        nonlocal current_title, current_body, current_rows, section_has_banner
        if current_rows:
            sections.append((current_title, current_body, current_rows))
        current_rows = []
        section_has_banner = False

    for line in lines:
        s = line.strip()
        if s.startswith("#"):
            contenido = s.lstrip("# ").rstrip()
            if _VAR_COMENTADA_RE.match(contenido):
                # Variable comentada: no emite fila y no es prosa (#271).
                solo_vars_comentadas = True
                continue
            pending_comment.append(contenido)
        elif m := re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", s):
            var, default = m.group(1), m.group(2)
            title, body, desc = _split_banner_desc(pending_comment)
            secretish = re.search(r"(secret|key|password|token)", var, re.I)
            shown = "*(secreto — generado por instalación)*" if secretish and default else (f"`{default}`" if default else "—")
            row = (var, shown, desc.replace("|", "\\|"))
            if title and title != current_title:
                # Banner distinto: nueva sección con título.
                _flush_section()
                current_title = title
                current_body = body
                section_has_banner = True
            elif not title and last_had_blank and not section_has_banner and current_rows:
                # Sin banner, separado por blank, y la sección actual tampoco
                # tiene banner: cambio de contexto, nueva sección sin título.
                _flush_section()
                current_title = None
                current_body = None
            # Si la sección actual tiene banner, las vars sin banner quedan en
            # ella (p.ej. vars del motor de IA, cubiertas por un banner, tienen
            # descripciones separadas por blank pero misma sección).
            current_rows.append(row)
            pending_comment = []
            last_had_blank = False
            solo_vars_comentadas = False
        elif not s:
            # Un bloque cuyas variables están TODAS comentadas no emite filas: su
            # banner no tiene a quién titular y arrastrarlo lo funde con el de la
            # sección siguiente, que termina archivando variables ajenas bajo un
            # `###` que no es el suyo (#271).
            if solo_vars_comentadas:
                pending_comment = []
                solo_vars_comentadas = False
            elif pending_comment:
                pending_comment.append("")
            last_had_blank = True
        else:
            pending_comment = []
            last_had_blank = False
            solo_vars_comentadas = False

    _flush_section()
    return sections


_TABLE_HEADER = ["| Variable | Default | Descripción |", "|---|---|---|"]


def _render_section(title, body, rows):
    """Emite el markdown de una sección: ``### title`` + cuerpo + tabla."""
    out = []
    if title:
        out += [f"### {title}", ""]
    if body:
        out += [body, ""]
    out += _TABLE_HEADER[:]
    out += [f"| `{v}` | {d} | {c} |" for v, d, c in rows]
    out.append("")
    return out


def generate(src=SRC, dest=DEST):
    sections = parse_env_sections(src.read_text().splitlines())
    out = [
        "# Configuración (variables de entorno)",
        "",
        "!!! info \"Página generada — no editar a mano\"",
        "    Esta referencia se genera del `.env.example` del producto (una sola fuente de",
        "    verdad). Los valores marcados como secretos los genera cada instalación — jamás",
        "    hay defaults sensibles.",
        "",
    ]
    for title, body, rows in sections:
        out += _render_section(title, body, rows)
    dest.write_text("\n".join(out) + "\n")
    # flat rows (compatibilidad con callers que esperan la lista plana)
    flat = [row for _, _, rows in sections for row in rows]
    return flat


if __name__ == "__main__":
    rows = generate()
    print(f"✅ {DEST.relative_to(REPO)}: {len(rows)} variables desde .env.example", file=sys.stderr)
