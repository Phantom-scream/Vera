"""Indexed lateral history queries: bounded observations and two bulk queries."""

import hashlib
import json
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import Select, String, Uuid, any_, bindparam, cast, func, select, true
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from vera.domain.enums import ExecutionStatus
from vera.domain.exceptions import AmbiguousTestIdentityError
from vera.domain.models import TestRun
from vera.domain.models.stability import HistoryObservation, ScoringPolicy, TestStabilityAnalysis
from vera.persistence.models import (
    EnvironmentContextRecord,
    TestCaseAttemptRecord,
    TestCaseExecutionRecord,
    TestRunRecord,
    TestSuiteRecord,
)
from vera.persistence.models.stability import TestStabilitySnapshotRecord
from vera.providers.retries import execution_series


class TestHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def snapshots(
        self, reference: TestRun, keys: list[str], window: int, policy: ScoringPolicy
    ) -> dict[str, TestStabilityAnalysis]:
        rows = await self.session.scalars(
            select(TestStabilitySnapshotRecord).where(
                TestStabilitySnapshotRecord.reference_run_id == reference.id,
                TestStabilitySnapshotRecord.test_key
                == any_(bindparam("keys", keys, type_=ARRAY(String))),
                TestStabilitySnapshotRecord.history_window == window,
                TestStabilitySnapshotRecord.policy_key == policy_key(policy),
            )
        )
        return {row.test_key: TestStabilityAnalysis.model_validate(row.payload) for row in rows}

    async def store_snapshots(
        self, results: list[TestStabilityAnalysis], policy: ScoringPolicy
    ) -> None:
        for start in range(0, len(results), 500):
            values = [
                dict(
                    reference_run_id=item.reference_run_id,
                    test_key=item.test_key,
                    history_window=item.history_window,
                    policy_key=policy_key(policy),
                    scoring_version=item.scoring_version,
                    environment_fingerprint=item.environment_fingerprint,
                    classification=item.classification.value,
                    flaky_score=item.flaky_score,
                    payload=item.model_dump(mode="json"),
                )
                for item in results[start : start + 500]
            ]
            if values:
                await self.session.execute(
                    insert(TestStabilitySnapshotRecord)
                    .values(values)
                    .on_conflict_do_nothing(constraint="uq_stability_snapshot")
                )

    async def latest_run_id(self, repository: str, test_key: str) -> UUID | None:
        result = await self.session.scalar(
            select(TestRunRecord.id)
            .join(TestSuiteRecord, TestSuiteRecord.test_run_id == TestRunRecord.id)
            .join(
                TestCaseExecutionRecord, TestCaseExecutionRecord.test_suite_id == TestSuiteRecord.id
            )
            .where(
                TestRunRecord.repository == repository,
                TestCaseExecutionRecord.stable_test_key == test_key,
            )
            .order_by(TestRunRecord.created_at.desc(), TestRunRecord.id.desc())
            .limit(1)
        )
        return UUID(str(result)) if result is not None else None

    async def histories(
        self, reference: TestRun, keys: list[str], window: int
    ) -> dict[str, tuple[HistoryObservation, ...]]:
        """Fetch at most window rows per key, preserving duplicate-identity diagnostics."""
        if not keys:
            return {}
        statement = history_statement(reference, keys, window)
        rows = (await self.session.execute(statement)).mappings().all()
        if any(row["identity_count"] > 1 for row in rows):
            raise AmbiguousTestIdentityError(
                "Historical run contains ambiguous duplicate test identities"
            )
        case_ids = [row["case_id"] for row in rows]
        attempts: dict[UUID, list[tuple[int, ExecutionStatus]]] = defaultdict(list)
        if case_ids:
            attempt_rows = await self.session.execute(
                select(
                    TestCaseAttemptRecord.test_case_execution_id,
                    TestCaseAttemptRecord.attempt,
                    TestCaseAttemptRecord.status,
                )
                .where(
                    TestCaseAttemptRecord.test_case_execution_id
                    == any_(bindparam("case_ids", case_ids, type_=ARRAY(Uuid)))
                )
                .order_by(TestCaseAttemptRecord.attempt)
            )
            for case_id, number, status in attempt_rows:
                attempts[case_id].append((number, ExecutionStatus(status)))
        result: dict[str, list[HistoryObservation]] = {key: [] for key in keys}
        for row in rows:
            observed = attempts[row["case_id"]] or [
                (row["attempt"], ExecutionStatus(row["status"]))
            ]
            result[row["stable_test_key"]].append(
                HistoryObservation(
                    run_id=row["run_id"],
                    case_id=row["case_id"],
                    created_at=row["created_at"],
                    pipeline_key=json.dumps([row["provider"], row["pipeline_id"]]),
                    ci_series_key=execution_series(
                        row["provider"],
                        row["pipeline_id"],
                        row["job_id"],
                        row["job_name"],
                        row["external_run_id"],
                    ),
                    initial_status=observed[0][1] if observed[0][0] == 1 else None,
                    final_status=ExecutionStatus(row["status"]),
                    attempt_numbers=tuple(number for number, status in observed),
                    attempt_statuses=tuple(status for number, status in observed),
                )
            )
        return {
            key: tuple(sorted(items, key=lambda item: (item.created_at, item.run_id)))
            for key, items in result.items()
        }


def policy_key(policy: ScoringPolicy) -> str:
    return hashlib.sha256(json.dumps(policy.model_dump(), sort_keys=True).encode()).hexdigest()


def history_statement(reference: TestRun, keys: list[str], window: int) -> Select[Any]:
    """Construct per-key index-friendly bounded SQL; also used for query-plan verification."""
    key_table = (
        func.unnest(bindparam("test_keys", keys, type_=ARRAY(String)))
        .table_valued("test_key")
        .render_derived()
        .alias("keys")
    )
    run, suite, case, env = (
        TestRunRecord,
        TestSuiteRecord,
        TestCaseExecutionRecord,
        EnvironmentContextRecord,
    )
    dimensions = []
    for name in ("environment", "platform", "browser", "device"):
        value = getattr(reference.environment, name)
        column = getattr(env, name)
        dimensions.append(column.is_(None) if value is None else column == value)
    history = (
        select(
            run.id.label("run_id"),
            case.id.label("case_id"),
            case.stable_test_key,
            run.created_at,
            run.provider,
            run.pipeline_id,
            run.job_id,
            run.job_name,
            run.external_run_id,
            case.status,
            case.attempt,
            func.count().over(partition_by=(run.id, case.stable_test_key)).label("identity_count"),
        )
        .select_from(case)
        .join(suite, suite.id == case.test_suite_id)
        .join(run, run.id == suite.test_run_id)
        .join(env, env.test_run_id == run.id)
        .where(
            case.stable_test_key == key_table.c.test_key,
            run.repository == reference.repository,
            run.created_at <= reference.created_at,
            run.started_at <= reference.started_at,
            cast(env.test_configuration, JSONB) == reference.environment.test_configuration,
            *dimensions,
        )
        .order_by(run.created_at.desc(), run.id.desc(), case.id)
        .limit(window)
        .lateral("history")
    )
    return select(history).select_from(key_table.join(history, true()))
