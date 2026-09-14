"""Add normalized CI execution context and retry-aware identity.

Revision ID: 20260914_02
Revises: 20260914_01
Create Date: 2026-09-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_02"
down_revision: str | None = "20260914_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("test_runs", sa.Column("repository_url", sa.String(2000), nullable=True))
    op.add_column("test_runs", sa.Column("pipeline_name", sa.String(500), nullable=True))
    op.add_column("test_runs", sa.Column("pipeline_url", sa.String(2000), nullable=True))
    op.add_column("test_runs", sa.Column("job_name", sa.String(500), nullable=True))
    op.add_column("test_runs", sa.Column("job_url", sa.String(2000), nullable=True))
    op.add_column("test_runs", sa.Column("run_number", sa.Integer(), nullable=True))
    op.add_column(
        "test_runs",
        sa.Column("run_attempt", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("test_runs", sa.Column("trigger_source", sa.String(255), nullable=True))
    op.add_column("test_runs", sa.Column("actor", sa.String(500), nullable=True))
    op.add_column(
        "test_runs",
        sa.Column("detected_from_ci", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("test_runs", sa.Column("git_ref", sa.String(1000), nullable=True))
    op.add_column("test_runs", sa.Column("default_branch", sa.String(500), nullable=True))
    op.add_column("test_runs", sa.Column("commit_message", sa.Text(), nullable=True))
    op.add_column("test_runs", sa.Column("commit_author", sa.String(500), nullable=True))
    op.add_column("test_runs", sa.Column("change_request_kind", sa.String(30), nullable=True))
    op.add_column("test_runs", sa.Column("change_request_number", sa.String(255), nullable=True))
    op.add_column("test_runs", sa.Column("change_request_title", sa.String(2000), nullable=True))
    op.add_column(
        "test_runs", sa.Column("change_request_source_branch", sa.String(500), nullable=True)
    )
    op.add_column(
        "test_runs", sa.Column("change_request_target_branch", sa.String(500), nullable=True)
    )
    op.add_column("test_runs", sa.Column("change_request_url", sa.String(2000), nullable=True))
    op.alter_column("test_runs", "run_attempt", server_default=None)
    op.alter_column("test_runs", "detected_from_ci", server_default=None)

    op.drop_constraint("uq_test_runs_ingestion_identity", "test_runs", type_="unique")
    op.create_check_constraint("ck_test_runs_run_attempt_positive", "test_runs", "run_attempt >= 1")
    op.create_unique_constraint(
        "uq_test_runs_ingestion_identity",
        "test_runs",
        ["provider", "repository", "pipeline_id", "job_id", "external_run_id", "run_attempt"],
    )
    op.create_index(
        "ix_test_runs_repository_branch_created_at",
        "test_runs",
        ["repository", "branch", "created_at"],
    )
    op.create_index(
        "ix_test_runs_provider_repository_pipeline",
        "test_runs",
        ["provider", "repository", "pipeline_id"],
    )
    op.create_index(
        "ix_test_runs_repository_change_request",
        "test_runs",
        ["repository", "change_request_number"],
    )


def downgrade() -> None:
    op.drop_index("ix_test_runs_repository_change_request", table_name="test_runs")
    op.drop_index("ix_test_runs_provider_repository_pipeline", table_name="test_runs")
    op.drop_index("ix_test_runs_repository_branch_created_at", table_name="test_runs")
    op.drop_constraint("uq_test_runs_ingestion_identity", "test_runs", type_="unique")
    op.drop_constraint("ck_test_runs_run_attempt_positive", "test_runs", type_="check")
    op.execute(
        """
        DELETE FROM test_runs
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY provider, repository, pipeline_id, job_id, external_run_id
                    ORDER BY run_attempt, created_at, id
                ) AS duplicate_number
                FROM test_runs
            ) AS ranked_runs
            WHERE duplicate_number > 1
        )
        """
    )
    op.create_unique_constraint(
        "uq_test_runs_ingestion_identity",
        "test_runs",
        ["provider", "repository", "pipeline_id", "job_id", "external_run_id"],
    )
    for column in (
        "change_request_url",
        "change_request_target_branch",
        "change_request_source_branch",
        "change_request_title",
        "change_request_number",
        "change_request_kind",
        "commit_author",
        "commit_message",
        "default_branch",
        "git_ref",
        "detected_from_ci",
        "actor",
        "trigger_source",
        "run_attempt",
        "run_number",
        "job_url",
        "job_name",
        "pipeline_url",
        "pipeline_name",
        "repository_url",
    ):
        op.drop_column("test_runs", column)
