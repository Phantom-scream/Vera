"""Relational representation of persisted regression comparisons."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vera.persistence.database import Base


class RegressionComparisonRecord(Base):
    """Persisted summary for a canonical run pair comparison."""

    __tablename__ = "regression_comparisons"
    __table_args__ = (
        CheckConstraint("current_run_id <> baseline_run_id", name="ck_comparisons_distinct_runs"),
        CheckConstraint(
            "current_total >= 0 AND baseline_total >= 0 AND new_failures >= 0 "
            "AND existing_failures >= 0 AND recovered_tests >= 0 AND new_tests >= 0 "
            "AND missing_tests >= 0 AND status_changes >= 0 AND unchanged_tests >= 0",
            name="ck_comparisons_counts_nonnegative",
        ),
        UniqueConstraint(
            "current_run_id", "baseline_run_id", name="uq_comparisons_current_baseline"
        ),
        Index("ix_comparisons_current_created", "current_run_id", "created_at"),
        Index("ix_comparisons_baseline_run_id", "baseline_run_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    current_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    baseline_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    baseline_strategy: Mapped[str] = mapped_column(String(30))
    baseline_reason: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    current_total: Mapped[int] = mapped_column(Integer)
    baseline_total: Mapped[int] = mapped_column(Integer)
    new_failures: Mapped[int] = mapped_column(Integer)
    existing_failures: Mapped[int] = mapped_column(Integer)
    recovered_tests: Mapped[int] = mapped_column(Integer)
    new_tests: Mapped[int] = mapped_column(Integer)
    missing_tests: Mapped[int] = mapped_column(Integer)
    status_changes: Mapped[int] = mapped_column(Integer)
    unchanged_tests: Mapped[int] = mapped_column(Integer)

    findings: Mapped[list["TestComparisonFindingRecord"]] = relationship(
        back_populates="comparison",
        cascade="all, delete-orphan",
        order_by="TestComparisonFindingRecord.test_key",
    )


class TestComparisonFindingRecord(Base):
    """Persisted status transition for one stable test identity."""

    __tablename__ = "test_comparison_findings"
    __table_args__ = (
        UniqueConstraint("comparison_id", "test_key", name="uq_findings_comparison_test_key"),
        Index("ix_findings_comparison_classification", "comparison_id", "classification"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    comparison_id: Mapped[UUID] = mapped_column(
        ForeignKey("regression_comparisons.id", ondelete="CASCADE")
    )
    test_key: Mapped[str] = mapped_column(String(67))
    current_case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_case_executions.id", ondelete="RESTRICT")
    )
    baseline_case_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("test_case_executions.id", ondelete="RESTRICT")
    )
    baseline_status: Mapped[str | None] = mapped_column(String(20))
    current_status: Mapped[str | None] = mapped_column(String(20))
    classification: Mapped[str] = mapped_column(String(30))

    comparison: Mapped[RegressionComparisonRecord] = relationship(back_populates="findings")
