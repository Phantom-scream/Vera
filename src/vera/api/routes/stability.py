"""Bounded history and explainable test stability endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vera.api.dependencies import get_database_session
from vera.application.services.flaky_analysis import FlakyTestAnalysisService
from vera.application.services.test_history import TestHistoryService
from vera.domain.models.stability import (
    HistoryMetrics,
    HistoryObservation,
    StabilityClass,
    TestStabilityAnalysis,
    environment_fingerprint,
)
from vera.domain.stability import history_metrics

router = APIRouter(tags=["stability"])
Session = Annotated[AsyncSession, Depends(get_database_session)]
Window = Annotated[int, Query(ge=1, le=100)]
TestKey = Annotated[str, Path(pattern=r"^v1:[0-9a-f]{64}$")]


class HistoryResponse(BaseModel):
    test_key: str
    reference_run_id: UUID
    environment_fingerprint: str
    statistics: HistoryMetrics
    items: tuple[HistoryObservation, ...]
    total: int
    offset: int
    limit: int


class StabilityPage(BaseModel):
    items: list[TestStabilityAnalysis]
    total: int
    offset: int
    limit: int


@router.get("/tests/{test_key}/history", response_model=HistoryResponse)
async def get_history(
    test_key: TestKey,
    session: Session,
    request: Request,
    repository: str | None = None,
    reference_run_id: UUID | None = None,
    window: Window = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> HistoryResponse:
    service = TestHistoryService()
    reference = await service.reference(
        test_key=test_key, repository=repository, run_id=reference_run_id, session=session
    )
    observations = (await service.histories(reference, [test_key], window, session))[test_key]
    recent_first = tuple(reversed(observations))
    return HistoryResponse(
        test_key=test_key,
        reference_run_id=reference.id,
        environment_fingerprint=environment_fingerprint(reference.environment),
        statistics=history_metrics(
            observations, request.app.state.settings.stability_policy.recent_window
        ),
        items=recent_first[offset : offset + limit],
        total=len(observations),
        offset=offset,
        limit=limit,
    )


@router.get("/tests/{test_key}/stability", response_model=TestStabilityAnalysis)
async def get_stability(
    test_key: TestKey,
    session: Session,
    request: Request,
    repository: str | None = None,
    reference_run_id: UUID | None = None,
    window: Window = 50,
    include_sequence: bool = False,
) -> TestStabilityAnalysis:
    reference = await TestHistoryService().reference(
        test_key=test_key, repository=repository, run_id=reference_run_id, session=session
    )
    result = (
        await FlakyTestAnalysisService(request.app.state.settings.stability_policy).analyze(
            reference=reference, keys=[test_key], window=window, session=session
        )
    )[0]
    return result if include_sequence else result.model_copy(update={"observations": ()})


@router.get("/test-runs/{run_id}/flaky-tests", response_model=StabilityPage)
async def get_run_stability(
    run_id: UUID,
    session: Session,
    request: Request,
    window: Window = 50,
    classification: StabilityClass | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> StabilityPage:
    reference = await TestHistoryService().reference(
        test_key=None, repository=None, run_id=run_id, session=session
    )
    results = await FlakyTestAnalysisService(request.app.state.settings.stability_policy).analyze(
        reference=reference, window=window, session=session
    )
    filtered = [
        item for item in results if classification is None or item.classification is classification
    ]
    return StabilityPage(
        items=[
            item.model_copy(update={"observations": ()})
            for item in filtered[offset : offset + limit]
        ],
        total=len(filtered),
        offset=offset,
        limit=limit,
    )
