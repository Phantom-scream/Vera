from pathlib import Path

import pytest
from typer.testing import CliRunner

from vera.cli.app import app
from vera.config import get_settings

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


def test_cli_ingests_and_reports_idempotent_repeat(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
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
