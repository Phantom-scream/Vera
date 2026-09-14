from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from vera.api import create_app
from vera.config import Environment, Settings

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


async def test_api_ingests_retrieves_lists_and_deduplicates(
    migrated_database_url: str,
) -> None:
    app = create_app(
        Settings(
            environment=Environment.TEST,
            database_url=migrated_database_url,
            _env_file=None,
        )
    )
    data = {
        "provider": "github",
        "repository": "acme/api",
        "pipeline_id": "901",
        "job_id": "22",
        "branch": "main",
        "commit_sha": "deadbeef",
        "environment": "ci",
        "test_configuration": '{"workers": 4}',
    }
    files = {"report": ("mixed.xml", (FIXTURES / "mixed.xml").read_bytes(), "application/xml")}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        created = await client.post("/api/v1/test-runs/ingest", data=data, files=files)
        duplicate = await client.post("/api/v1/test-runs/ingest", data=data, files=files)
        run_id = created.json()["test_run"]["id"]
        retrieved = await client.get(f"/api/v1/test-runs/{run_id}")
        page = await client.get("/api/v1/test-runs?offset=0&limit=10")

    assert created.status_code == 201
    assert created.json()["created"] is True
    assert created.json()["test_run"]["total_tests"] == 3
    assert duplicate.status_code == 200
    assert duplicate.json()["created"] is False
    assert duplicate.json()["test_run"]["id"] == run_id
    assert retrieved.status_code == 200
    assert retrieved.json()["suites"][0]["test_cases"][1]["failure"]["message"] == "expected true"
    assert page.status_code == 200
    assert page.json()["total"] == 1
    assert len(page.json()["items"]) == 1


async def test_api_rejects_malformed_report(migrated_database_url: str) -> None:
    app = create_app(
        Settings(environment=Environment.TEST, database_url=migrated_database_url, _env_file=None)
    )
    data = {
        "provider": "github",
        "repository": "acme/api",
        "pipeline_id": "902",
        "job_id": "23",
    }
    files = {
        "report": (
            "malformed.xml",
            (FIXTURES / "malformed.xml").read_bytes(),
            "application/xml",
        )
    }

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        response = await client.post("/api/v1/test-runs/ingest", data=data, files=files)

    assert response.status_code == 422
    assert "Malformed or unsafe JUnit XML" in response.json()["detail"]


async def test_api_rejects_report_over_configured_size(migrated_database_url: str) -> None:
    app = create_app(
        Settings(
            environment=Environment.TEST,
            database_url=migrated_database_url,
            max_report_size_bytes=8,
            _env_file=None,
        )
    )
    data = {
        "provider": "github",
        "repository": "acme/api",
        "pipeline_id": "903",
        "job_id": "24",
    }
    files = {"report": ("report.xml", b"<testsuite />", "application/xml")}

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        response = await client.post("/api/v1/test-runs/ingest", data=data, files=files)

    assert response.status_code == 413
    assert response.json() == {"detail": "JUnit report exceeds 8 bytes"}
