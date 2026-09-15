import asyncio
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vera.application.services import RegressionComparisonService
from vera.application.services import TestRunIngestionService as IngestionService
from vera.domain.enums import BaselineStrategy
from vera.domain.exceptions import AmbiguousTestIdentityError, InvalidBaselineError
from vera.domain.models import (
    ChangeRequestContext,
    ChangeRequestKind,
    ComparisonResult,
    EnvironmentContext,
    PipelineContext,
    RegressionComparison,
)
from vera.domain.models import (
    TestComparisonFinding as Finding,
)
from vera.domain.models import (
    TestRun as Run,
)
from vera.persistence import Database
from vera.persistence.models import RegressionComparisonRecord
from vera.persistence.models import TestComparisonFindingRecord as FindingRecord
from vera.persistence.repositories import ComparisonRepository

pytestmark = pytest.mark.integration
FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


async def ingest(
    session: AsyncSession,
    *,
    sequence: int,
    branch: str = "main",
    environment: str = "staging",
    provider: str = "local",
    change_request: ChangeRequestContext | None = None,
    pipeline_id: str | None = None,
) -> Run:
    filename = "regression_baseline.xml" if sequence == 1 else "regression_current.xml"
    result = await IngestionService().ingest(
        content=(FIXTURES / filename).read_bytes(),
        report_format="junit",
        pipeline=PipelineContext(
            provider=provider,
            repository="acme/backend",
            branch=branch,
            pipeline_id=pipeline_id or str(sequence),
            job_id=f"test-{sequence}",
            default_branch="main",
            change_request=change_request,
        ),
        environment=EnvironmentContext(environment=environment),
        session=session,
    )
    return result.test_run


async def test_comparison_persists_categories_and_is_idempotent(
    database_session: AsyncSession,
) -> None:
    baseline = await ingest(database_session, sequence=1)
    current = await ingest(database_session, sequence=2)
    service = RegressionComparisonService()

    first = await service.compare(
        current_run_id=current.id, baseline_run_id=None, session=database_session
    )
    repeated = await service.compare(
        current_run_id=current.id, baseline_run_id=None, session=database_session
    )

    assert first.comparison is not None
    assert first.selection.baseline_run_id == baseline.id
    assert first.comparison.new_failures == 1
    assert first.comparison.existing_failures == 1
    assert first.comparison.recovered_tests == 1
    assert first.comparison.new_tests == 1
    assert first.comparison.missing_tests == 1
    assert first.comparison.status_changes == 1
    assert repeated.comparison == first.comparison
    assert repeated.findings == first.findings
    assert repeated.created is False
    assert (
        await database_session.scalar(select(func.count()).select_from(RegressionComparisonRecord))
        == 1
    )


@pytest.mark.parametrize(
    ("provider", "kind"),
    [("github", ChangeRequestKind.PULL_REQUEST), ("gitlab", ChangeRequestKind.MERGE_REQUEST)],
)
async def test_change_request_selects_target_branch(
    database_session: AsyncSession,
    provider: str,
    kind: ChangeRequestKind,
) -> None:
    baseline = await ingest(database_session, sequence=1, provider=provider)
    current = await ingest(
        database_session,
        sequence=2,
        provider=provider,
        branch="feature",
        change_request=ChangeRequestContext(
            kind=kind,
            number_or_iid="23",
            source_branch="feature",
            target_branch="main",
        ),
    )

    result = await RegressionComparisonService().compare(
        current_run_id=current.id, baseline_run_id=None, session=database_session
    )

    assert result.selection.baseline_run_id == baseline.id
    assert result.selection.strategy is BaselineStrategy.TARGET_BRANCH


async def test_no_baseline_environment_mismatch_and_explicit_override(
    database_session: AsyncSession,
) -> None:
    baseline = await ingest(database_session, sequence=1)
    service = RegressionComparisonService()
    first = await service.compare(
        current_run_id=baseline.id, baseline_run_id=None, session=database_session
    )
    current = await ingest(database_session, sequence=2, environment="production")
    automatic = await service.compare(
        current_run_id=current.id, baseline_run_id=None, session=database_session
    )
    explicit = await service.compare(
        current_run_id=current.id, baseline_run_id=baseline.id, session=database_session
    )

    assert first.comparison is None
    assert automatic.comparison is None
    assert explicit.selection.strategy is BaselineStrategy.EXPLICIT
    assert explicit.comparison is not None


async def test_current_pipeline_is_excluded_and_future_explicit_baseline_is_rejected(
    database_session: AsyncSession,
) -> None:
    baseline = await ingest(database_session, sequence=1, pipeline_id="same-pipeline")
    current = await ingest(database_session, sequence=2, pipeline_id="same-pipeline")
    service = RegressionComparisonService()
    result = await service.compare(
        current_run_id=current.id, baseline_run_id=None, session=database_session
    )
    assert result.comparison is None

    with pytest.raises(InvalidBaselineError, match="must be older"):
        await service.compare(
            current_run_id=baseline.id, baseline_run_id=current.id, session=database_session
        )


async def test_ambiguous_comparison_leaves_no_partial_analysis(
    database_session: AsyncSession,
) -> None:
    await ingest(database_session, sequence=1)
    content = (
        b'<testsuite name="duplicate"><testcase name="same"/><testcase name="same"/></testsuite>'
    )
    result = await IngestionService().ingest(
        content=content,
        report_format="junit",
        pipeline=PipelineContext(
            provider="local",
            repository="acme/backend",
            branch="main",
            pipeline_id="2",
            job_id="tests",
        ),
        environment=EnvironmentContext(environment="staging"),
        session=database_session,
    )
    with pytest.raises(AmbiguousTestIdentityError):
        await RegressionComparisonService().compare(
            current_run_id=result.test_run.id, baseline_run_id=None, session=database_session
        )
    assert (
        await database_session.scalar(select(func.count()).select_from(RegressionComparisonRecord))
        == 0
    )
    assert await database_session.scalar(select(func.count()).select_from(FindingRecord)) == 0


async def test_concurrent_comparison_creates_one_canonical_pair(
    database_session: AsyncSession, migrated_database_url: str
) -> None:
    baseline = await ingest(database_session, sequence=1)
    current = await ingest(database_session, sequence=2)
    database = Database(migrated_database_url)

    async def compare() -> ComparisonResult:
        async with database.session_factory() as session:
            return await RegressionComparisonService().compare(
                current_run_id=current.id, baseline_run_id=baseline.id, session=session
            )

    try:
        first, second = await asyncio.gather(compare(), compare())
        assert first.comparison is not None and second.comparison is not None
        assert first.comparison.id == second.comparison.id
        assert sum([first.created, second.created]) == 1
    finally:
        await database.dispose()


async def test_failure_after_flush_rolls_back_summary_and_findings(
    database_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    baseline = await ingest(database_session, sequence=1)
    current = await ingest(database_session, sequence=2)
    original_add = ComparisonRepository.add

    async def fail_after_flush(
        repository: ComparisonRepository,
        summary: RegressionComparison,
        findings: tuple[Finding, ...],
    ) -> RegressionComparison:
        await original_add(repository, summary, findings)
        raise RuntimeError("simulated failure after database flush")

    monkeypatch.setattr(ComparisonRepository, "add", fail_after_flush)
    with pytest.raises(RuntimeError, match="after database flush"):
        await RegressionComparisonService().compare(
            current_run_id=current.id, baseline_run_id=baseline.id, session=database_session
        )
    assert (
        await database_session.scalar(select(func.count()).select_from(RegressionComparisonRecord))
        == 0
    )
    assert await database_session.scalar(select(func.count()).select_from(FindingRecord)) == 0


async def test_pipeline_exclusion_is_provider_scoped(database_session: AsyncSession) -> None:
    baseline = await ingest(database_session, sequence=1, provider="gitlab", pipeline_id="same-id")
    current = await ingest(database_session, sequence=2, provider="github", pipeline_id="same-id")
    selected = await RegressionComparisonService().compare(
        current_run_id=current.id, baseline_run_id=None, session=database_session
    )
    assert selected.selection.baseline_run_id == baseline.id
