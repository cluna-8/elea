#!/usr/bin/env python3
"""Valida los enlaces markdown relativos de specs/ y de la doc interna.

POR QUÉ EXISTE. Al mover o borrar carpetas de specs se rompen dos familias de enlaces, y la
segunda es la que se olvida: los que APUNTAN a la carpeta movida —que se ven enseguida— y los
que están DENTRO de ella, cuyos `../` cambian de significado al cambiar de profundidad. A la
sesión de Eleia se le rompieron 10 así en un solo commit, y nadie se entera hasta que alguien
hace clic.

También caza el caso que había acá: un enlace a una spec de la OTRA localización
(`049-motor-generacion-documentos`, que sólo existe en Eleia), que es exactamente lo que la
convención de prefijos de ADR-0007 viene a evitar.

Salida: lista de rotos y código 1 si hay alguno, para poder colgarlo de un gate.
Uso: scripts/enlaces-rotos.py
"""
import pathlib
import re
import sys

OBJETIVO = ["specs", "docs"]
IGNORAR_PARTES = {".venv", "node_modules", "__pycache__"}
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+?)(?:\s+\"[^\"]*\")?\)")
EXTERNOS = ("http://", "https://", "mailto:", "#")

raiz = pathlib.Path(__file__).resolve().parent.parent
rotos, revisados = [], 0

for nombre in OBJETIVO:
    for md in (raiz / nombre).rglob("*.md"):
        if IGNORAR_PARTES & set(md.parts):
            continue
        for destino in LINK.findall(md.read_text(encoding="utf-8", errors="replace")):
            if destino.startswith(EXTERNOS):
                continue
            revisados += 1
            # El ancla (#L50) se recorta: el fichero existe o no, la línea no se valida.
            if not (md.parent / destino.split("#")[0]).resolve().exists():
                rotos.append(f"{md.relative_to(raiz)}  ->  {destino}")

print(f"── {revisados} enlaces relativos revisados en {', '.join(OBJETIVO)}")
if rotos:
    print(f"── {len(rotos)} ROTOS:")
    for r in sorted(rotos):
        print("   ", r)
    sys.exit(1)
print("── ninguno roto")
