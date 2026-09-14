from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vera.application.services import TestRunIngestionService as IngestionService
from vera.domain.models import EnvironmentContext, PipelineContext
from vera.persistence import models as persistence_models

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


def pipeline(*, run_attempt: int = 1, job_id: str = "8891") -> PipelineContext:
    return PipelineContext(
        provider="gitlab",
        repository="startup/backend",
        branch="main",
        commit_sha="abc123",
        pipeline_id="1201",
        job_id=job_id,
        repository_url="https://gitlab.example/startup/backend",
        pipeline_name="startup/backend",
        pipeline_url="https://gitlab.example/startup/backend/-/pipelines/1201",
        job_name="regression",
        job_url=f"https://gitlab.example/startup/backend/-/jobs/{job_id}",
        run_number=44,
        run_attempt=run_attempt,
        trigger_source="push",
        actor="ci-user",
        detected_from_ci=True,
        ref="main",
        default_branch="main",
    )


async def test_persists_complete_run_and_is_idempotent(database_session: AsyncSession) -> None:
    service = IngestionService()
    content = (FIXTURES / "mixed.xml").read_bytes()

    first = await service.ingest(
        content=content,
        report_format="junit",
        pipeline=pipeline(),
        environment=EnvironmentContext(environment="staging"),
        session=database_session,
    )
    second = await service.ingest(
        content=content,
        report_format="junit",
        pipeline=pipeline(),
        environment=EnvironmentContext(environment="staging"),
        session=database_session,
    )

    assert first.created is True
    assert second.created is False
    assert second.test_run.id == first.test_run.id
    assert second.test_run.suites[0].test_cases[1].failure is not None
    assert second.test_run.ci_context.pipeline_name == "startup/backend"
    assert second.test_run.ci_context.detected_from_ci is True
    assert second.test_run.git_context.default_branch == "main"
    assert (
        await database_session.scalar(
            select(func.count()).select_from(persistence_models.TestRunRecord)
        )
        == 1
    )


async def test_retry_identity_distinguishes_attempts_and_gitlab_job_retries(
    database_session: AsyncSession,
) -> None:
    service = IngestionService()
    content = (FIXTURES / "simple.xml").read_bytes()

    original = await service.ingest(
        content=content,
        report_format="junit",
        pipeline=pipeline(),
        environment=EnvironmentContext(),
        session=database_session,
    )
    github_rerun = await service.ingest(
        content=content,
        report_format="junit",
        pipeline=pipeline(run_attempt=2),
        environment=EnvironmentContext(),
        session=database_session,
    )
    gitlab_retry = await service.ingest(
        content=content,
        report_format="junit",
        pipeline=pipeline(job_id="8892"),
        environment=EnvironmentContext(),
        session=database_session,
    )

    assert original.created is True
    assert github_rerun.created is True
    assert gitlab_retry.created is True
    assert len({original.test_run.id, github_rerun.test_run.id, gitlab_retry.test_run.id}) == 3
    assert (
        await database_session.scalar(
            select(func.count()).select_from(persistence_models.TestCaseExecutionRecord)
        )
        == 3
    )


async def test_failed_nested_insert_rolls_back_complete_run(
    database_session: AsyncSession,
) -> None:
    service = IngestionService()

    def fail_case_insert(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if statement.startswith("INSERT INTO test_case_executions"):
            raise RuntimeError("simulated nested insert failure")

    event.listen(database_session.bind.sync_engine, "before_cursor_execute", fail_case_insert)
    try:
        with pytest.raises(RuntimeError, match="simulated nested insert failure"):
            await service.ingest(
                content=(FIXTURES / "simple.xml").read_bytes(),
                report_format="junit",
                pipeline=pipeline(),
                environment=EnvironmentContext(),
                session=database_session,
            )
    finally:
        event.remove(database_session.bind.sync_engine, "before_cursor_execute", fail_case_insert)

    assert (
        await database_session.scalar(
            select(func.count()).select_from(persistence_models.TestRunRecord)
        )
        == 0
    )
