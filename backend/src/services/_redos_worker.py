"""Worker standalone del chequeo de ReDoS (spec 016) — SIN imports pesados
(nada de sqlalchemy/fastapi/etc.) a propósito: `multiprocessing` con contexto
`spawn` reimporta este módulo en el proceso hijo, y cuanto menos traiga, más
rápido arranca (relevante porque el timeout de la validación tiene que cubrir
el arranque del proceso Y el matching, no solo el matching).

Por qué un PROCESO y no un hilo (ver entity_catalog_service.py): el motor `re`
de stdlib no libera el GIL durante el backtracking — un hilo catastrófico
bloquea a TODOS los hilos del proceso, incluido el que intenta medir el
timeout. Un proceso aparte tiene su propio GIL y se puede matar de verdad.
"""
import re


def match_worker(pattern: str, text: str, result_queue) -> None:
    try:
        re.search(pattern, text)
        result_queue.put(True)
    except Exception:
        result_queue.put(False)
