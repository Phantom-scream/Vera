import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from vera.application.services import TestRunIngestionService as IngestionService
from vera.domain.models import EnvironmentContext, PipelineContext
from vera.domain.models import TestRun as Run
from vera.persistence import Database
from vera.persistence.repositories import TestRunRepository as RunRepository

pytestmark = pytest.mark.integration


def test_phase3_downgrade_upgrade_backfills_existing_cases(migrated_database_url: str) -> None:
    async def seed() -> Run:
        database = Database(migrated_database_url)
        try:
            async with database.session_factory() as session:
                result = await IngestionService().ingest(
                    content=(
                        Path(__file__).parents[1] / "fixtures/junit/regression_baseline.xml"
                    ).read_bytes(),
                    report_format="junit",
                    pipeline=PipelineContext(
                        provider="local", repository="acme/backend", pipeline_id="1", job_id="tests"
                    ),
                    environment=EnvironmentContext(),
                    session=session,
                )
                return result.test_run
        finally:
            await database.dispose()

    original = asyncio.run(seed())
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", migrated_database_url)
    command.downgrade(config, "20260914_02")
    command.upgrade(config, "head")
    command.check(config)

    async def verify() -> None:
        database = Database(migrated_database_url)
        try:
            async with database.session_factory() as session:
                restored = await RunRepository(session).get(original.id)
                assert restored is not None
                assert [
                    case.stable_test_key for suite in restored.suites for case in suite.test_cases
                ] == [
                    case.stable_test_key for suite in original.suites for case in suite.test_cases
                ]
        finally:
            await database.dispose()

    asyncio.run(verify())
