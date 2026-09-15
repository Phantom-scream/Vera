"""Provider-neutral baseline and regression comparison models."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import Field

from vera.domain.enums import BaselineStrategy, ExecutionStatus, FindingClassification
from vera.domain.models.base import DomainModel
from vera.domain.models.stability import StabilityClass


class BaselineSelection(DomainModel):
    """Structured result explaining whether and why a baseline was selected."""

    current_run_id: UUID
    baseline_run_id: UUID | None = None
    strategy: BaselineStrategy | None = None
    reason: str

    @property
    def found(self) -> bool:
        return self.baseline_run_id is not None


class TestComparisonFinding(DomainModel):
    """One deterministic classification for a stable test identity."""

    id: UUID = Field(default_factory=uuid4)
    comparison_id: UUID | None = None
    test_key: str
    current_case_id: UUID | None = None
    baseline_case_id: UUID | None = None
    baseline_status: ExecutionStatus | None = None
    current_status: ExecutionStatus | None = None
    classification: FindingClassification
    stability: StabilityClass | None = None
    flaky_score: float | None = None
    stability_scoring_version: str | None = None


class RegressionComparison(DomainModel):
    """Persisted aggregate summary for one current/baseline pair."""

    id: UUID = Field(default_factory=uuid4)
    current_run_id: UUID
    baseline_run_id: UUID
    baseline_strategy: BaselineStrategy
    baseline_reason: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_total: int = Field(ge=0)
    baseline_total: int = Field(ge=0)
    new_failures: int = Field(ge=0)
    existing_failures: int = Field(ge=0)
    recovered_tests: int = Field(ge=0)
    new_tests: int = Field(ge=0)
    missing_tests: int = Field(ge=0)
    status_changes: int = Field(ge=0)
    unchanged_tests: int = Field(ge=0)


class ComparisonResult(DomainModel):
    """Comparison summary with its complete or requested finding set."""

    selection: BaselineSelection
    comparison: RegressionComparison | None = None
    findings: tuple[TestComparisonFinding, ...] = ()
    created: bool = False
