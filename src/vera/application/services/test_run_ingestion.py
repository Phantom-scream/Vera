"""Application service coordinating safe and atomic test-run ingestion."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vera.application.services.failure_intelligence import FailureFingerprintService
from vera.domain.exceptions import TestRunNotFoundError, UnsupportedReportError
from vera.domain.models import EnvironmentContext, PipelineContext, TestRun
from vera.parsers import JUnitXmlParser, TestResultParser
from vera.persistence.repositories import TestRunRepository


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Stable result indicating whether a run was newly persisted."""

    test_run: TestRun
    created: bool


class TestRunIngestionService:
    """Parse, normalize, validate, and atomically persist test executions."""

    def __init__(self, parsers: dict[str, TestResultParser] | None = None) -> None:
        self._parsers = parsers or {"junit": JUnitXmlParser()}

    async def ingest(
        self,
        *,
        content: bytes,
        report_format: str,
        pipeline: PipelineContext,
        environment: EnvironmentContext,
        session: AsyncSession,
    ) -> IngestionResult:
        """Persist a complete run or return its existing idempotent match."""

        parser = self._parsers.get(report_format.lower())
        if parser is None:
            raise UnsupportedReportError(f"Unsupported report format: {report_format}")
        report = parser.parse(content)
        run = TestRun.from_report(report, pipeline, environment)
        repository = TestRunRepository(session)

        try:
            async with session.begin():
                existing = await repository.find_by_identity(pipeline)
                if existing is not None:
                    return IngestionResult(test_run=existing, created=False)
                stored = await repository.add(run)
                await FailureFingerprintService().materialize_run(stored.id, session)
            return IngestionResult(test_run=stored, created=True)
        except IntegrityError:
            await session.rollback()
            existing = await repository.find_by_identity(pipeline)
            if existing is None:
                raise
            return IngestionResult(test_run=existing, created=False)

    async def get(self, run_id: UUID, session: AsyncSession) -> TestRun:
        """Retrieve one complete test run or raise a domain error."""

        run = await TestRunRepository(session).get(run_id)
        if run is None:
            raise TestRunNotFoundError(f"Test run {run_id} was not found")
        return run

    async def list(
        self, *, offset: int, limit: int, session: AsyncSession
    ) -> tuple[list[TestRun], int]:
        """Retrieve a page of complete test runs."""

        return await TestRunRepository(session).list(offset=offset, limit=limit)
