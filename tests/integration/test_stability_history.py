import asyncio
import json
from time import perf_counter
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select
from sqlalchemy.engine import Connection, ExecutionContext
from sqlalchemy.ext.asyncio import AsyncSession
from typer.testing import CliRunner

from vera.api import create_app
from vera.application.services import RegressionComparisonService
from vera.application.services import TestRunIngestionService as IngestionService
from vera.application.services.flaky_analysis import FlakyTestAnalysisService
from vera.application.services.test_history import TestHistoryService as HistoryService
from vera.cli.app import app as cli_app
from vera.config import Settings, get_settings
from vera.domain.enums import FindingClassification
from vera.domain.models import EnvironmentContext, PipelineContext
from vera.domain.models import TestRun as Run
from vera.domain.models.stability import StabilityClass
from vera.persistence import Database
from vera.persistence.models.stability import TestStabilitySnapshotRecord as SnapshotRecord
from vera.persistence.repositories.history import (
    history_statement,
)

pytestmark = pytest.mark.integration


def report(index: int, count: int = 5) -> bytes:
    if count != 5:
        return (
            '<testsuite name="large">'
            + "".join(
                f'<testcase name="test-{number}" classname="tests.Large"/>'
                for number in range(count)
            )
            + "</testsuite>"
        ).encode()
    failure = '<failure message="observed failure">trace</failure>'
    return (
        f'<testsuite name="history">'
        f'<testcase name="stable" classname="tests.History"/>'
        f'<testcase name="failing" classname="tests.History">{failure}</testcase>'
        f'<testcase name="alternating" classname="tests.History">'
        f"{failure if index % 2 else ''}</testcase>"
        f'<testcase name="isolated" classname="tests.History">'
        f"{failure if index == 0 else ''}</testcase>"
        f'<testcase name="retried" classname="tests.History" attempt="1">{failure}</testcase>'
        f'<testcase name="retried" classname="tests.History" attempt="2"/>'
        f"</testsuite>"
    ).encode()


async def seed(
    session: AsyncSession, count: int = 20, browser: str = "chrome", cases: int = 5
) -> list[Run]:
    runs = []
    for index in range(count):
        result = await IngestionService().ingest(
            content=report(index, cases),
            report_format="junit",
            pipeline=PipelineContext(
                provider="local",
                repository="acme/stability",
                branch="main",
                pipeline_id=f"{browser}-{index}",
                job_id="tests",
            ),
            environment=EnvironmentContext(environment="staging", browser=browser),
            session=session,
        )
        runs.append(result.test_run)
    return runs


async def test_historical_statistics_snapshots_and_regression_enrichment(
    database_session: AsyncSession,
) -> None:
    runs = await seed(database_session)
    service = FlakyTestAnalysisService()
    results = await service.analyze(reference=runs[-1], session=database_session)
    repeated = await service.analyze(reference=runs[-1], session=database_session)
    assert results == repeated
    classes = {
        case.name: next(
            item for item in results if item.test_key == case.stable_test_key
        ).classification
        for suite in runs[-1].suites
        for case in suite.test_cases
    }
    assert classes == {
        "stable": StabilityClass.STABLE,
        "failing": StabilityClass.CONSISTENTLY_FAILING,
        "alternating": StabilityClass.FLAKY,
        "isolated": StabilityClass.LIKELY_STABLE,
        "retried": StabilityClass.FLAKY,
    }
    assert await database_session.scalar(select(func.count()).select_from(SnapshotRecord)) == 5
    await database_session.rollback()
    comparison_service = RegressionComparisonService()
    comparison = await comparison_service.compare(
        current_run_id=runs[-1].id, baseline_run_id=None, session=database_session
    )
    page = await comparison_service.for_run(
        run_id=runs[-1].id,
        offset=0,
        limit=100,
        classification=FindingClassification.NEW_FAILURE,
        session=database_session,
    )
    enriched = await comparison_service.enrich(page, database_session)
    assert enriched.findings[0].classification is FindingClassification.NEW_FAILURE
    assert enriched.findings[0].stability is StabilityClass.FLAKY
    assert comparison.comparison.new_failures == 1


async def test_history_windows_isolation_and_retry_idempotency(
    database_session: AsyncSession,
) -> None:
    chrome = await seed(database_session)
    firefox = await seed(database_session, count=1, browser="firefox")
    key = chrome[-1].suites[0].test_cases[0].stable_test_key
    chrome_history = await HistoryService().histories(chrome[-1], [key], 10, database_session)
    firefox_history = await HistoryService().histories(firefox[-1], [key], 50, database_session)
    assert len(chrome_history[key]) == 10 and len(firefox_history[key]) == 1
    assert chrome_history[key][0].run_id == chrome[10].id
    await database_session.rollback()
    duplicate = await IngestionService().ingest(
        content=report(19),
        report_format="junit",
        pipeline=PipelineContext(
            provider="local",
            repository="acme/stability",
            branch="main",
            pipeline_id="chrome-19",
            job_id="tests",
        ),
        environment=EnvironmentContext(environment="staging", browser="chrome"),
        session=database_session,
    )
    assert not duplicate.created and duplicate.test_run.id == chrome[-1].id
    retried = duplicate.test_run.suites[0].test_cases[-1]
    assert retried.attempt == 2 and retried.attempts[0].failure.stack_trace == "trace"


@pytest.mark.parametrize("provider", ["github", "gitlab"])
async def test_ci_reruns_remain_distinct_from_test_retries(
    database_session: AsyncSession, provider: str
) -> None:
    runs = []
    for index in range(2):
        result = await IngestionService().ingest(
            content=b'<testsuite><testcase name="x"><failure/></testcase></testsuite>'
            if index == 0
            else b'<testsuite><testcase name="x"/></testsuite>',
            report_format="junit",
            pipeline=PipelineContext(
                provider=provider,
                repository="acme/reruns",
                pipeline_id="same",
                job_id=str(index) if provider == "gitlab" else "tests",
                job_name="tests",
                run_attempt=index + 1 if provider == "github" else 1,
            ),
            environment=EnvironmentContext(),
            session=database_session,
        )
        runs.append(result.test_run)
    assert runs[0].id != runs[1].id
    results = await FlakyTestAnalysisService().analyze(reference=runs[-1], session=database_session)
    stats = results[0].statistics
    assert stats.total_executions == 2 and stats.retry_count == 0
    assert stats.ci_rerun_count == stats.ci_rerun_recoveries == 1
    assert results[0].classification is StabilityClass.INSUFFICIENT_HISTORY


async def test_api_history_pagination_filtering_and_enriched_findings(
    migrated_database_url: str,
) -> None:
    database = Database(migrated_database_url)
    try:
        async with database.session_factory() as session:
            runs = await seed(session)
            await RegressionComparisonService().compare(
                current_run_id=runs[-1].id, baseline_run_id=None, session=session
            )
    finally:
        await database.dispose()
    app = create_app(Settings(database_url=migrated_database_url, _env_file=None))
    key = runs[-1].suites[0].test_cases[0].stable_test_key
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        history = await client.get(
            f"/api/v1/tests/{key}/history",
            params={"reference_run_id": str(runs[-1].id), "limit": 3, "offset": 2},
        )
        assert history.status_code == 200, history.text
        assert history.json()["total"] == 20 and len(history.json()["items"]) == 3
        assert history.json()["items"][0]["run_id"] == str(runs[17].id)
        stability = await client.get(
            f"/api/v1/tests/{key}/stability", params={"repository": "acme/stability"}
        )
        assert stability.json()["classification"] == "stable"
        assert stability.json()["scoring_version"] == "flaky-v1"
        run = await client.get(
            f"/api/v1/test-runs/{runs[-1].id}/flaky-tests?classification=flaky&limit=1"
        )
        assert run.json()["total"] == 2 and len(run.json()["items"]) == 1
        findings = await client.get(
            f"/api/v1/test-runs/{runs[-1].id}/comparison?classification=new_failure&include_stability=true"
        )
        assert findings.json()["items"][0]["classification"] == "new_failure"
        assert findings.json()["items"][0]["stability"] == "flaky"
        assert (await client.get(f"/api/v1/tests/{key}/history?window=101")).status_code == 422


def test_cli_json_stability_history_and_regressions(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def create_history() -> Run:
        database = Database(migrated_database_url)
        try:
            async with database.session_factory() as session:
                runs = await seed(session)
                return runs[-1]
        finally:
            await database.dispose()

    current = asyncio.run(create_history())
    monkeypatch.setenv("VERA_DATABASE_URL", migrated_database_url)
    get_settings.cache_clear()
    runner = CliRunner()
    key = current.suites[0].test_cases[0].stable_test_key
    try:
        result = runner.invoke(cli_app, ["flaky", "--run", str(current.id), "--json"])
        assert result.exit_code == 0, result.output
        assert len(json.loads(result.stdout)) == 5
        single = runner.invoke(cli_app, ["flaky", key, "--repository", "acme/stability", "--json"])
        assert single.exit_code == 0, single.output
        assert json.loads(single.stdout)[0]["classification"] == "stable"
        history = runner.invoke(cli_app, ["history", key, "--run", str(current.id), "--json"])
        assert len(json.loads(history.stdout)["observations"]) == 20
    finally:
        get_settings.cache_clear()


async def test_thousands_of_tests_use_bounded_bulk_queries(database_session: AsyncSession) -> None:
    runs = await seed(database_session, count=3, cases=2000)
    statements: list[str] = []
    engine = database_session.bind.sync_engine

    def count_statement(
        connection: Connection,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    started = perf_counter()
    try:
        results = await FlakyTestAnalysisService().analyze(
            reference=runs[-1], session=database_session, window=20
        )
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)
    assert len(results) == 2000 and all(item.statistics.total_executions == 3 for item in results)
    assert len(statements) <= 10
    assert perf_counter() - started < 20
    query = history_statement(runs[-1], [results[0].test_key], 20)
    compiled = query.compile(dialect=engine.dialect)
    parameters = tuple(
        json.dumps(compiled.params[name])
        if isinstance(compiled.params[name], dict)
        else compiled.params[name]
        for name in compiled.positiontup
    )
    connection = await database_session.connection()
    plan = await connection.exec_driver_sql("EXPLAIN " + str(compiled), parameters)
    assert "Limit" in "\n".join(row[0] for row in plan)
