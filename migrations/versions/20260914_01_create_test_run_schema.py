"""Create normalized test-run ingestion schema.

Revision ID: 20260914_01
Revises:
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("external_run_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("repository", sa.String(length=500), nullable=False),
        sa.Column("branch", sa.String(length=500), nullable=True),
        sa.Column("commit_sha", sa.String(length=128), nullable=True),
        sa.Column("pipeline_id", sa.String(length=255), nullable=False),
        sa.Column("job_id", sa.String(length=255), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("total_tests", sa.Integer(), nullable=False),
        sa.Column("passed_tests", sa.Integer(), nullable=False),
        sa.Column("failed_tests", sa.Integer(), nullable=False),
        sa.Column("skipped_tests", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("duration_seconds >= 0", name="ck_test_runs_duration_nonnegative"),
        sa.CheckConstraint(
            "total_tests >= 0 AND passed_tests >= 0 AND failed_tests >= 0 AND skipped_tests >= 0",
            name="ck_test_runs_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "total_tests = passed_tests + failed_tests + skipped_tests",
            name="ck_test_runs_counts_consistent",
        ),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'skipped', 'error')",
            name="ck_test_runs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "repository",
            "pipeline_id",
            "job_id",
            "external_run_id",
            name="uq_test_runs_ingestion_identity",
        ),
    )
    op.create_index("ix_test_runs_commit_sha", "test_runs", ["commit_sha"])
    op.create_index("ix_test_runs_repository_created_at", "test_runs", ["repository", "created_at"])

    op.create_table(
        "environment_contexts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column("environment", sa.String(length=100), nullable=True),
        sa.Column("application_version", sa.String(length=255), nullable=True),
        sa.Column("build_number", sa.String(length=255), nullable=True),
        sa.Column("platform", sa.String(length=255), nullable=True),
        sa.Column("browser", sa.String(length=255), nullable=True),
        sa.Column("device", sa.String(length=255), nullable=True),
        sa.Column("test_configuration", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_run_id"),
    )
    op.create_table(
        "test_suites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column("package", sa.String(length=1000), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("total_tests", sa.Integer(), nullable=False),
        sa.Column("passed_tests", sa.Integer(), nullable=False),
        sa.Column("failed_tests", sa.Integer(), nullable=False),
        sa.Column("skipped_tests", sa.Integer(), nullable=False),
        sa.CheckConstraint("duration_seconds >= 0", name="ck_test_suites_duration_nonnegative"),
        sa.CheckConstraint(
            "total_tests = passed_tests + failed_tests + skipped_tests",
            name="ck_test_suites_counts_consistent",
        ),
        sa.ForeignKeyConstraint(["test_run_id"], ["test_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_run_id", "position", name="uq_test_suites_run_position"),
    )
    op.create_index("ix_test_suites_test_run_id", "test_suites", ["test_run_id"])

    op.create_table(
        "test_case_executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_suite_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=1000), nullable=False),
        sa.Column("classname", sa.String(length=1000), nullable=True),
        sa.Column("file", sa.String(length=2000), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "duration_seconds >= 0", name="ck_test_case_executions_duration_nonnegative"
        ),
        sa.CheckConstraint("attempt >= 1", name="ck_test_case_executions_attempt_positive"),
        sa.CheckConstraint(
            "status IN ('passed', 'failed', 'skipped', 'error')",
            name="ck_test_case_executions_status",
        ),
        sa.ForeignKeyConstraint(["test_suite_id"], ["test_suites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "test_suite_id", "position", name="uq_test_case_executions_suite_position"
        ),
    )
    op.create_index(
        "ix_test_case_executions_classname_name",
        "test_case_executions",
        ["classname", "name"],
    )
    op.create_index(
        "ix_test_case_executions_test_suite_id", "test_case_executions", ["test_suite_id"]
    )

    op.create_table(
        "test_failures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("test_case_execution_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=1000), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("stack_trace", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["test_case_execution_id"], ["test_case_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("test_case_execution_id"),
    )


def downgrade() -> None:
    op.drop_table("test_failures")
    op.drop_index("ix_test_case_executions_test_suite_id", table_name="test_case_executions")
    op.drop_index("ix_test_case_executions_classname_name", table_name="test_case_executions")
    op.drop_table("test_case_executions")
    op.drop_index("ix_test_suites_test_run_id", table_name="test_suites")
    op.drop_table("test_suites")
    op.drop_table("environment_contexts")
    op.drop_index("ix_test_runs_repository_created_at", table_name="test_runs")
    op.drop_index("ix_test_runs_commit_sha", table_name="test_runs")
    op.drop_table("test_runs")
