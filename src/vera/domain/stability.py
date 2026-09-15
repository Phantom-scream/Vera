"""Deterministic bounded-history metrics and explainable flaky-v1 scoring."""

from collections import Counter
from itertools import pairwise

from vera.domain.enums import ExecutionStatus
from vera.domain.models.stability import (
    HistoryMetrics,
    HistoryObservation,
    ScoringPolicy,
    StabilityClass,
)

BAD = {ExecutionStatus.FAILED, ExecutionStatus.ERROR}


def history_metrics(
    observations: tuple[HistoryObservation, ...], recent_window: int = 5
) -> HistoryMetrics:
    """Calculate from oldest-first initial observations; skipped/unknown are non-decisive."""
    counts = Counter(item.initial_status for item in observations)
    decisive = [
        item for item in observations if item.initial_status in BAD | {ExecutionStatus.PASSED}
    ]
    failures = [item for item in decisive if item.initial_status in BAD]
    passes = [item for item in decisive if item.initial_status is ExecutionStatus.PASSED]
    flips = sum(
        (a.initial_status in BAD) != (b.initial_status in BAD) for a, b in pairwise(decisive)
    )
    recent = decisive[-recent_window:]
    retry_count = opportunities = recoveries = ci_reruns = ci_recoveries = 0
    attempt_flips = decisive_attempt_pairs = 0
    observed_failures = [
        item for item in observations if any(status in BAD for status in item.attempt_statuses)
    ]
    previous: dict[str, HistoryObservation] = {}
    for item in observations:
        retry_count += len(item.attempt_statuses) - 1
        for (number, before), (next_number, after) in pairwise(
            zip(item.attempt_numbers, item.attempt_statuses, strict=True)
        ):
            if (
                next_number == number + 1
                and before in BAD | {ExecutionStatus.PASSED}
                and after in BAD | {ExecutionStatus.PASSED}
            ):
                decisive_attempt_pairs += 1
                attempt_flips += (before in BAD) != (after in BAD)
            if next_number == number + 1 and before in BAD:
                opportunities += 1
                recoveries += after is ExecutionStatus.PASSED
        prior = previous.get(item.ci_series_key)
        if prior is not None:
            ci_reruns += 1
            ci_recoveries += (
                prior.final_status in BAD and item.final_status is ExecutionStatus.PASSED
            )
        previous[item.ci_series_key] = item
    consecutive_failures = consecutive_passes = 0
    for item in reversed(observations):
        if item.initial_status not in BAD:
            break
        consecutive_failures += 1
    for item in reversed(observations):
        if item.initial_status is not ExecutionStatus.PASSED:
            break
        consecutive_passes += 1
    return HistoryMetrics(
        total_executions=len(observations),
        decisive_executions=len(decisive),
        independent_pipelines=len({item.pipeline_key for item in decisive}),
        failure_pipelines=len({item.pipeline_key for item in observed_failures}),
        passed_executions=counts[ExecutionStatus.PASSED],
        failed_executions=counts[ExecutionStatus.FAILED],
        errored_executions=counts[ExecutionStatus.ERROR],
        skipped_executions=counts[ExecutionStatus.SKIPPED],
        unknown_initial_executions=counts[None],
        final_passed_executions=sum(
            item.final_status is ExecutionStatus.PASSED for item in observations
        ),
        final_failed_executions=sum(
            item.final_status is ExecutionStatus.FAILED for item in observations
        ),
        final_errored_executions=sum(
            item.final_status is ExecutionStatus.ERROR for item in observations
        ),
        final_skipped_executions=sum(
            item.final_status is ExecutionStatus.SKIPPED for item in observations
        ),
        observed_failure_executions=len(observed_failures),
        observed_pass_executions=sum(
            ExecutionStatus.PASSED in item.attempt_statuses for item in observations
        ),
        attempt_flip_count=attempt_flips,
        attempt_flip_rate=attempt_flips / decisive_attempt_pairs if decisive_attempt_pairs else 0,
        failure_rate=len(failures) / len(decisive) if decisive else 0,
        pass_rate=len(passes) / len(decisive) if decisive else 0,
        status_flip_count=flips,
        status_flip_rate=flips / (len(decisive) - 1) if len(decisive) > 1 else 0,
        consecutive_failures=consecutive_failures,
        consecutive_passes=consecutive_passes,
        recent_failure_rate=sum(item.initial_status in BAD for item in recent) / len(recent)
        if recent
        else 0,
        first_seen_at=observations[0].created_at if observations else None,
        last_seen_at=observations[-1].created_at if observations else None,
        last_failure_at=failures[-1].created_at if failures else None,
        last_pass_at=passes[-1].created_at if passes else None,
        retry_count=retry_count,
        retry_opportunities=opportunities,
        retry_recoveries=recoveries,
        retry_success_rate=recoveries / opportunities if opportunities else 0,
        ci_rerun_count=ci_reruns,
        ci_rerun_recoveries=ci_recoveries,
    )


def score_stability(
    metrics: HistoryMetrics, policy: ScoringPolicy
) -> tuple[float, float, StabilityClass, str]:
    """Return scores and classification with independent-history evidence gates."""
    failure = metrics.failure_rate
    recent = metrics.recent_failure_rate
    retry_evidence = max(
        metrics.retry_success_rate,
        metrics.ci_rerun_recoveries / metrics.ci_rerun_count if metrics.ci_rerun_count else 0,
    )
    raw = 100 * (
        policy.mixed_weight * 4 * failure * (1 - failure)
        + policy.flip_weight * max(metrics.status_flip_rate, metrics.attempt_flip_rate)
        + policy.recent_weight * 4 * recent * (1 - recent)
        + policy.retry_weight * retry_evidence
    )
    # Repeated retry recoveries are direct within-execution instability evidence.
    retry_floor = (
        policy.retry_floor_score * retry_evidence
        if metrics.retry_recoveries + metrics.ci_rerun_recoveries >= policy.minimum_retry_recoveries
        else 0
    )
    score = round(min(100, max(raw, retry_floor)), 2)
    reliability = round(100 * metrics.pass_rate, 2)
    if metrics.independent_pipelines < policy.minimum_observations:
        return (
            reliability,
            score,
            StabilityClass.INSUFFICIENT_HISTORY,
            "Fewer than minimum independent decisive pipelines",
        )
    if failure == 1 and metrics.observed_pass_executions == 0:
        return (
            reliability,
            0,
            StabilityClass.CONSISTENTLY_FAILING,
            "No observed attempt passed and every decisive initial outcome failed",
        )
    if metrics.observed_failure_executions == 0:
        classification = (
            StabilityClass.STABLE
            if metrics.independent_pipelines >= policy.stable_observations
            else StabilityClass.LIKELY_STABLE
        )
        return reliability, 0, classification, "No observed failures or retry recoveries"
    if metrics.failure_pipelines < policy.minimum_failure_pipelines:
        return (
            reliability,
            score,
            StabilityClass.LIKELY_STABLE,
            "Failure evidence is confined to fewer than two independent pipelines",
        )
    if score >= policy.flaky_threshold:
        return (
            reliability,
            score,
            StabilityClass.FLAKY,
            "Repeated independent failures with high transition/retry evidence",
        )
    if score >= policy.suspected_threshold:
        return (
            reliability,
            score,
            StabilityClass.SUSPECTED_FLAKY,
            "Repeated independent failures with moderate instability evidence",
        )
    return (
        reliability,
        score,
        StabilityClass.LIKELY_STABLE,
        "Observed instability below suspected threshold",
    )
