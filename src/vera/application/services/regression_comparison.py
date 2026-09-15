"""Application orchestration for deterministic persisted comparisons."""

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from vera.application.services.baseline_selection import BaselineSelectionService
from vera.application.services.flaky_analysis import FlakyTestAnalysisService
from vera.domain.comparison import compare_test_runs
from vera.domain.enums import FindingClassification
from vera.domain.exceptions import (
    AmbiguousTestIdentityError,
    ComparisonNotFoundError,
)
from vera.domain.failures import FINGERPRINT_VERSION, normalize_failure
from vera.domain.models import (
    BaselineSelection,
    ComparisonResult,
    RegressionComparison,
    TestComparisonFinding,
)
from vera.domain.models.stability import ScoringPolicy
from vera.persistence.models import FailureFamilyRecord
from vera.persistence.repositories import ComparisonRepository, TestRunRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FindingPage:
    """One persisted comparison with a filtered finding page."""

    comparison: RegressionComparison
    findings: list[TestComparisonFinding]
    total: int
    offset: int
    limit: int


class RegressionComparisonService:
    """Select, compare, validate, and atomically persist historical analysis."""

    def __init__(self, baseline_service: BaselineSelectionService | None = None) -> None:
        self._baseline_service = baseline_service or BaselineSelectionService()

    async def compare(
        self,
        *,
        current_run_id: UUID,
        baseline_run_id: UUID | None,
        session: AsyncSession,
    ) -> ComparisonResult:
        comparison_repository = ComparisonRepository(session)
        baseline_id: UUID | None = None
        selection: BaselineSelection | None = None
        try:
            async with session.begin():
                selected = await self._baseline_service.select(
                    current_run_id=current_run_id,
                    explicit_baseline_id=baseline_run_id,
                    repository=TestRunRepository(session),
                )
                selection = selected.selection
                if selected.baseline is None:
                    logger.info(
                        "No baseline selected current_run_id=%s reason=%s",
                        current_run_id,
                        selection.reason,
                    )
                    return ComparisonResult(selection=selection)
                if selection.strategy is None:
                    raise AssertionError("selected baseline must include a strategy")
                baseline_id = selected.baseline.id
                logger.info(
                    "Baseline selected current_run_id=%s baseline_run_id=%s reason=%s",
                    current_run_id,
                    baseline_id,
                    selection.reason,
                )
                existing = await comparison_repository.find_pair(current_run_id, baseline_id)
                if existing is not None:
                    findings = await comparison_repository.complete_findings(existing.id)
                    return ComparisonResult(
                        selection=_selection_from_comparison(existing),
                        comparison=existing,
                        findings=findings,
                        created=False,
                    )
                try:
                    comparison, findings = compare_test_runs(
                        current=selected.current,
                        baseline=selected.baseline,
                        strategy=selection.strategy,
                        reason=selection.reason,
                    )
                except AmbiguousTestIdentityError:
                    logger.warning(
                        "Ambiguous stable test identity current_run_id=%s", current_run_id
                    )
                    raise
                stored = await comparison_repository.add(comparison, findings)
                findings = await comparison_repository.complete_findings(stored.id)
            logger.info(
                "Comparison created current_run_id=%s baseline_run_id=%s new_failures=%s "
                "existing_failures=%s recovered=%s new_tests=%s missing_tests=%s",
                current_run_id,
                baseline_id,
                stored.new_failures,
                stored.existing_failures,
                stored.recovered_tests,
                stored.new_tests,
                stored.missing_tests,
            )
            return ComparisonResult(
                selection=selection,
                comparison=stored,
                findings=findings,
                created=True,
            )
        except IntegrityError:
            await session.rollback()
            if baseline_id is None:
                raise
            existing = await comparison_repository.find_pair(current_run_id, baseline_id)
            if existing is None:
                raise
            findings = await comparison_repository.complete_findings(existing.id)
            return ComparisonResult(
                selection=_selection_from_comparison(existing),
                comparison=existing,
                findings=findings,
                created=False,
            )

    async def for_run(
        self,
        *,
        run_id: UUID,
        offset: int,
        limit: int,
        classification: FindingClassification | None,
        session: AsyncSession,
    ) -> FindingPage:
        repository = ComparisonRepository(session)
        comparison = await repository.latest_for_current(run_id)
        if comparison is None:
            raise ComparisonNotFoundError(f"No comparison exists for test run {run_id}")
        return await self._page(comparison, offset, limit, classification, repository)

    async def get(
        self,
        *,
        comparison_id: UUID,
        offset: int,
        limit: int,
        classification: FindingClassification | None,
        session: AsyncSession,
    ) -> FindingPage:
        repository = ComparisonRepository(session)
        comparison = await repository.get(comparison_id)
        if comparison is None:
            raise ComparisonNotFoundError(f"Comparison {comparison_id} was not found")
        return await self._page(comparison, offset, limit, classification, repository)

    @staticmethod
    async def _page(
        comparison: RegressionComparison,
        offset: int,
        limit: int,
        classification: FindingClassification | None,
        repository: ComparisonRepository,
    ) -> FindingPage:
        findings, total = await repository.findings_page(
            comparison_id=comparison.id,
            offset=offset,
            limit=limit,
            classification=classification,
        )
        return FindingPage(
            comparison=comparison,
            findings=findings,
            total=total,
            offset=offset,
            limit=limit,
        )

    async def enrich(
        self, page: FindingPage, session: AsyncSession, policy: ScoringPolicy | None = None
    ) -> FindingPage:
        """Attach current stability without modifying canonical regression classifications."""
        reference = await TestRunRepository(session).get(page.comparison.current_run_id)
        if reference is None:
            raise ComparisonNotFoundError("Comparison current run was not found")
        analyses = await FlakyTestAnalysisService(policy).analyze(
            reference=reference, session=session, keys=[item.test_key for item in page.findings]
        )
        by_key = {item.test_key: item for item in analyses}
        family_by_case: dict[UUID, FailureFamilyRecord] = {}
        for suite in reference.suites:
            for case in suite.test_cases:
                failure = case.failure
                if failure is None:
                    continue
                normalized = normalize_failure(failure.type, failure.message, failure.stack_trace)
                family = await session.scalar(
                    select(FailureFamilyRecord).where(
                        FailureFamilyRecord.fingerprint == normalized.fingerprint,
                        FailureFamilyRecord.fingerprint_version == FINGERPRINT_VERSION,
                    )
                )
                if family is not None:
                    family_by_case[case.id] = family
        findings = []
        for item in page.findings:
            family = family_by_case.get(item.current_case_id) if item.current_case_id else None
            findings.append(
                item.model_copy(
                    update={
                        "stability": by_key[item.test_key].classification,
                        "flaky_score": by_key[item.test_key].flaky_score,
                        "stability_scoring_version": by_key[item.test_key].scoring_version,
                        "failure_fingerprint": family.fingerprint if family else None,
                        "failure_family_id": family.id if family else None,
                        "failure_recurrence": (
                            "recent_recurring"
                            if family and family.occurrence_count > 1
                            else "new_failure_pattern"
                            if family
                            else None
                        ),
                    }
                )
            )
        return FindingPage(page.comparison, findings, page.total, page.offset, page.limit)


def _selection_from_comparison(comparison: RegressionComparison) -> BaselineSelection:
    return BaselineSelection(
        current_run_id=comparison.current_run_id,
        baseline_run_id=comparison.baseline_run_id,
        strategy=comparison.baseline_strategy,
        reason=comparison.baseline_reason,
    )
