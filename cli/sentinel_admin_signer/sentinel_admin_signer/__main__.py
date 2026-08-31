import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="sentinel-admin-signer")
def cli() -> None:
    """sentinel-admin-signer: firma de licencias SENTINEL (uso interno Sentinel, offline)."""


if __name__ == "__main__":
    cli()
