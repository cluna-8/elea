import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="sentinel-admin")
def cli() -> None:
    """sentinel-admin: instalacion y operacion offline de un cliente Sentinel."""


if __name__ == "__main__":
    cli()
