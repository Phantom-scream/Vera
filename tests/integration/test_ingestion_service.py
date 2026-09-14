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


def pipeline() -> PipelineContext:
    return PipelineContext(
        provider="gitlab",
        repository="startup/backend",
        branch="main",
        commit_sha="abc123",
        pipeline_id="1201",
        job_id="8891",
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
    assert (
        await database_session.scalar(
            select(func.count()).select_from(persistence_models.TestRunRecord)
        )
        == 1
    )
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
