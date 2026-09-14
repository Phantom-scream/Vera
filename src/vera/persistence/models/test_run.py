"""Relational representation of normalized test executions."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from vera.persistence.database import Base


class TestRunRecord(Base):
    """Persisted CI test run and its calculated totals."""

    __tablename__ = "test_runs"
    __table_args__ = (
        CheckConstraint("duration_seconds >= 0", name="ck_test_runs_duration_nonnegative"),
        CheckConstraint(
            "total_tests >= 0 AND passed_tests >= 0 AND failed_tests >= 0 AND skipped_tests >= 0",
            name="ck_test_runs_counts_nonnegative",
        ),
        CheckConstraint(
            "total_tests = passed_tests + failed_tests + skipped_tests",
            name="ck_test_runs_counts_consistent",
        ),
        CheckConstraint(
            "status IN ('passed', 'failed', 'skipped', 'error')",
            name="ck_test_runs_status",
        ),
        UniqueConstraint(
            "provider",
            "repository",
            "pipeline_id",
            "job_id",
            "external_run_id",
            name="uq_test_runs_ingestion_identity",
        ),
        Index("ix_test_runs_repository_created_at", "repository", "created_at"),
        Index("ix_test_runs_commit_sha", "commit_sha"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_run_id: Mapped[str] = mapped_column(String(255))
    provider: Mapped[str] = mapped_column(String(50))
    repository: Mapped[str] = mapped_column(String(500))
    branch: Mapped[str | None] = mapped_column(String(500))
    commit_sha: Mapped[str | None] = mapped_column(String(128))
    pipeline_id: Mapped[str] = mapped_column(String(255))
    job_id: Mapped[str] = mapped_column(String(255))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))
    total_tests: Mapped[int] = mapped_column(Integer)
    passed_tests: Mapped[int] = mapped_column(Integer)
    failed_tests: Mapped[int] = mapped_column(Integer)
    skipped_tests: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    suites: Mapped[list["TestSuiteRecord"]] = relationship(
        back_populates="test_run",
        cascade="all, delete-orphan",
        order_by="TestSuiteRecord.position",
    )
    environment: Mapped["EnvironmentContextRecord"] = relationship(
        back_populates="test_run",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TestSuiteRecord(Base):
    """Persisted suite belonging to one test run."""

    __tablename__ = "test_suites"
    __table_args__ = (
        CheckConstraint("duration_seconds >= 0", name="ck_test_suites_duration_nonnegative"),
        CheckConstraint(
            "total_tests = passed_tests + failed_tests + skipped_tests",
            name="ck_test_suites_counts_consistent",
        ),
        UniqueConstraint("test_run_id", "position", name="uq_test_suites_run_position"),
        Index("ix_test_suites_test_run_id", "test_run_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    test_run_id: Mapped[UUID] = mapped_column(ForeignKey("test_runs.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(1000))
    package: Mapped[str | None] = mapped_column(String(1000))
    duration_seconds: Mapped[float] = mapped_column(Float)
    total_tests: Mapped[int] = mapped_column(Integer)
    passed_tests: Mapped[int] = mapped_column(Integer)
    failed_tests: Mapped[int] = mapped_column(Integer)
    skipped_tests: Mapped[int] = mapped_column(Integer)

    test_run: Mapped[TestRunRecord] = relationship(back_populates="suites")
    test_cases: Mapped[list["TestCaseExecutionRecord"]] = relationship(
        back_populates="test_suite",
        cascade="all, delete-orphan",
        order_by="TestCaseExecutionRecord.position",
    )


class TestCaseExecutionRecord(Base):
    """Persisted normalized test case execution."""

    __tablename__ = "test_case_executions"
    __table_args__ = (
        CheckConstraint(
            "duration_seconds >= 0", name="ck_test_case_executions_duration_nonnegative"
        ),
        CheckConstraint("attempt >= 1", name="ck_test_case_executions_attempt_positive"),
        CheckConstraint(
            "status IN ('passed', 'failed', 'skipped', 'error')",
            name="ck_test_case_executions_status",
        ),
        UniqueConstraint(
            "test_suite_id", "position", name="uq_test_case_executions_suite_position"
        ),
        Index("ix_test_case_executions_test_suite_id", "test_suite_id"),
        Index("ix_test_case_executions_classname_name", "classname", "name"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    test_suite_id: Mapped[UUID] = mapped_column(ForeignKey("test_suites.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(1000))
    classname: Mapped[str | None] = mapped_column(String(1000))
    file: Mapped[str | None] = mapped_column(String(2000))
    duration_seconds: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20))
    attempt: Mapped[int] = mapped_column(Integer, default=1)

    test_suite: Mapped[TestSuiteRecord] = relationship(back_populates="test_cases")
    failure: Mapped["TestFailureRecord | None"] = relationship(
        back_populates="test_case_execution",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TestFailureRecord(Base):
    """Persisted failure or error detail for one test case execution."""

    __tablename__ = "test_failures"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    test_case_execution_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_case_executions.id", ondelete="CASCADE"), unique=True
    )
    type: Mapped[str | None] = mapped_column(String(1000))
    message: Mapped[str | None] = mapped_column(Text)
    stack_trace: Mapped[str | None] = mapped_column(Text)

    test_case_execution: Mapped[TestCaseExecutionRecord] = relationship(back_populates="failure")


class EnvironmentContextRecord(Base):
    """Persisted environment dimensions for one test run."""

    __tablename__ = "environment_contexts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    test_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("test_runs.id", ondelete="CASCADE"), unique=True
    )
    environment: Mapped[str | None] = mapped_column(String(100))
    application_version: Mapped[str | None] = mapped_column(String(255))
    build_number: Mapped[str | None] = mapped_column(String(255))
    platform: Mapped[str | None] = mapped_column(String(255))
    browser: Mapped[str | None] = mapped_column(String(255))
    device: Mapped[str | None] = mapped_column(String(255))
    test_configuration: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    test_run: Mapped[TestRunRecord] = relationship(back_populates="environment")
