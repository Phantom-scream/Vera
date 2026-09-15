"""Pure linear-time regression comparison rules."""

from collections import Counter
from itertools import chain

from vera.domain.enums import BaselineStrategy, ExecutionStatus, FindingClassification
from vera.domain.exceptions import AmbiguousTestIdentityError
from vera.domain.models.comparison import RegressionComparison, TestComparisonFinding
from vera.domain.models.test_run import TestCaseExecution, TestRun
from vera.domain.test_identity import stable_test_key

FAILURE_STATUSES = {ExecutionStatus.FAILED, ExecutionStatus.ERROR}


def compare_test_runs(
    *,
    current: TestRun,
    baseline: TestRun,
    strategy: BaselineStrategy,
    reason: str,
) -> tuple[RegressionComparison, tuple[TestComparisonFinding, ...]]:
    """Compare complete runs in O(current cases + baseline cases)."""

    current_cases = _index_cases(current)
    baseline_cases = _index_cases(baseline)
    comparison = RegressionComparison(
        current_run_id=current.id,
        baseline_run_id=baseline.id,
        baseline_strategy=strategy,
        baseline_reason=reason,
        current_total=len(current_cases),
        baseline_total=len(baseline_cases),
        new_failures=0,
        existing_failures=0,
        recovered_tests=0,
        new_tests=0,
        missing_tests=0,
        status_changes=0,
        unchanged_tests=0,
    )
    findings: list[TestComparisonFinding] = []
    for test_key in dict.fromkeys(chain(current_cases, baseline_cases)):
        current_case = current_cases.get(test_key)
        baseline_case = baseline_cases.get(test_key)
        classification = _classify(baseline_case, current_case)
        findings.append(
            TestComparisonFinding(
                comparison_id=comparison.id,
                test_key=test_key,
                current_case_id=current_case.id if current_case else None,
                baseline_case_id=baseline_case.id if baseline_case else None,
                baseline_status=baseline_case.status if baseline_case else None,
                current_status=current_case.status if current_case else None,
                classification=classification,
            )
        )

    counts = Counter(finding.classification for finding in findings)
    comparison = comparison.model_copy(
        update={
            "new_failures": counts[FindingClassification.NEW_FAILURE],
            "existing_failures": counts[FindingClassification.EXISTING_FAILURE],
            "recovered_tests": counts[FindingClassification.RECOVERED],
            "new_tests": counts[FindingClassification.NEW_TEST],
            "missing_tests": counts[FindingClassification.MISSING_TEST],
            "status_changes": counts[FindingClassification.NEWLY_SKIPPED]
            + counts[FindingClassification.STATUS_CHANGED],
            "unchanged_tests": counts[FindingClassification.UNCHANGED_PASS]
            + counts[FindingClassification.UNCHANGED_SKIPPED],
        }
    )
    return comparison, tuple(findings)


def _index_cases(run: TestRun) -> dict[str, TestCaseExecution]:
    indexed: dict[str, TestCaseExecution] = {}
    duplicates: set[str] = set()
    for suite in run.suites:
        for case in suite.test_cases:
            key = case.stable_test_key or stable_test_key(
                suite_name=suite.name,
                suite_package=suite.package,
                classname=case.classname,
                test_name=case.name,
                file=case.file,
            )
            if key in indexed:
                duplicates.add(key)
            else:
                indexed[key] = case
    if duplicates:
        keys = ", ".join(sorted(duplicates)[:3])
        raise AmbiguousTestIdentityError(
            f"Run {run.id} contains duplicate stable test identities: {keys}"
        )
    return indexed


def _classify(
    baseline: TestCaseExecution | None,
    current: TestCaseExecution | None,
) -> FindingClassification:
    if baseline is None:
        return FindingClassification.NEW_TEST
    if current is None:
        return FindingClassification.MISSING_TEST
    before = baseline.status
    after = current.status
    if before in FAILURE_STATUSES and after in FAILURE_STATUSES:
        return FindingClassification.EXISTING_FAILURE
    if before not in FAILURE_STATUSES and after in FAILURE_STATUSES:
        return FindingClassification.NEW_FAILURE
    if before in FAILURE_STATUSES and after is ExecutionStatus.PASSED:
        return FindingClassification.RECOVERED
    if before is ExecutionStatus.PASSED and after is ExecutionStatus.PASSED:
        return FindingClassification.UNCHANGED_PASS
    if before is ExecutionStatus.PASSED and after is ExecutionStatus.SKIPPED:
        return FindingClassification.NEWLY_SKIPPED
    if before is ExecutionStatus.SKIPPED and after is ExecutionStatus.SKIPPED:
        return FindingClassification.UNCHANGED_SKIPPED
    return FindingClassification.STATUS_CHANGED
