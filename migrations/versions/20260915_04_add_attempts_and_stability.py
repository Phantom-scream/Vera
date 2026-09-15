"""Preserve observed case attempts and versioned stability evidence.

Revision ID: 20260915_04
Revises: 20260914_03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "20260915_04"
down_revision: str | None = "20260914_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "test_case_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "test_case_execution_id",
            sa.Uuid(),
            sa.ForeignKey("test_case_executions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("failure_type", sa.String(1000)),
        sa.Column("failure_message", sa.Text()),
        sa.Column("stack_trace", sa.Text()),
        sa.UniqueConstraint("test_case_execution_id", "attempt", name="uq_case_attempt_number"),
        sa.CheckConstraint("attempt >= 1 AND duration_seconds >= 0", name="ck_case_attempt_values"),
        sa.CheckConstraint(
            "status IN ('passed','failed','error','skipped')", name="ck_case_attempt_status"
        ),
    )
    # Reuse case UUIDs in this separate table; preserve only genuinely observed outcomes.
    op.execute("""INSERT INTO test_case_attempts
        (id, test_case_execution_id, attempt, status, duration_seconds,
         failure_type, failure_message, stack_trace)
        SELECT c.id, c.id, c.attempt, c.status, c.duration_seconds, f.type, f.message, f.stack_trace
        FROM test_case_executions c LEFT JOIN test_failures f ON f.test_case_execution_id = c.id""")
    op.create_table(
        "test_stability_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "reference_run_id",
            sa.Uuid(),
            sa.ForeignKey("test_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("test_key", sa.String(67), nullable=False),
        sa.Column("history_window", sa.Integer(), nullable=False),
        sa.Column("policy_key", sa.String(64), nullable=False),
        sa.Column("scoring_version", sa.String(50), nullable=False),
        sa.Column("environment_fingerprint", sa.String(64), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("flaky_score", sa.Float(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "reference_run_id",
            "test_key",
            "history_window",
            "policy_key",
            name="uq_stability_snapshot",
        ),
        sa.CheckConstraint("history_window BETWEEN 1 AND 100", name="ck_stability_window"),
    )
    op.create_index(
        "ix_stability_run_classification",
        "test_stability_snapshots",
        ["reference_run_id", "classification"],
    )


def downgrade() -> None:
    op.drop_index("ix_stability_run_classification", table_name="test_stability_snapshots")
    op.drop_table("test_stability_snapshots")
    op.drop_table("test_case_attempts")
