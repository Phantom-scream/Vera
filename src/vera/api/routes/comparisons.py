"""Regression comparison execution and retrieval endpoints."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vera.api.dependencies import get_database_session
from vera.application.services import FindingPage, RegressionComparisonService
from vera.domain.enums import FindingClassification
from vera.domain.models import (
    BaselineSelection,
    RegressionComparison,
    TestComparisonFinding,
)

router = APIRouter(tags=["comparisons"])
service = RegressionComparisonService()
SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


class CompareRequest(BaseModel):
    """Optional explicit baseline override."""

    baseline_run_id: UUID | None = None


class ComparisonExecutionResponse(BaseModel):
    """Comparison execution result including structured no-baseline state."""

    status: Literal["compared", "no_baseline"]
    created: bool
    selection: BaselineSelection
    comparison: RegressionComparison | None


class FindingPageResponse(BaseModel):
    """Persisted comparison summary and paginated findings."""

    comparison: RegressionComparison
    baseline_selection: BaselineSelection
    items: list[TestComparisonFinding]
    total: int
    offset: int
    limit: int


@router.post("/test-runs/{run_id}/compare", response_model=ComparisonExecutionResponse)
async def compare_test_run(
    run_id: UUID,
    session: SessionDependency,
    request: Annotated[CompareRequest | None, Body(examples=[{"baseline_run_id": None}])] = None,
) -> ComparisonExecutionResponse:
    """Select a baseline and idempotently persist a deterministic comparison."""

    result = await service.compare(
        current_run_id=run_id,
        baseline_run_id=request.baseline_run_id if request else None,
        session=session,
    )
    return ComparisonExecutionResponse(
        status="compared" if result.comparison else "no_baseline",
        created=result.created,
        selection=result.selection,
        comparison=result.comparison,
    )


@router.get("/test-runs/{run_id}/comparison", response_model=FindingPageResponse)
async def get_run_comparison(
    run_id: UUID,
    session: SessionDependency,
    request: Request,
    include_stability: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    classification: FindingClassification | None = None,
) -> FindingPageResponse:
    """Return the latest comparison for a run with filtered findings."""

    page = await service.for_run(
        run_id=run_id,
        offset=offset,
        limit=limit,
        classification=classification,
        session=session,
    )
    if include_stability:
        page = await service.enrich(page, session, request.app.state.settings.stability_policy)
    return _page_response(page)


@router.get("/comparisons/{comparison_id}", response_model=FindingPageResponse)
async def get_comparison(
    comparison_id: UUID,
    session: SessionDependency,
    request: Request,
    include_stability: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    classification: FindingClassification | None = None,
) -> FindingPageResponse:
    """Return a comparison by ID with filtered, paginated findings."""

    page = await service.get(
        comparison_id=comparison_id,
        offset=offset,
        limit=limit,
        classification=classification,
        session=session,
    )
    if include_stability:
        page = await service.enrich(page, session, request.app.state.settings.stability_policy)
    return _page_response(page)


def _page_response(page: FindingPage) -> FindingPageResponse:
    comparison = page.comparison
    return FindingPageResponse(
        comparison=comparison,
        baseline_selection=BaselineSelection(
            current_run_id=comparison.current_run_id,
            baseline_run_id=comparison.baseline_run_id,
            strategy=comparison.baseline_strategy,
            reason=comparison.baseline_reason,
        ),
        items=page.findings,
        total=page.total,
        offset=page.offset,
        limit=page.limit,
    )
