from fastapi import APIRouter
from pydantic import BaseModel

from vera import __version__

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Public service liveness response."""

    status: str
    version: str


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Report process liveness without depending on external services."""

    return HealthResponse(status="ok", version=__version__)
