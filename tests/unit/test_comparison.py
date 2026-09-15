from datetime import UTC, datetime, timedelta
from time import perf_counter

import pytest

from vera.domain.comparison import compare_test_runs
from vera.domain.enums import BaselineStrategy, ExecutionStatus, FindingClassification
from vera.domain.exceptions import AmbiguousTestIdentityError
from vera.domain.models import (
    EnvironmentContext,
    ParsedTestReport,
    PipelineContext,
)
from vera.domain.models import (
    TestCaseExecution as CaseExecution,
)
from vera.domain.models import (
    TestFailure as Failure,
)
from vera.domain.models import (
    TestRun as Run,
)
from vera.domain.models import (
    TestSuite as Suite,
)
from vera.domain.test_identity import stable_test_key


def case(name: str, status: ExecutionStatus) -> CaseExecution:
    return CaseExecution(
        name=name,
        classname="tests.Example",
        file="tests/test_example.py",
        status=status,
        failure=(
            Failure(message="failure")
            if status in {ExecutionStatus.FAILED, ExecutionStatus.ERROR}
            else None
        ),
    )


def run(*cases: CaseExecution, sequence: int = 1, suite_name: str = "suite") -> Run:
    started = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=sequence)
    result = Run.from_report(
        ParsedTestReport(
            suites=(
                Suite.from_cases(
                    name=suite_name,
                    package="tests",
                    test_cases=tuple(cases),
                ),
            ),
            started_at=started,
        ),
        PipelineContext(
            provider="local",
            repository="acme/api",
            branch="main",
            pipeline_id=str(sequence),
            job_id="tests",
        ),
        EnvironmentContext(environment="test"),
    )
    return result.model_copy(update={"created_at": started})


def test_stable_identity_normalizes_whitespace_and_ignores_suite_when_qualified() -> None:
    first = stable_test_key(
        suite_name="suite one",
        suite_package="package",
        classname=" tests.Example ",
        test_name="test value[one]",
        file=" tests/test_example.py ",
    )
    moved = stable_test_key(
        suite_name="renamed suite",
        suite_package="other",
        classname="tests.Example",
        test_name=" test value[one] ",
        file="tests/test_example.py",
    )

    assert first == moved
    assert first.startswith("v1:")


def test_parameterized_test_names_remain_distinct() -> None:
    first = stable_test_key(
        suite_name="suite",
        suite_package=None,
        classname="tests.Example",
        test_name="test_value[one]",
        file=None,
    )
    second = stable_test_key(
        suite_name="suite",
        suite_package=None,
        classname="tests.Example",
        test_name="test_value[two]",
        file=None,
    )

    assert first != second
    assert stable_test_key(
        suite_name="suite",
        suite_package=None,
        classname="tests.Example",
        test_name="test_value[a  b]",
        file=None,
    ) != stable_test_key(
        suite_name="suite",
        suite_package=None,
        classname="tests.Example",
        test_name="test_value[a b]",
        file=None,
    )


def test_comparison_classifies_all_supported_transitions() -> None:
    baseline = run(
        case("new-failure", ExecutionStatus.PASSED),
        case("existing", ExecutionStatus.ERROR),
        case("recovered", ExecutionStatus.FAILED),
        case("unchanged-pass", ExecutionStatus.PASSED),
        case("missing", ExecutionStatus.PASSED),
        case("unchanged-skip", ExecutionStatus.SKIPPED),
        case("newly-skip", ExecutionStatus.PASSED),
        case("status-change", ExecutionStatus.SKIPPED),
        sequence=1,
    )
    current = run(
        case("new-failure", ExecutionStatus.FAILED),
        case("existing", ExecutionStatus.FAILED),
        case("recovered", ExecutionStatus.PASSED),
        case("unchanged-pass", ExecutionStatus.PASSED),
        case("new", ExecutionStatus.PASSED),
        case("unchanged-skip", ExecutionStatus.SKIPPED),
        case("newly-skip", ExecutionStatus.SKIPPED),
        case("status-change", ExecutionStatus.PASSED),
        sequence=2,
    )

    comparison, findings = compare_test_runs(
        current=current,
        baseline=baseline,
        strategy=BaselineStrategy.SAME_BRANCH,
        reason="test",
    )
    classifications = {finding.classification for finding in findings}

    assert classifications == set(FindingClassification)
    assert comparison.new_failures == 1
    assert comparison.existing_failures == 1
    assert comparison.recovered_tests == 1
    assert comparison.new_tests == 1
    assert comparison.missing_tests == 1
    assert comparison.status_changes == 2
    assert comparison.unchanged_tests == 2


def test_duplicate_stable_identity_is_rejected() -> None:
    duplicate = case("duplicate", ExecutionStatus.PASSED)
    current = run(duplicate, duplicate.model_copy())

    with pytest.raises(AmbiguousTestIdentityError, match="duplicate stable test identities"):
        compare_test_runs(
            current=current,
            baseline=run(sequence=1),
            strategy=BaselineStrategy.SAME_BRANCH,
            reason="test",
        )


def test_large_comparison_remains_linear_in_practice() -> None:
    baseline = run(
        *(case(f"test-{index}", ExecutionStatus.PASSED) for index in range(5000)),
        sequence=1,
    )
    current = run(
        *(case(f"test-{index}", ExecutionStatus.PASSED) for index in range(5000)),
        sequence=2,
    )

    started = perf_counter()
    comparison, findings = compare_test_runs(
        current=current,
        baseline=baseline,
        strategy=BaselineStrategy.SAME_BRANCH,
        reason="performance test",
    )

    assert len(findings) == 5000
    assert comparison.unchanged_tests == 5000
    assert perf_counter() - started < 5


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (ExecutionStatus.SKIPPED, ExecutionStatus.ERROR, FindingClassification.NEW_FAILURE),
        (ExecutionStatus.ERROR, ExecutionStatus.FAILED, FindingClassification.EXISTING_FAILURE),
        (ExecutionStatus.FAILED, ExecutionStatus.SKIPPED, FindingClassification.STATUS_CHANGED),
    ],
)
def test_error_and_skipped_transitions(
    before: ExecutionStatus, after: ExecutionStatus, expected: FindingClassification
) -> None:
    _, findings = compare_test_runs(
        current=run(case("test", after), sequence=2),
        baseline=run(case("test", before), sequence=1),
        strategy=BaselineStrategy.SAME_BRANCH,
        reason="test",
    )
    assert findings[0].classification is expected
    assert findings[0].baseline_status is before
    assert findings[0].current_status is after


def test_empty_runs_and_suite_moves() -> None:
    qualified = case("test", ExecutionStatus.PASSED)
    _, moved = compare_test_runs(
        current=run(qualified, sequence=2, suite_name="new-suite"),
        baseline=run(qualified, sequence=1, suite_name="old-suite"),
        strategy=BaselineStrategy.SAME_BRANCH,
        reason="test",
    )
    assert moved[0].classification is FindingClassification.UNCHANGED_PASS
    for current, baseline, expected in [
        (run(), run(qualified), FindingClassification.MISSING_TEST),
        (run(qualified), run(), FindingClassification.NEW_TEST),
    ]:
        _, findings = compare_test_runs(
            current=current, baseline=baseline, strategy=BaselineStrategy.EXPLICIT, reason="test"
        )
        assert findings[0].classification is expected
