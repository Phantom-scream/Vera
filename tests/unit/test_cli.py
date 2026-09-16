import json
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError
from typer.testing import CliRunner

from vera import __version__
from vera.cli import app as cli_module
from vera.cli.app import app
from vera.config import get_settings

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


def test_context_command_emits_normalized_json_without_tokens(
    clean_ci_environment: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITLAB_CI", "true")
    clean_ci_environment()
    get_settings.cache_clear()
    result = runner.invoke(
        app,
        ["context", "--json"],
        env={
            "GITHUB_ACTIONS": "true",
            "GITHUB_REPOSITORY": "acme/api",
            "GITHUB_RUN_ID": "9001",
            "GITHUB_JOB": "tests",
            "GITHUB_RUN_ATTEMPT": "3",
            "GITHUB_TOKEN": "top-secret-token",
        },
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "github"
    assert payload["context"]["ci"]["run_attempt"] == 3
    assert "top-secret-token" not in result.stdout
    get_settings.cache_clear()


def test_context_command_reports_local_mode(clean_ci_environment: Callable[[], None]) -> None:
    get_settings.cache_clear()
    result = runner.invoke(app, ["context", "--json"], env={"VERA_CI_PROVIDER_OVERRIDE": "local"})

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"context": None, "mode": "local"}
    get_settings.cache_clear()


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


@pytest.mark.parametrize(
    ("command", "helper"), [("compare", "_compare_run"), ("regressions", "_regressions")]
)
def test_comparison_database_errors_do_not_print_sensitive_parameters(
    command: str, helper: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(*args: object) -> None:
        raise SQLAlchemyError("sensitive-database-parameter")

    monkeypatch.setattr(cli_module, helper, fail)
    result = runner.invoke(app, [command, str(uuid4())])
    assert result.exit_code == 1
    assert "database operation failed" in result.output
    assert "sensitive-database-parameter" not in result.output
