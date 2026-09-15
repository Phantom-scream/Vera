"""Transactional materialization and lookup of deterministic failure families."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vera.domain.failures import FINGERPRINT_VERSION, normalize_failure
from vera.persistence.models import (
    FailureFamilyRecord,
    TestCaseExecutionRecord,
    TestFailureRecord,
    TestSuiteRecord,
)


class FailureFingerprintService:
    """Resolve failure records into idempotent versioned families."""

    async def materialize_run(self, run_id: UUID, session: AsyncSession) -> None:
        statement = (
            select(TestFailureRecord)
            .join(TestFailureRecord.test_case_execution)
            .join(TestCaseExecutionRecord.test_suite)
            .where(TestSuiteRecord.test_run_id == run_id)
        )
        failures = (await session.scalars(statement)).all()
        for failure in failures:
            normalized = normalize_failure(failure.type, failure.message, failure.stack_trace)
            family = await session.scalar(
                select(FailureFamilyRecord).where(
                    FailureFamilyRecord.fingerprint == normalized.fingerprint,
                    FailureFamilyRecord.fingerprint_version == FINGERPRINT_VERSION,
                )
            )
            if family is None:
                family = FailureFamilyRecord(
                    fingerprint=normalized.fingerprint,
                    fingerprint_version=FINGERPRINT_VERSION,
                    canonical_type=normalized.type,
                    canonical_message=normalized.message,
                    first_seen_run_id=run_id,
                    last_seen_run_id=run_id,
                    occurrence_count=0,
                )
                session.add(family)
                await session.flush()
            failure.normalized_type = normalized.type
            failure.normalized_message = normalized.message
            failure.fingerprint = normalized.fingerprint
            failure.fingerprint_version = FINGERPRINT_VERSION
            failure.failure_family_id = family.id
        await session.flush()
        family_ids = {item.failure_family_id for item in failures if item.failure_family_id}
        for family_id in family_ids:
            family = await session.get(FailureFamilyRecord, family_id)
            if family is not None:
                count = await session.scalar(
                    select(func.count())
                    .select_from(TestFailureRecord)
                    .where(TestFailureRecord.failure_family_id == family.id)
                )
                family.occurrence_count = count or 0
                family.last_seen_at = datetime.now(UTC)
                family.last_seen_run_id = run_id


class FailureIntelligenceService:
    """Present run groups and historical recurrence without raw traces in summaries."""

    async def run_families(self, run_id: UUID, session: AsyncSession) -> list[dict[str, object]]:
        statement = (
            select(FailureFamilyRecord, func.count(TestFailureRecord.id).label("affected"))
            .join(TestFailureRecord, TestFailureRecord.failure_family_id == FailureFamilyRecord.id)
            .join(TestFailureRecord.test_case_execution)
            .join(TestCaseExecutionRecord.test_suite)
            .where(TestSuiteRecord.test_run_id == run_id)
            .group_by(FailureFamilyRecord.id)
            .order_by(func.count(TestFailureRecord.id).desc())
        )
        rows = await session.execute(statement)
        return [self._summary(family, int(count)) for family, count in rows]

    async def family(self, family_id: UUID, session: AsyncSession) -> dict[str, object] | None:
        family = await session.get(FailureFamilyRecord, family_id)
        return self._summary(family, family.occurrence_count) if family else None

    async def list_families(
        self, offset: int, limit: int, session: AsyncSession
    ) -> tuple[list[dict[str, object]], int]:
        total = await session.scalar(select(func.count()).select_from(FailureFamilyRecord)) or 0
        statement = (
            select(FailureFamilyRecord)
            .order_by(FailureFamilyRecord.last_seen_at.desc())
            .offset(offset)
            .limit(limit)
        )
        families = (await session.scalars(statement)).all()
        return [self._summary(item, 0) for item in families], int(total)

    @staticmethod
    def _summary(family: FailureFamilyRecord, affected: int) -> dict[str, object]:
        recurrence = (
            "new_failure_pattern" if family.occurrence_count <= affected else "recent_recurring"
        )
        return {
            "id": family.id,
            "fingerprint": family.fingerprint,
            "fingerprint_version": family.fingerprint_version,
            "canonical_type": family.canonical_type,
            "canonical_message": family.canonical_message,
            "first_seen_at": family.first_seen_at,
            "last_seen_at": family.last_seen_at,
            "occurrence_count": family.occurrence_count,
            "affected_test_count": affected,
            "recurrence": recurrence,
        }
