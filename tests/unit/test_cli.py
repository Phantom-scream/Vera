import json

from typer.testing import CliRunner

from vera import __version__
from vera.cli.app import app

runner = CliRunner()


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_health_command() -> None:
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"status": "ok", "version": __version__}
