"""Observed attempts and auditable bounded stability snapshots."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vera.persistence.database import Base

if TYPE_CHECKING:
    from vera.persistence.models.test_run import TestCaseExecutionRecord


class TestCaseAttemptRecord(Base):
    __tablename__ = "test_case_attempts"
    __table_args__ = (
        UniqueConstraint("test_case_execution_id", "attempt", name="uq_case_attempt_number"),
        CheckConstraint("attempt >= 1 AND duration_seconds >= 0", name="ck_case_attempt_values"),
        CheckConstraint(
            "status IN ('passed','failed','error','skipped')", name="ck_case_attempt_status"
        ),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    test_case_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_case_executions.id", ondelete="CASCADE")
    )
    attempt: Mapped[int]
    status: Mapped[str] = mapped_column(String(20))
    duration_seconds: Mapped[float] = mapped_column(Float)
    failure_type: Mapped[str | None] = mapped_column(String(1000))
    failure_message: Mapped[str | None] = mapped_column(Text)
    stack_trace: Mapped[str | None] = mapped_column(Text)
    case: Mapped["TestCaseExecutionRecord"] = relationship(back_populates="attempts")


class TestStabilitySnapshotRecord(Base):
    __tablename__ = "test_stability_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "reference_run_id",
            "test_key",
            "history_window",
            "policy_key",
            name="uq_stability_snapshot",
        ),
        CheckConstraint("history_window BETWEEN 1 AND 100", name="ck_stability_window"),
        Index("ix_stability_run_classification", "reference_run_id", "classification"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    reference_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    test_key: Mapped[str] = mapped_column(String(67))
    history_window: Mapped[int]
    policy_key: Mapped[str] = mapped_column(String(64))
    scoring_version: Mapped[str] = mapped_column(String(50))
    environment_fingerprint: Mapped[str] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(30))
    flaky_score: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
