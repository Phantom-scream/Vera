"""Add stable test identity and persisted regression comparisons.

Revision ID: 20260914_03
Revises: 20260914_02
Create Date: 2026-09-14
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "20260914_03"
down_revision: str | None = "20260914_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "test_case_executions", sa.Column("stable_test_key", sa.String(67), nullable=True)
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            SELECT cases.id, cases.name, cases.classname, cases.file,
                   suites.name AS suite_name, suites.package AS suite_package
            FROM test_case_executions AS cases
            JOIN test_suites AS suites ON suites.id = cases.test_suite_id
            """
        )
    ).mappings()
    for row in rows:
        connection.execute(
            sa.text(
                "UPDATE test_case_executions SET stable_test_key = :stable_test_key WHERE id = :id"
            ),
            {"stable_test_key": _stable_test_key(row), "id": row["id"]},
        )
    op.alter_column("test_case_executions", "stable_test_key", nullable=False)
    op.create_index(
        "ix_test_case_executions_stable_test_key",
        "test_case_executions",
        ["stable_test_key"],
    )

    op.create_table(
        "regression_comparisons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("current_run_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_run_id", sa.Uuid(), nullable=False),
        sa.Column("baseline_strategy", sa.String(30), nullable=False),
        sa.Column("baseline_reason", sa.String(1000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("current_total", sa.Integer(), nullable=False),
        sa.Column("baseline_total", sa.Integer(), nullable=False),
        sa.Column("new_failures", sa.Integer(), nullable=False),
        sa.Column("existing_failures", sa.Integer(), nullable=False),
        sa.Column("recovered_tests", sa.Integer(), nullable=False),
        sa.Column("new_tests", sa.Integer(), nullable=False),
        sa.Column("missing_tests", sa.Integer(), nullable=False),
        sa.Column("status_changes", sa.Integer(), nullable=False),
        sa.Column("unchanged_tests", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "current_run_id <> baseline_run_id", name="ck_comparisons_distinct_runs"
        ),
        sa.CheckConstraint(
            "current_total >= 0 AND baseline_total >= 0 AND new_failures >= 0 "
            "AND existing_failures >= 0 AND recovered_tests >= 0 AND new_tests >= 0 "
            "AND missing_tests >= 0 AND status_changes >= 0 AND unchanged_tests >= 0",
            name="ck_comparisons_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(["baseline_run_id"], ["test_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["current_run_id"], ["test_runs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "current_run_id", "baseline_run_id", name="uq_comparisons_current_baseline"
        ),
    )
    op.create_index(
        "ix_comparisons_current_created",
        "regression_comparisons",
        ["current_run_id", "created_at"],
    )
    op.create_index("ix_comparisons_baseline_run_id", "regression_comparisons", ["baseline_run_id"])

    op.create_table(
        "test_comparison_findings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("comparison_id", sa.Uuid(), nullable=False),
        sa.Column("test_key", sa.String(67), nullable=False),
        sa.Column("current_case_id", sa.Uuid(), nullable=True),
        sa.Column("baseline_case_id", sa.Uuid(), nullable=True),
        sa.Column("baseline_status", sa.String(20), nullable=True),
        sa.Column("current_status", sa.String(20), nullable=True),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.ForeignKeyConstraint(
            ["baseline_case_id"], ["test_case_executions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["comparison_id"], ["regression_comparisons.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["current_case_id"], ["test_case_executions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("comparison_id", "test_key", name="uq_findings_comparison_test_key"),
    )
    op.create_index(
        "ix_findings_comparison_classification",
        "test_comparison_findings",
        ["comparison_id", "classification"],
    )


def downgrade() -> None:
    op.drop_index("ix_findings_comparison_classification", table_name="test_comparison_findings")
    op.drop_table("test_comparison_findings")
    op.drop_index("ix_comparisons_baseline_run_id", table_name="regression_comparisons")
    op.drop_index("ix_comparisons_current_created", table_name="regression_comparisons")
    op.drop_table("regression_comparisons")
    op.drop_index("ix_test_case_executions_stable_test_key", table_name="test_case_executions")
    op.drop_column("test_case_executions", "stable_test_key")


def _stable_test_key(row: sa.RowMapping) -> str:
    classname = _normalize(row["classname"])
    file = _normalize(row["file"])
    suite = None
    if classname is None and file is None:
        suite = [_normalize(row["suite_package"]), _normalize(row["suite_name"])]
    canonical = json.dumps(
        {
            "classname": classname,
            "file": file,
            "name": row["name"].strip() or None,
            "suite": suite,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"v1:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _normalize(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
