import json
from pathlib import Path

from typer.testing import CliRunner

from vera import __version__
from vera.cli.app import app

runner = CliRunner()
FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


def test_version_option() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


def test_health_command() -> None:
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"status": "ok", "version": __version__}


def test_ingest_returns_nonzero_for_malformed_xml() -> None:
    result = runner.invoke(
        app,
        [
            "ingest",
            str(FIXTURES / "malformed.xml"),
            "--provider",
            "gitlab",
            "--repository",
            "startup/backend",
            "--pipeline-id",
            "1201",
            "--job-id",
            "8891",
        ],
    )

    assert result.exit_code == 1
    assert "Malformed or unsafe JUnit XML" in result.output
