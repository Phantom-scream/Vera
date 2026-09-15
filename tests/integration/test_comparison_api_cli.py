import json
import re
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from typer.testing import CliRunner

from vera.api import create_app
from vera.cli.app import app as cli_app
from vera.config import Settings, get_settings

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


async def test_api_comparison_persistence_pagination_and_filtering(
    migrated_database_url: str,
) -> None:
    app = create_app(Settings(database_url=migrated_database_url, _env_file=None))
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        run_ids = []
        for sequence, filename in enumerate(
            ["regression_baseline.xml", "regression_current.xml"], start=1
        ):
            response = await client.post(
                "/api/v1/test-runs/ingest",
                data={
                    "provider": "local",
                    "repository": "acme/backend",
                    "pipeline_id": str(sequence),
                    "job_id": "tests",
                    "branch": "main",
                },
                files={"report": (filename, (FIXTURES / filename).read_bytes(), "application/xml")},
            )
            assert response.status_code == 201
            run_ids.append(response.json()["test_run"]["id"])
        no_baseline = await client.post(f"/api/v1/test-runs/{run_ids[0]}/compare")
        created = await client.post(f"/api/v1/test-runs/{run_ids[1]}/compare")
        repeated = await client.post(f"/api/v1/test-runs/{run_ids[1]}/compare")
        comparison_id = created.json()["comparison"]["id"]
        filtered = await client.get(
            f"/api/v1/comparisons/{comparison_id}?classification=new_failure&limit=1"
        )
        by_run = await client.get(f"/api/v1/test-runs/{run_ids[1]}/comparison?limit=2")
        explicit = await client.post(
            f"/api/v1/test-runs/{run_ids[1]}/compare", json={"baseline_run_id": run_ids[0]}
        )
        invalid = await client.post(
            f"/api/v1/test-runs/{run_ids[1]}/compare", json={"baseline_run_id": run_ids[1]}
        )
        missing = await client.get(f"/api/v1/test-runs/{run_ids[0]}/comparison")

    assert no_baseline.json()["status"] == "no_baseline"
    assert created.status_code == 200
    assert created.json()["comparison"]["new_failures"] == 1
    assert repeated.json()["created"] is False
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["classification"] == "new_failure"
    assert len(by_run.json()["items"]) == 2
    assert by_run.json()["total"] == 7
    assert explicit.json()["comparison"]["id"] == comparison_id
    assert invalid.status_code == 400
    assert missing.status_code == 404


def test_cli_compare_json_and_no_baseline_exit_code(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERA_DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("VERA_CI_PROVIDER_OVERRIDE", "local")
    get_settings.cache_clear()
    runner = CliRunner()
    run_ids = []
    try:
        for sequence, filename in enumerate(
            ["regression_baseline.xml", "regression_current.xml"], start=1
        ):
            result = runner.invoke(
                cli_app,
                [
                    "ingest",
                    str(FIXTURES / filename),
                    "--provider",
                    "local",
                    "--repository",
                    "acme/backend",
                    "--pipeline-id",
                    str(sequence),
                    "--job-id",
                    "tests",
                    "--branch",
                    "main",
                ],
            )
            assert result.exit_code == 0, result.output
            match = re.search(r"test run ([0-9a-f-]{36})", result.output)
            assert match is not None
            run_ids.append(match.group(1))
        first = runner.invoke(cli_app, ["compare", run_ids[0], "--json"])
        comparison = runner.invoke(cli_app, ["compare", run_ids[1], "--json"])
        regressions = runner.invoke(cli_app, ["regressions", run_ids[1], "--json"])
        human = runner.invoke(cli_app, ["compare", run_ids[1], "--baseline", run_ids[0]])
        human_regressions = runner.invoke(cli_app, ["regressions", run_ids[1]])
    finally:
        get_settings.cache_clear()

    assert first.exit_code == 2
    assert json.loads(first.stdout)["comparison"] is None
    assert comparison.exit_code == 0, comparison.output
    assert json.loads(comparison.stdout)["comparison"]["new_failures"] == 1
    assert regressions.exit_code == 0
    assert json.loads(regressions.stdout)["total"] == 1
    assert human.exit_code == 0
    assert "New failures: 1" in human.stdout
    assert human_regressions.exit_code == 0
