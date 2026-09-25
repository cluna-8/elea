"""Migraciones adicionales (seam de extensión): ALEMBIC_EXTRA_VERSION_LOCATIONS.

Un paquete externo trae sus propias migraciones alembic sin copiarlas a
`alembic/versions`:

    ALEMBIC_EXTRA_VERSION_LOCATIONS=/opt/ext/migrations,/opt/otra/migrations
    # separadas por coma o por os.pathsep (":" en Linux)

Cada directorio extra es una RAMA propia del árbol (su primera revisión con
`branch_labels` y `down_revision` = None o una revisión del core), así que con la env
puesta hay más de un head y los entrypoints migran a `heads`.

Decisiones:
- Sin la env (o vacía) no se toca nada: `version_locations` sigue en None, un solo head,
  `upgrade head` como siempre. Las harness de migración del core no se enteran.
- Se engancha en `alembic/env.py` y no en el `Config`: así vale IGUAL para el arranque
  de la app (`command.upgrade`) y para el CLI (`alembic upgrade`), que lee el .ini antes
  de que nadie pueda tocarlo. Límite: los comandos que no corren env.py (`alembic heads`,
  `history`) no ven las ramas extra.
- Un directorio declarado que no existe levanta error: alembic lo saltearía en silencio y
  la extensión quedaría sin migrar.
"""
from __future__ import annotations

import os
import re

from alembic.script import ScriptDirectory
from alembic.script.revision import RevisionMap


class MigrationLocationError(RuntimeError):
    """Un directorio de ALEMBIC_EXTRA_VERSION_LOCATIONS no existe."""


def extra_version_locations(raw: str | None = None) -> list[str]:
    """Directorios extra declarados (env por default), sin vacíos ni espacios."""
    if raw is None:
        raw = os.getenv("ALEMBIC_EXTRA_VERSION_LOCATIONS", "")
    return [p.strip() for p in re.split(rf"[,{re.escape(os.pathsep)}]", raw) if p.strip()]


def upgrade_target(raw: str | None = None) -> str:
    """`heads` si hay ramas extra, `head` (el comportamiento de siempre) si no."""
    return "heads" if extra_version_locations(raw) else "head"


def extend_script_directory(script: ScriptDirectory, raw: str | None = None) -> None:
    """Suma los directorios extra al ScriptDirectory que alembic ya armó (idempotente)."""
    extras = [os.path.abspath(p) for p in extra_version_locations(raw)]
    if not extras:
        return
    for d in extras:
        if not os.path.isdir(d):
            raise MigrationLocationError(
                f"ALEMBIC_EXTRA_VERSION_LOCATIONS: el directorio {d!r} no existe"
            )
    locations = list(script._version_locations)
    locations += [d for d in extras if d not in locations]
    script.version_locations = locations
    # alembic cachea las rutas y el mapa de revisiones (lazy, se arma recién al resolver
    # el target): se invalidan para que el upgrade en curso vea las ramas nuevas.
    script.__dict__.pop("_version_locations", None)
    script.revision_map = RevisionMap(script._load_revisions)
