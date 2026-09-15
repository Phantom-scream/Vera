from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from vera.domain.enums import ExecutionStatus as Status
from vera.domain.models import EnvironmentContext
from vera.domain.models.stability import (
    HistoryObservation,
    ScoringPolicy,
    StabilityClass,
    environment_fingerprint,
)
from vera.domain.stability import history_metrics, score_stability


def observations(statuses: list[Status], retry: bool = False) -> tuple[HistoryObservation, ...]:
    return tuple(
        HistoryObservation(
            run_id=uuid4(),
            case_id=uuid4(),
            created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
            pipeline_key=str(index),
            ci_series_key=str(index),
            initial_status=status,
            final_status=Status.PASSED if retry else status,
            attempt_statuses=(status, Status.PASSED) if retry else (status,),
            attempt_numbers=(1, 2) if retry else (1,),
        )
        for index, status in enumerate(statuses)
    )


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([Status.PASSED] * 20, StabilityClass.STABLE),
        ([Status.FAILED] * 20, StabilityClass.CONSISTENTLY_FAILING),
        ([Status.ERROR] * 20, StabilityClass.CONSISTENTLY_FAILING),
        ([Status.PASSED, Status.FAILED] * 10, StabilityClass.FLAKY),
        ([Status.FAILED] + [Status.PASSED] * 19, StabilityClass.LIKELY_STABLE),
        ([Status.PASSED] * 5, StabilityClass.INSUFFICIENT_HISTORY),
        ([Status.SKIPPED] * 20, StabilityClass.INSUFFICIENT_HISTORY),
        (
            [Status.PASSED] * 2
            + [Status.FAILED]
            + [Status.PASSED] * 3
            + [Status.FAILED]
            + [Status.PASSED] * 13,
            StabilityClass.SUSPECTED_FLAKY,
        ),
    ],
)
def test_expected_stability_classes(statuses: list[Status], expected: StabilityClass) -> None:
    metrics = history_metrics(observations(statuses))
    reliability, score, classification, reason = score_stability(metrics, ScoringPolicy())
    assert classification is expected
    assert 0 <= score <= 100 and 0 <= reliability <= 100
    assert reason


def test_repeated_retry_recoveries_are_evidence_but_one_is_not() -> None:
    recovered = observations([Status.FAILED] * 20, retry=True)
    metrics = history_metrics(recovered)
    assert metrics.retry_count == metrics.retry_recoveries == metrics.retry_opportunities == 20
    assert metrics.retry_success_rate == 1
    assert score_stability(metrics, ScoringPolicy())[2] is StabilityClass.FLAKY
    one = recovered[:1] + observations([Status.PASSED] * 19)
    assert score_stability(history_metrics(one), ScoringPolicy())[2] is StabilityClass.LIKELY_STABLE


def test_skipped_and_unknown_outcomes_are_non_decisive_and_break_streaks() -> None:
    history = observations([Status.PASSED, Status.SKIPPED, Status.ERROR, Status.SKIPPED])
    metrics = history_metrics(history)
    assert metrics.pass_rate == metrics.failure_rate == 0.5
    assert metrics.status_flip_count == 1
    assert metrics.consecutive_failures == metrics.consecutive_passes == 0
    assert metrics.last_failure_at == history[2].created_at
    unknown = history[0].model_copy(update={"initial_status": None, "attempt_numbers": (3,)})
    assert history_metrics((unknown,)).unknown_initial_executions == 1


def test_ci_reruns_are_not_test_retries_and_one_pipeline_is_insufficient() -> None:
    history = observations([Status.FAILED, Status.PASSED] * 10)
    same_pipeline = tuple(
        item.model_copy(update={"pipeline_key": "one", "ci_series_key": "one-job"})
        for item in history
    )
    metrics = history_metrics(same_pipeline)
    assert metrics.retry_count == 0
    assert metrics.ci_rerun_count == 19 and metrics.ci_rerun_recoveries == 10
    assert score_stability(metrics, ScoringPolicy())[2] is StabilityClass.INSUFFICIENT_HISTORY


def test_policy_version_boundaries_and_fingerprints() -> None:
    policy = ScoringPolicy()
    assert policy.version == "flaky-v1"
    with pytest.raises(ValidationError):
        ScoringPolicy(flip_weight=1)
    with pytest.raises(ValidationError):
        ScoringPolicy(suspected_threshold=70, flaky_threshold=50)
    chrome = EnvironmentContext(
        environment="staging", browser="chrome", test_configuration={"b": 2, "a": 1}
    )
    assert environment_fingerprint(chrome) == environment_fingerprint(
        chrome.model_copy(
            update={"application_version": "next", "test_configuration": {"a": 1, "b": 2}}
        )
    )
    assert environment_fingerprint(chrome) != environment_fingerprint(
        chrome.model_copy(update={"browser": "firefox"})
    )


def test_initial_pass_then_failed_retry_is_not_stable() -> None:
    history = tuple(
        item.model_copy(
            update={
                "final_status": Status.FAILED,
                "attempt_statuses": (Status.PASSED, Status.FAILED),
                "attempt_numbers": (1, 2),
            }
        )
        for item in observations([Status.PASSED] * 20)
    )
    metrics = history_metrics(history)
    assert metrics.pass_rate == 1 and metrics.final_failed_executions == 20
    assert metrics.attempt_flip_rate == 1
    assert score_stability(metrics, ScoringPolicy())[2] is StabilityClass.SUSPECTED_FLAKY
