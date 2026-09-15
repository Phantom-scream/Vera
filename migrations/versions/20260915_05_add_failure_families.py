"""Add versioned deterministic failure fingerprints and families.

Revision ID: 20260915_05
Revises: 20260915_04
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision: str = "20260915_05"
down_revision: str | None = "20260915_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "failure_families",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("fingerprint_version", sa.String(50), nullable=False),
        sa.Column("canonical_type", sa.String(500), nullable=False),
        sa.Column("canonical_message", sa.Text(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "first_seen_run_id",
            sa.Uuid(),
            sa.ForeignKey("test_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_run_id",
            sa.Uuid(),
            sa.ForeignKey("test_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint(
            "fingerprint", "fingerprint_version", name="uq_failure_family_fingerprint"
        ),
    )
    op.create_index("ix_failure_families_last_seen", "failure_families", ["last_seen_at"])
    op.add_column("test_failures", sa.Column("normalized_type", sa.String(500)))
    op.add_column("test_failures", sa.Column("normalized_message", sa.Text()))
    op.add_column("test_failures", sa.Column("fingerprint", sa.String(64)))
    op.add_column("test_failures", sa.Column("fingerprint_version", sa.String(50)))
    op.add_column(
        "test_failures",
        sa.Column(
            "failure_family_id",
            sa.Uuid(),
            sa.ForeignKey("failure_families.id", ondelete="RESTRICT"),
        ),
    )
    op.create_index("ix_test_failures_fingerprint", "test_failures", ["fingerprint"])
    op.create_index("ix_test_failures_failure_family_id", "test_failures", ["failure_family_id"])
    # Backfill through the same conservative algorithm used for new ingestion.
    from vera.domain.failures import FINGERPRINT_VERSION, normalize_failure

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT f.id, f.type, f.message, f.stack_trace, s.test_run_id "
            "FROM test_failures f "
            "JOIN test_case_executions c ON c.id = f.test_case_execution_id "
            "JOIN test_suites s ON s.id = c.test_suite_id"
        )
    )
    families: dict[str, object] = {}
    for row in rows:
        normalized = normalize_failure(row.type, row.message, row.stack_trace)
        family_id = families.get(normalized.fingerprint)
        if family_id is None:
            family_id = uuid4()
            families[normalized.fingerprint] = family_id
            bind.execute(
                sa.text(
                    "INSERT INTO failure_families "
                    "(id, fingerprint, fingerprint_version, canonical_type, canonical_message, "
                    "first_seen_run_id, last_seen_run_id, occurrence_count) "
                    "VALUES (:id, :fingerprint, :version, :type, :message, :run, :run, 0)"
                ),
                {
                    "id": family_id,
                    "fingerprint": normalized.fingerprint,
                    "version": FINGERPRINT_VERSION,
                    "type": normalized.type,
                    "message": normalized.message,
                    "run": row.test_run_id,
                },
            )
        bind.execute(
            sa.text(
                "UPDATE test_failures SET normalized_type=:type, normalized_message=:message, "
                "fingerprint=:fingerprint, fingerprint_version=:version, failure_family_id=:family "
                "WHERE id=:id"
            ),
            {
                "id": row.id,
                "type": normalized.type,
                "message": normalized.message,
                "fingerprint": normalized.fingerprint,
                "version": FINGERPRINT_VERSION,
                "family": family_id,
            },
        )
    bind.execute(
        sa.text(
            "UPDATE failure_families ff SET occurrence_count = "
            "(SELECT count(*) FROM test_failures tf WHERE tf.failure_family_id = ff.id)"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_test_failures_failure_family_id", table_name="test_failures")
    op.drop_index("ix_test_failures_fingerprint", table_name="test_failures")
    op.drop_column("test_failures", "failure_family_id")
    op.drop_column("test_failures", "fingerprint_version")
    op.drop_column("test_failures", "fingerprint")
    op.drop_column("test_failures", "normalized_message")
    op.drop_column("test_failures", "normalized_type")
    op.drop_index("ix_failure_families_last_seen", table_name="failure_families")
    op.drop_table("failure_families")
