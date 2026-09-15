"""Failure-family inspection endpoints with bounded summary responses."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from vera.api.dependencies import get_database_session
from vera.application.services.failure_intelligence import FailureIntelligenceService

router = APIRouter(tags=["failure-families"])
Session = Annotated[AsyncSession, Depends(get_database_session)]


@router.get("/test-runs/{run_id}/failure-families")
async def run_failure_families(run_id: UUID, session: Session) -> dict[str, object]:
    """Group a run's failed cases by deterministic family without stack traces."""
    items = await FailureIntelligenceService().run_families(run_id, session)
    return {
        "run_id": run_id,
        "failed_tests": sum(cast(int, item["affected_test_count"]) for item in items),
        "failure_families": len(items),
        "items": items,
    }


@router.get("/failure-families/{family_id}")
async def get_failure_family(family_id: UUID, session: Session) -> dict[str, object]:
    """Return canonical normalized evidence and recurrence summary."""
    item = await FailureIntelligenceService().family(family_id, session)
    if item is None:
        raise HTTPException(status_code=404, detail="Failure family was not found")
    return item


@router.get("/failure-families")
async def list_failure_families(
    session: Session,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, object]:
    """List families ordered by latest occurrence; raw traces are never returned."""
    items, total = await FailureIntelligenceService().list_families(offset, limit, session)
    return {"items": items, "total": total, "offset": offset, "limit": limit}
