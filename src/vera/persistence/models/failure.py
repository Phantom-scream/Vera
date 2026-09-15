"""Persistent normalized failure families."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vera.persistence.database import Base

if TYPE_CHECKING:
    from vera.persistence.models.test_run import TestFailureRecord


class FailureFamilyRecord(Base):
    """One deterministic family identified by a versioned cryptographic fingerprint."""

    __tablename__ = "failure_families"
    __table_args__ = (
        UniqueConstraint(
            "fingerprint", "fingerprint_version", name="uq_failure_family_fingerprint"
        ),
        Index("ix_failure_families_last_seen", "last_seen_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint_version: Mapped[str] = mapped_column(String(50))
    canonical_type: Mapped[str] = mapped_column(String(500))
    canonical_message: Mapped[str] = mapped_column(Text)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    first_seen_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    last_seen_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="RESTRICT"))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[list["TestFailureRecord"]] = relationship(back_populates="family")
