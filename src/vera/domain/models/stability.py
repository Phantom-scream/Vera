"""Versioned, provider-neutral stability evidence and scoring policy."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, model_validator

from vera.domain.enums import ExecutionStatus
from vera.domain.models.base import DomainModel
from vera.domain.models.test_run import EnvironmentContext


class StabilityClass(StrEnum):
    STABLE = "stable"
    LIKELY_STABLE = "likely_stable"
    INSUFFICIENT_HISTORY = "insufficient_history"
    SUSPECTED_FLAKY = "suspected_flaky"
    FLAKY = "flaky"
    CONSISTENTLY_FAILING = "consistently_failing"


class ScoringPolicy(DomainModel):
    """Centralized transparent flaky-v1 weights and minimum-evidence thresholds."""

    version: Literal["flaky-v1"] = "flaky-v1"
    minimum_observations: int = Field(default=10, ge=2, le=100)
    stable_observations: int = Field(default=20, ge=2, le=100)
    minimum_failure_pipelines: int = Field(default=2, ge=2)
    suspected_threshold: float = Field(default=18, ge=0, le=100)
    flaky_threshold: float = Field(default=50, ge=0, le=100)
    mixed_weight: float = Field(default=0.35, ge=0, le=1)
    flip_weight: float = Field(default=0.30, ge=0, le=1)
    recent_weight: float = Field(default=0.15, ge=0, le=1)
    retry_weight: float = Field(default=0.20, ge=0, le=1)
    recent_window: int = Field(default=5, ge=2, le=100)
    retry_floor_score: float = Field(default=60, ge=0, le=100)
    minimum_retry_recoveries: int = Field(default=2, ge=2)

    @model_validator(mode="after")
    def validate_policy(self) -> Self:
        if (
            abs(self.mixed_weight + self.flip_weight + self.recent_weight + self.retry_weight - 1)
            > 1e-9
        ):
            raise ValueError("scoring weights must sum to one")
        if (
            self.suspected_threshold > self.flaky_threshold
            or self.stable_observations < self.minimum_observations
        ):
            raise ValueError("scoring thresholds must be ordered")
        return self


class HistoryObservation(DomainModel):
    """A complete report observation with no test output or failure secrets."""

    run_id: UUID
    case_id: UUID
    created_at: datetime
    pipeline_key: str
    ci_series_key: str
    initial_status: ExecutionStatus | None
    final_status: ExecutionStatus
    attempt_statuses: tuple[ExecutionStatus, ...]
    attempt_numbers: tuple[int, ...]

    @model_validator(mode="after")
    def validate_attempts(self) -> Self:
        if (
            not self.attempt_numbers
            or len(self.attempt_numbers) != len(self.attempt_statuses)
            or len(self.attempt_numbers) > 100
        ):
            raise ValueError("observations require 1 to 100 aligned attempts")
        if list(self.attempt_numbers) != sorted(set(self.attempt_numbers)):
            raise ValueError("observed attempts must be uniquely ordered")
        if self.attempt_statuses[-1] != self.final_status:
            raise ValueError("final outcome must match the last observed attempt")
        return self


class HistoryMetrics(DomainModel):
    """Initial-outcome rates alongside final and within-attempt evidence."""

    total_executions: int
    decisive_executions: int
    independent_pipelines: int
    failure_pipelines: int
    passed_executions: int
    failed_executions: int
    errored_executions: int
    skipped_executions: int
    unknown_initial_executions: int
    final_passed_executions: int
    final_failed_executions: int
    final_errored_executions: int
    final_skipped_executions: int
    observed_failure_executions: int
    observed_pass_executions: int
    attempt_flip_count: int
    attempt_flip_rate: float
    failure_rate: float
    pass_rate: float
    status_flip_count: int
    status_flip_rate: float
    consecutive_failures: int
    consecutive_passes: int
    recent_failure_rate: float
    first_seen_at: datetime | None
    last_seen_at: datetime | None
    last_failure_at: datetime | None
    last_pass_at: datetime | None
    retry_count: int
    retry_opportunities: int
    retry_recoveries: int
    retry_success_rate: float
    ci_rerun_count: int
    ci_rerun_recoveries: int


class TestStabilityAnalysis(DomainModel):
    test_key: str
    repository: str
    reference_run_id: UUID
    environment_fingerprint: str
    history_window: int
    scoring_version: str
    policy: ScoringPolicy
    statistics: HistoryMetrics
    reliability_score: float
    flaky_score: float
    classification: StabilityClass
    reason: str
    observations: tuple[HistoryObservation, ...]


def environment_fingerprint(environment: EnvironmentContext) -> str:
    """Fingerprint only comparison dimensions, not versions or build identifiers."""
    values = environment.model_dump(mode="json", exclude={"application_version", "build_number"})
    canonical = json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
