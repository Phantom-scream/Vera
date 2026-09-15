"""SQLAlchemy persistence operations for normalized test runs."""

from uuid import UUID

from sqlalchemy import Select, and_, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vera.domain.enums import ExecutionStatus
from vera.domain.models import (
    ChangeRequestContext,
    ChangeRequestKind,
    CIContext,
    EnvironmentContext,
    GitContext,
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
            TestRunRecord.run_attempt == pipeline.run_attempt,
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

    async def find_comparable_baseline(self, current: TestRun, branch: str) -> TestRun | None:
        """Return the latest strictly older run matching comparison dimensions."""

        environment = current.environment
        conditions = [
            TestRunRecord.repository == current.repository,
            TestRunRecord.branch == branch,
            TestRunRecord.id != current.id,
            TestRunRecord.created_at < current.created_at,
            TestRunRecord.started_at <= current.started_at,
            or_(
                TestRunRecord.provider != current.provider,
                TestRunRecord.pipeline_id != current.pipeline_id,
            ),
            EnvironmentContextRecord.environment.is_(None)
            if environment.environment is None
            else EnvironmentContextRecord.environment == environment.environment,
            EnvironmentContextRecord.platform.is_(None)
            if environment.platform is None
            else EnvironmentContextRecord.platform == environment.platform,
            EnvironmentContextRecord.browser.is_(None)
            if environment.browser is None
            else EnvironmentContextRecord.browser == environment.browser,
            EnvironmentContextRecord.device.is_(None)
            if environment.device is None
            else EnvironmentContextRecord.device == environment.device,
            cast(EnvironmentContextRecord.test_configuration, JSONB)
            == environment.test_configuration,
        ]
        statement = (
            self._complete_query()
            .join(TestRunRecord.environment)
            .where(and_(*conditions))
            .order_by(TestRunRecord.created_at.desc(), TestRunRecord.id.desc())
            .limit(1)
        )
        record = (await self._session.scalars(statement)).unique().one_or_none()
        return _to_domain(record) if record is not None else None

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
        repository_url=run.ci_context.repository_url,
        pipeline_name=run.ci_context.pipeline_name,
        pipeline_url=run.ci_context.pipeline_url,
        job_name=run.ci_context.job_name,
        job_url=run.ci_context.job_url,
        run_number=run.ci_context.run_number,
        run_attempt=run.ci_context.run_attempt,
        trigger_source=run.ci_context.trigger_source,
        actor=run.ci_context.actor,
        detected_from_ci=run.ci_context.detected_from_ci,
        git_ref=run.git_context.ref,
        default_branch=run.git_context.default_branch,
        commit_message=run.git_context.commit_message,
        commit_author=run.git_context.commit_author,
        change_request_kind=run.change_request.kind.value if run.change_request else None,
        change_request_number=run.change_request.number_or_iid if run.change_request else None,
        change_request_title=run.change_request.title if run.change_request else None,
        change_request_source_branch=(
            run.change_request.source_branch if run.change_request else None
        ),
        change_request_target_branch=(
            run.change_request.target_branch if run.change_request else None
        ),
        change_request_url=run.change_request.url if run.change_request else None,
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
                    stable_test_key=case.stable_test_key,
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
        ci_context=CIContext(
            provider=record.provider,
            repository=record.repository,
            repository_url=record.repository_url,
            pipeline_id=record.pipeline_id,
            pipeline_name=record.pipeline_name,
            pipeline_url=record.pipeline_url,
            job_id=record.job_id,
            job_name=record.job_name,
            job_url=record.job_url,
            run_number=record.run_number,
            run_attempt=record.run_attempt,
            trigger_source=record.trigger_source,
            actor=record.actor,
            detected_from_ci=record.detected_from_ci,
        ),
        git_context=GitContext(
            commit_sha=record.commit_sha,
            branch=record.branch,
            ref=record.git_ref,
            default_branch=record.default_branch,
            commit_message=record.commit_message,
            commit_author=record.commit_author,
        ),
        change_request=(
            ChangeRequestContext(
                kind=ChangeRequestKind(record.change_request_kind),
                number_or_iid=record.change_request_number,
                title=record.change_request_title,
                source_branch=record.change_request_source_branch,
                target_branch=record.change_request_target_branch,
                url=record.change_request_url,
            )
            if record.change_request_kind and record.change_request_number
            else None
        ),
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
                        stable_test_key=case.stable_test_key,
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
