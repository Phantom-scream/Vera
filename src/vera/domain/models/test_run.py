import math
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import Field, field_validator, model_validator

from vera.domain.enums import ExecutionStatus
from vera.domain.models.base import DomainModel
from vera.domain.models.ci import ChangeRequestContext, CIContext, GitContext


class TestFailure(DomainModel):
    """Failure details associated with one failed or errored test case."""

    id: UUID = Field(default_factory=uuid4)
    type: str | None = None
    message: str | None = None
    stack_trace: str | None = None


class TestCaseExecution(DomainModel):
    """A normalized execution of one test case."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    classname: str | None = None
    file: str | None = None
    duration_seconds: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    status: ExecutionStatus
    attempt: int = Field(default=1, ge=1)
    failure: TestFailure | None = None

    @model_validator(mode="after")
    def validate_failure_consistency(self) -> Self:
        has_failure_status = self.status in {ExecutionStatus.FAILED, ExecutionStatus.ERROR}
        if has_failure_status != (self.failure is not None):
            raise ValueError("failed and errored test cases must contain failure details")
        return self


class TestSuite(DomainModel):
    """A normalized suite and its calculated aggregates."""

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    package: str | None = None
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    total_tests: int = Field(ge=0)
    passed_tests: int = Field(ge=0)
    failed_tests: int = Field(ge=0)
    skipped_tests: int = Field(ge=0)
    test_cases: tuple[TestCaseExecution, ...]

    @classmethod
    def from_cases(
        cls,
        *,
        name: str,
        package: str | None,
        test_cases: tuple[TestCaseExecution, ...],
    ) -> Self:
        """Create a suite using aggregates calculated from its test cases."""

        return cls(
            name=name,
            package=package,
            duration_seconds=_sum_durations(case.duration_seconds for case in test_cases),
            total_tests=len(test_cases),
            passed_tests=sum(case.status is ExecutionStatus.PASSED for case in test_cases),
            failed_tests=sum(
                case.status in {ExecutionStatus.FAILED, ExecutionStatus.ERROR}
                for case in test_cases
            ),
            skipped_tests=sum(case.status is ExecutionStatus.SKIPPED for case in test_cases),
            test_cases=test_cases,
        )


class PipelineContext(DomainModel):
    """Provider-neutral metadata identifying the originating CI execution."""

    external_run_id: str | None = None
    provider: str = Field(min_length=1, max_length=50)
    repository: str = Field(min_length=1, max_length=500)
    branch: str | None = Field(default=None, max_length=500)
    commit_sha: str | None = Field(default=None, max_length=128)
    pipeline_id: str = Field(min_length=1, max_length=255)
    job_id: str = Field(min_length=1, max_length=255)
    repository_url: str | None = Field(default=None, max_length=2000)
    pipeline_name: str | None = Field(default=None, max_length=500)
    pipeline_url: str | None = Field(default=None, max_length=2000)
    job_name: str | None = Field(default=None, max_length=500)
    job_url: str | None = Field(default=None, max_length=2000)
    run_number: int | None = Field(default=None, ge=1)
    run_attempt: int = Field(default=1, ge=1)
    trigger_source: str | None = Field(default=None, max_length=255)
    actor: str | None = Field(default=None, max_length=500)
    detected_from_ci: bool = False
    ref: str | None = Field(default=None, max_length=1000)
    default_branch: str | None = Field(default=None, max_length=500)
    commit_message: str | None = Field(default=None, max_length=10000)
    commit_author: str | None = Field(default=None, max_length=500)
    change_request: ChangeRequestContext | None = None

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("repository", "pipeline_id", "job_id", mode="before")
    @classmethod
    def normalize_required_identity(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("external_run_id", "branch", "commit_sha", mode="before")
    @classmethod
    def normalize_optional_identity(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None

    def resolved_external_run_id(self) -> str:
        """Return an explicit run ID or a stable pipeline/job fallback."""

        return self.external_run_id or f"{self.pipeline_id}:{self.job_id}"

    def ci_context(self) -> CIContext:
        """Return normalized pipeline and job metadata."""

        return CIContext(
            provider=self.provider,
            repository=self.repository,
            repository_url=self.repository_url,
            pipeline_id=self.pipeline_id,
            pipeline_name=self.pipeline_name,
            pipeline_url=self.pipeline_url,
            job_id=self.job_id,
            job_name=self.job_name,
            job_url=self.job_url,
            run_number=self.run_number,
            run_attempt=self.run_attempt,
            trigger_source=self.trigger_source,
            actor=self.actor,
            detected_from_ci=self.detected_from_ci,
        )

    def git_context(self) -> GitContext:
        """Return normalized source revision metadata."""

        return GitContext(
            commit_sha=self.commit_sha,
            branch=self.branch,
            ref=self.ref,
            default_branch=self.default_branch,
            commit_message=self.commit_message,
            commit_author=self.commit_author,
        )


class EnvironmentContext(DomainModel):
    """Execution environment dimensions used for later historical comparison."""

    environment: str | None = Field(default=None, max_length=100)
    application_version: str | None = Field(default=None, max_length=255)
    build_number: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=255)
    browser: str | None = Field(default=None, max_length=255)
    device: str | None = Field(default=None, max_length=255)
    test_configuration: dict[str, Any] = Field(default_factory=dict)


class ParsedTestReport(DomainModel):
    """Parser output before CI and environment metadata are attached."""

    suites: tuple[TestSuite, ...]
    started_at: datetime | None = None


class TestRun(DomainModel):
    """A complete normalized test execution independent of persistence."""

    id: UUID = Field(default_factory=uuid4)
    external_run_id: str
    provider: str
    repository: str
    branch: str | None = None
    commit_sha: str | None = None
    pipeline_id: str
    job_id: str
    ci_context: CIContext
    git_context: GitContext
    change_request: ChangeRequestContext | None = None
    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(ge=0, allow_inf_nan=False)
    status: ExecutionStatus
    total_tests: int = Field(ge=0)
    passed_tests: int = Field(ge=0)
    failed_tests: int = Field(ge=0)
    skipped_tests: int = Field(ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    suites: tuple[TestSuite, ...]
    environment: EnvironmentContext = Field(default_factory=EnvironmentContext)

    @classmethod
    def from_report(
        cls,
        report: ParsedTestReport,
        pipeline: PipelineContext,
        environment: EnvironmentContext,
    ) -> Self:
        """Attach metadata and calculate all run-level aggregates."""

        total = sum(suite.total_tests for suite in report.suites)
        passed = sum(suite.passed_tests for suite in report.suites)
        failed = sum(suite.failed_tests for suite in report.suites)
        skipped = sum(suite.skipped_tests for suite in report.suites)
        duration = _sum_durations(suite.duration_seconds for suite in report.suites)
        statuses = {case.status for suite in report.suites for case in suite.test_cases}
        if ExecutionStatus.ERROR in statuses:
            status = ExecutionStatus.ERROR
        elif ExecutionStatus.FAILED in statuses:
            status = ExecutionStatus.FAILED
        elif statuses and statuses == {ExecutionStatus.SKIPPED}:
            status = ExecutionStatus.SKIPPED
        else:
            status = ExecutionStatus.PASSED
        started_at = report.started_at or datetime.now(UTC)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)

        return cls(
            external_run_id=pipeline.resolved_external_run_id(),
            provider=pipeline.provider,
            repository=pipeline.repository,
            branch=pipeline.branch,
            commit_sha=pipeline.commit_sha,
            pipeline_id=pipeline.pipeline_id,
            job_id=pipeline.job_id,
            ci_context=pipeline.ci_context(),
            git_context=pipeline.git_context(),
            change_request=pipeline.change_request,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=duration),
            duration_seconds=duration,
            status=status,
            total_tests=total,
            passed_tests=passed,
            failed_tests=failed,
            skipped_tests=skipped,
            suites=report.suites,
            environment=environment,
        )


def _sum_durations(values: Iterable[float]) -> float:
    return round(math.fsum(values), 9)
