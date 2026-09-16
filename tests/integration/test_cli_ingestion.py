from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from vera.cli.app import app
from vera.config import get_settings

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


def test_cli_ingests_and_reports_idempotent_repeat(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    clean_ci_environment: Callable[[], None],
) -> None:
    monkeypatch.setenv("VERA_DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    runner = CliRunner()
    arguments = [
        "ingest",
        str(FIXTURES / "simple.xml"),
        "--provider",
        "gitlab",
        "--repository",
        "startup/backend",
        "--branch",
        "main",
        "--commit-sha",
        "abc123",
        "--pipeline-id",
        "1201",
        "--job-id",
        "8891",
        "--environment",
        "staging",
    ]
    try:
        first = runner.invoke(app, arguments)
        second = runner.invoke(app, arguments)
    finally:
        get_settings.cache_clear()

    assert first.exit_code == 0, first.output
    assert "Stored test run" in first.output
    assert "1 tests, 1 passed, 0 failed, 0 skipped" in first.output
    assert second.exit_code == 0, second.output
    assert "Already stored test run" in second.output


def test_cli_auto_detects_gitlab_context(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    clean_ci_environment: Callable[[], None],
) -> None:
    # Simulate a GitHub Actions parent, then build an isolated GitLab child.
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_EVENT_PATH", "/untrusted/runner-event.json")
    clean_ci_environment()
    variables = {
        "VERA_DATABASE_URL": migrated_database_url,
        "GITLAB_CI": "true",
        "CI_PROJECT_PATH": "startup/backend",
        "CI_PROJECT_URL": "https://gitlab.example/startup/backend",
        "CI_PIPELINE_ID": "2201",
        "CI_PIPELINE_IID": "32",
        "CI_JOB_ID": "9901",
        "CI_JOB_NAME": "regression",
        "CI_COMMIT_SHA": "feedface",
        "CI_COMMIT_BRANCH": "main",
    }
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(
            app,
            ["ingest", str(FIXTURES / "simple.xml"), "--environment", "staging"],
        )
    finally:
        get_settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "Stored test run" in result.output
