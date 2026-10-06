#!/usr/bin/env python3
"""Fusión de fragmentos de perfil en un config.yaml del motor ya renderizado (research D13/D21).

Helper ÚNICO para los caminos propios de Sentinel que no pasan por `render_profile.sh` de la
base (deploy de nix, release, instalador de la 065). Implementa el **mismo contrato** que la
costura S11 (`deploy/release/merge_profile_fragments.py` en la base, PR `feat/deploy-profile-
fragments`), así el resultado es idéntico por cualquiera de los caminos:

  · un fragmento es un mapping que solo puede traer `model_list` y/o `guardrails` (listas);
  · sus entradas se AGREGAN AL FINAL de las del perfil, en el orden de los fragmentos (el
    guardrail del fragmento queda después del de la base y ve su `masking_report`, D16);
  · `model_name` o `guardrail_name` repetidos (contra el perfil o entre fragmentos) ⇒ error;
  · cualquier otra clave top-level ⇒ error; los fragmentos se toman literales (sin envsubst);
  · escritura atómica; el config se re-serializa con PyYAML (se pierden comentarios).

Uso: fragment_merge.py <config.yaml> <fragmento.yaml | directorio>...
Un directorio aporta sus `*.yaml` (no recursivo, orden por nombre). Solo stdlib + PyYAML.
"""
from __future__ import annotations

import os
import sys
import tempfile

KEYS = {"model_list": "model_name", "guardrails": "guardrail_name"}


class FragmentError(ValueError):
    pass


def _yaml():
    try:
        import yaml
    except ImportError:  # pragma: no cover
        raise FragmentError("hace falta python3 con PyYAML (pip install pyyaml)") from None
    return yaml


def merge(config: dict, fragments) -> dict:
    """`fragments`: iterable de (nombre, mapping). Devuelve un config NUEVO; no muta la entrada."""
    if not isinstance(config, dict):
        raise FragmentError("el config no es un mapping YAML")
    out = dict(config)
    seen = {}
    for key, id_field in KEYS.items():
        entries = out.get(key) or []
        seen[key] = {e.get(id_field): "perfil" for e in entries if isinstance(e, dict)}
    for name, frag in fragments:
        if not isinstance(frag, dict) or not frag:
            raise FragmentError(f"fragmento {name}: tiene que ser un mapping con model_list y/o guardrails")
        extra = sorted(set(frag) - set(KEYS))
        if extra:
            raise FragmentError(f"fragmento {name}: claves no permitidas {extra} (sólo model_list, guardrails)")
        for key, id_field in KEYS.items():
            if key not in frag:
                continue
            entries = frag[key]
            if not isinstance(entries, list):
                raise FragmentError(f"fragmento {name}: '{key}' tiene que ser una lista")
            for entry in entries:
                ident = entry.get(id_field) if isinstance(entry, dict) else None
                if not ident:
                    raise FragmentError(f"fragmento {name}: entrada de '{key}' sin '{id_field}'")
                if ident in seen[key]:
                    raise FragmentError(f"fragmento {name}: {id_field} '{ident}' duplicado "
                                        f"(ya en {seen[key][ident]})")
                seen[key][ident] = name
            out[key] = list(out.get(key) or []) + list(entries)
    return out


def _fragment_paths(args) -> list:
    paths = []
    for a in args:
        if os.path.isdir(a):
            found = sorted(f for f in os.listdir(a) if f.endswith(".yaml"))
            if not found:
                raise FragmentError(f"el directorio de fragmentos no contiene ningún *.yaml: {a}")
            paths += [os.path.join(a, f) for f in found]
        elif os.path.isfile(a):
            paths.append(a)
        else:
            raise FragmentError(f"fragmento inexistente: {a}")
    return paths


def merge_file(config_path: str, fragment_args) -> int:
    yaml = _yaml()
    with open(config_path, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    frags = []
    for p in _fragment_paths(fragment_args):
        with open(p, encoding="utf-8") as fh:
            frags.append((os.path.basename(p), yaml.safe_load(fh)))
    merged = merge(config, frags)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(config_path)))
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        yaml.safe_dump(merged, fh, sort_keys=False, allow_unicode=True, default_flow_style=False)
    os.chmod(tmp, os.stat(config_path).st_mode & 0o777)
    os.replace(tmp, config_path)
    return len(frags)


def main(argv) -> int:
    if len(argv) < 3:
        print("uso: fragment_merge.py <config.yaml> <fragmento.yaml|dir>...", file=sys.stderr)
        return 2
    try:
        n = merge_file(argv[1], argv[2:])
    except FragmentError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    print(f"── {argv[1]} + {n} fragmento(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
