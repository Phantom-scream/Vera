"""SQLAlchemy persistence operations for normalized test runs."""

from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vera.domain.enums import ExecutionStatus
from vera.domain.models import (
    EnvironmentContext,
    PipelineContext,
    TestCaseExecution,
    TestFailure,
    TestRun,
    TestSuite,
)
from vera.persistence.models import (
    EnvironmentContextRecord,
    TestCaseExecutionRecord,
    TestFailureRecord,
    TestRunRecord,
    TestSuiteRecord,
)


class TestRunRepository:
    """Store and reconstruct complete test-run aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_identity(self, pipeline: PipelineContext) -> TestRun | None:
        """Find an existing run using Vera's CI idempotency identity."""

        statement = self._complete_query().where(
            TestRunRecord.provider == pipeline.provider,
            TestRunRecord.repository == pipeline.repository,
            TestRunRecord.pipeline_id == pipeline.pipeline_id,
            TestRunRecord.job_id == pipeline.job_id,
            TestRunRecord.external_run_id == pipeline.resolved_external_run_id(),
        )
        record = (await self._session.scalars(statement)).one_or_none()
        return _to_domain(record) if record is not None else None

    async def get(self, run_id: UUID) -> TestRun | None:
        """Return one complete run by ID."""

        record = (
            await self._session.scalars(self._complete_query().where(TestRunRecord.id == run_id))
        ).one_or_none()
        return _to_domain(record) if record is not None else None

    async def list(self, *, offset: int, limit: int) -> tuple[list[TestRun], int]:
        """Return a newest-first page and the total number of runs."""

        total = await self._session.scalar(select(func.count()).select_from(TestRunRecord))
        statement = (
            self._complete_query()
            .order_by(TestRunRecord.created_at.desc(), TestRunRecord.id)
            .offset(offset)
            .limit(limit)
        )
        records = (await self._session.scalars(statement)).unique().all()
        return [_to_domain(record) for record in records], total or 0

    async def add(self, run: TestRun) -> TestRun:
        """Add a complete aggregate to the current transaction."""

        record = _to_record(run)
        self._session.add(record)
        await self._session.flush()
        return _to_domain(record)

    @staticmethod
    def _complete_query() -> Select[tuple[TestRunRecord]]:
        return select(TestRunRecord).options(
            selectinload(TestRunRecord.environment),
            selectinload(TestRunRecord.suites)
            .selectinload(TestSuiteRecord.test_cases)
            .selectinload(TestCaseExecutionRecord.failure),
        )


def _to_record(run: TestRun) -> TestRunRecord:
    record = TestRunRecord(
        id=run.id,
        external_run_id=run.external_run_id,
        provider=run.provider,
        repository=run.repository,
        branch=run.branch,
        commit_sha=run.commit_sha,
        pipeline_id=run.pipeline_id,
        job_id=run.job_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_seconds=run.duration_seconds,
        status=run.status.value,
        total_tests=run.total_tests,
        passed_tests=run.passed_tests,
        failed_tests=run.failed_tests,
        skipped_tests=run.skipped_tests,
        created_at=run.created_at,
    )
    record.environment = EnvironmentContextRecord(
        environment=run.environment.environment,
        application_version=run.environment.application_version,
        build_number=run.environment.build_number,
        platform=run.environment.platform,
        browser=run.environment.browser,
        device=run.environment.device,
        test_configuration=run.environment.test_configuration,
    )
    record.suites = [
        TestSuiteRecord(
            id=suite.id,
            position=suite_position,
            name=suite.name,
            package=suite.package,
            duration_seconds=suite.duration_seconds,
            total_tests=suite.total_tests,
            passed_tests=suite.passed_tests,
            failed_tests=suite.failed_tests,
            skipped_tests=suite.skipped_tests,
            test_cases=[
                TestCaseExecutionRecord(
                    id=case.id,
                    position=case_position,
                    name=case.name,
                    classname=case.classname,
                    file=case.file,
                    duration_seconds=case.duration_seconds,
                    status=case.status.value,
                    attempt=case.attempt,
                    failure=(
                        TestFailureRecord(
                            id=case.failure.id,
                            type=case.failure.type,
                            message=case.failure.message,
                            stack_trace=case.failure.stack_trace,
                        )
                        if case.failure is not None
                        else None
                    ),
                )
                for case_position, case in enumerate(suite.test_cases)
            ],
        )
        for suite_position, suite in enumerate(run.suites)
    ]
    return record


def _to_domain(record: TestRunRecord) -> TestRun:
    return TestRun(
        id=record.id,
        external_run_id=record.external_run_id,
        provider=record.provider,
        repository=record.repository,
        branch=record.branch,
        commit_sha=record.commit_sha,
        pipeline_id=record.pipeline_id,
        job_id=record.job_id,
        started_at=record.started_at,
        finished_at=record.finished_at,
        duration_seconds=record.duration_seconds,
        status=ExecutionStatus(record.status),
        total_tests=record.total_tests,
        passed_tests=record.passed_tests,
        failed_tests=record.failed_tests,
        skipped_tests=record.skipped_tests,
        created_at=record.created_at,
        suites=tuple(
            TestSuite(
                id=suite.id,
                name=suite.name,
                package=suite.package,
                duration_seconds=suite.duration_seconds,
                total_tests=suite.total_tests,
                passed_tests=suite.passed_tests,
                failed_tests=suite.failed_tests,
                skipped_tests=suite.skipped_tests,
                test_cases=tuple(
                    TestCaseExecution(
                        id=case.id,
                        name=case.name,
                        classname=case.classname,
                        file=case.file,
                        duration_seconds=case.duration_seconds,
                        status=ExecutionStatus(case.status),
                        attempt=case.attempt,
                        failure=(
                            TestFailure(
                                id=case.failure.id,
                                type=case.failure.type,
                                message=case.failure.message,
                                stack_trace=case.failure.stack_trace,
                            )
                            if case.failure is not None
                            else None
                        ),
                    )
                    for case in suite.test_cases
                ),
            )
            for suite in record.suites
        ),
        environment=EnvironmentContext(
            environment=record.environment.environment,
            application_version=record.environment.application_version,
            build_number=record.environment.build_number,
            platform=record.environment.platform,
            browser=record.environment.browser,
            device=record.environment.device,
            test_configuration=record.environment.test_configuration,
        ),
    )
