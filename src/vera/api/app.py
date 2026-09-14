"""FastAPI application bootstrap."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from vera import __version__
from vera.api.routes.health import router as health_router
from vera.api.routes.test_runs import router as test_runs_router
from vera.config import Settings, get_settings
from vera.domain.exceptions import (
    InvalidReportError,
    ReportTooLargeError,
    TestRunNotFoundError,
    UnsupportedReportError,
    VeraError,
)
from vera.observability import configure_logging
from vera.persistence import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an isolated application instance with owned resources."""

    runtime_settings = settings or get_settings()
    configure_logging(runtime_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(runtime_settings.database_url)
        app.state.database = database
        yield
        await database.dispose()

    app = FastAPI(
        title=runtime_settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = runtime_settings
    app.include_router(health_router, prefix="/api/v1")
    app.include_router(test_runs_router, prefix="/api/v1")

    @app.exception_handler(TestRunNotFoundError)
    async def handle_not_found(_request: Request, exc: TestRunNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ReportTooLargeError)
    async def handle_too_large(_request: Request, exc: ReportTooLargeError) -> JSONResponse:
        return JSONResponse(status_code=413, content={"detail": str(exc)})

    @app.exception_handler(UnsupportedReportError)
    async def handle_unsupported(_request: Request, exc: UnsupportedReportError) -> JSONResponse:
        return JSONResponse(status_code=415, content={"detail": str(exc)})

    @app.exception_handler(InvalidReportError)
    async def handle_invalid_report(_request: Request, exc: InvalidReportError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(VeraError)
    async def handle_vera_error(_request: Request, exc: VeraError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app
