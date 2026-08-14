from click.testing import CliRunner

from basa_admin_signer import __version__
from basa_admin_signer.__main__ import cli


def test_version_reports_prog_name_and_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "basa-admin-signer" in result.output
    assert __version__ in result.output


def test_help_exits_zero():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0


def test_no_command_shows_usage_not_traceback():
    result = CliRunner().invoke(cli, [])
    assert result.exit_code == 0
    assert result.exception is None
