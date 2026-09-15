"""Persistence operations for regression comparisons and findings."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vera.domain.enums import BaselineStrategy, ExecutionStatus, FindingClassification
from vera.domain.models import RegressionComparison, TestComparisonFinding
from vera.persistence.models import RegressionComparisonRecord, TestComparisonFindingRecord


class ComparisonRepository:
    """Store and retrieve canonical run-pair comparisons."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_pair(
        self, current_run_id: UUID, baseline_run_id: UUID
    ) -> RegressionComparison | None:
        statement = select(RegressionComparisonRecord).where(
            RegressionComparisonRecord.current_run_id == current_run_id,
            RegressionComparisonRecord.baseline_run_id == baseline_run_id,
        )
        record = (await self._session.scalars(statement)).one_or_none()
        return _to_comparison(record) if record else None

    async def latest_for_current(self, current_run_id: UUID) -> RegressionComparison | None:
        statement = (
            select(RegressionComparisonRecord)
            .where(RegressionComparisonRecord.current_run_id == current_run_id)
            .order_by(RegressionComparisonRecord.created_at.desc(), RegressionComparisonRecord.id)
            .limit(1)
        )
        record = (await self._session.scalars(statement)).one_or_none()
        return _to_comparison(record) if record else None

    async def get(self, comparison_id: UUID) -> RegressionComparison | None:
        record = await self._session.get(RegressionComparisonRecord, comparison_id)
        return _to_comparison(record) if record else None

    async def add(
        self,
        comparison: RegressionComparison,
        findings: tuple[TestComparisonFinding, ...],
    ) -> RegressionComparison:
        record = RegressionComparisonRecord(
            id=comparison.id,
            current_run_id=comparison.current_run_id,
            baseline_run_id=comparison.baseline_run_id,
            baseline_strategy=comparison.baseline_strategy.value,
            baseline_reason=comparison.baseline_reason,
            created_at=comparison.created_at,
            current_total=comparison.current_total,
            baseline_total=comparison.baseline_total,
            new_failures=comparison.new_failures,
            existing_failures=comparison.existing_failures,
            recovered_tests=comparison.recovered_tests,
            new_tests=comparison.new_tests,
            missing_tests=comparison.missing_tests,
            status_changes=comparison.status_changes,
            unchanged_tests=comparison.unchanged_tests,
            findings=[_to_finding_record(finding) for finding in findings],
        )
        self._session.add(record)
        await self._session.flush()
        return _to_comparison(record)

    async def complete_findings(self, comparison_id: UUID) -> tuple[TestComparisonFinding, ...]:
        statement = (
            select(TestComparisonFindingRecord)
            .where(TestComparisonFindingRecord.comparison_id == comparison_id)
            .order_by(TestComparisonFindingRecord.test_key)
        )
        records = (await self._session.scalars(statement)).all()
        return tuple(_to_finding(finding) for finding in records)

    async def findings_page(
        self,
        *,
        comparison_id: UUID,
        offset: int,
        limit: int,
        classification: FindingClassification | None,
    ) -> tuple[list[TestComparisonFinding], int]:
        filters = [TestComparisonFindingRecord.comparison_id == comparison_id]
        if classification is not None:
            filters.append(TestComparisonFindingRecord.classification == classification.value)
        total = await self._session.scalar(
            select(func.count()).select_from(TestComparisonFindingRecord).where(*filters)
        )
        statement = (
            select(TestComparisonFindingRecord)
            .where(*filters)
            .order_by(TestComparisonFindingRecord.test_key)
            .offset(offset)
            .limit(limit)
        )
        records = (await self._session.scalars(statement)).all()
        return [_to_finding(record) for record in records], total or 0


def _to_comparison(record: RegressionComparisonRecord) -> RegressionComparison:
    return RegressionComparison(
        id=record.id,
        current_run_id=record.current_run_id,
        baseline_run_id=record.baseline_run_id,
        baseline_strategy=BaselineStrategy(record.baseline_strategy),
        baseline_reason=record.baseline_reason,
        created_at=record.created_at,
        current_total=record.current_total,
        baseline_total=record.baseline_total,
        new_failures=record.new_failures,
        existing_failures=record.existing_failures,
        recovered_tests=record.recovered_tests,
        new_tests=record.new_tests,
        missing_tests=record.missing_tests,
        status_changes=record.status_changes,
        unchanged_tests=record.unchanged_tests,
    )


def _to_finding_record(finding: TestComparisonFinding) -> TestComparisonFindingRecord:
    return TestComparisonFindingRecord(
        id=finding.id,
        test_key=finding.test_key,
        current_case_id=finding.current_case_id,
        baseline_case_id=finding.baseline_case_id,
        baseline_status=finding.baseline_status.value if finding.baseline_status else None,
        current_status=finding.current_status.value if finding.current_status else None,
        classification=finding.classification.value,
    )


def _to_finding(record: TestComparisonFindingRecord) -> TestComparisonFinding:
    return TestComparisonFinding(
        id=record.id,
        comparison_id=record.comparison_id,
        test_key=record.test_key,
        current_case_id=record.current_case_id,
        baseline_case_id=record.baseline_case_id,
        baseline_status=ExecutionStatus(record.baseline_status) if record.baseline_status else None,
        current_status=ExecutionStatus(record.current_status) if record.current_status else None,
        classification=FindingClassification(record.classification),
    )
