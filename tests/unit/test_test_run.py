from datetime import UTC, datetime

from vera.domain import models as domain_models
from vera.domain.enums import ExecutionStatus
from vera.domain.models import (
    EnvironmentContext,
    ParsedTestReport,
    PipelineContext,
)


def test_run_aggregates_are_calculated_from_cases() -> None:
    cases = (
        domain_models.TestCaseExecution(name="pass", status=ExecutionStatus.PASSED),
        domain_models.TestCaseExecution(
            name="error",
            status=ExecutionStatus.ERROR,
            duration_seconds=0.4,
            failure=domain_models.TestFailure(message="boom"),
        ),
        domain_models.TestCaseExecution(name="skip", status=ExecutionStatus.SKIPPED),
    )
    suite = domain_models.TestSuite.from_cases(name="suite", package=None, test_cases=cases)
    report = ParsedTestReport(suites=(suite,), started_at=datetime(2026, 9, 14, tzinfo=UTC))

    run = domain_models.TestRun.from_report(
        report,
        PipelineContext(
            provider="gitlab",
            repository="startup/backend",
            pipeline_id="1201",
            job_id="8891",
        ),
        EnvironmentContext(environment="staging"),
    )

    assert run.external_run_id == "1201:8891"
    assert run.status is ExecutionStatus.ERROR
    assert (run.total_tests, run.passed_tests, run.failed_tests, run.skipped_tests) == (
        3,
        1,
        1,
        1,
    )
    assert run.duration_seconds == 0.4
    assert run.finished_at > run.started_at
