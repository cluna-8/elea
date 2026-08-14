import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="basa-admin")
def cli() -> None:
    """basa-admin: instalacion y operacion offline de un cliente Basa."""


if __name__ == "__main__":
    cli()
