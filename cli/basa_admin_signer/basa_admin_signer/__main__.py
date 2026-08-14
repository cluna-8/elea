import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="basa-admin-signer")
def cli() -> None:
    """basa-admin-signer: firma de licencias BASA (uso interno Basa, offline)."""


if __name__ == "__main__":
    cli()
