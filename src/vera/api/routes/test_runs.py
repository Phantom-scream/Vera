"""Test-run ingestion and retrieval endpoints."""

import json
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vera.api.dependencies import get_database_session
from vera.application.services import TestRunIngestionService
from vera.config import Settings
from vera.domain.exceptions import (
    InvalidReportError,
    ReportTooLargeError,
    UnsupportedReportError,
)
from vera.domain.models import (
    ChangeRequestContext,
    ChangeRequestKind,
    EnvironmentContext,
    PipelineContext,
    TestRun,
)

router = APIRouter(prefix="/test-runs", tags=["test-runs"])
service = TestRunIngestionService()

SessionDependency = Annotated[AsyncSession, Depends(get_database_session)]


class IngestionResponse(BaseModel):
    """API representation of an ingestion result."""

    created: bool
    test_run: TestRun


class TestRunPage(BaseModel):
    """Paginated test-run response."""

    items: list[TestRun]
    total: int
    offset: int
    limit: int


@router.post("/ingest", response_model=IngestionResponse, status_code=201)
async def ingest_test_run(
    response: Response,
    request: Request,
    session: SessionDependency,
    report: Annotated[UploadFile, File(description="JUnit XML report")],
    provider: Annotated[str, Form(min_length=1, max_length=50, examples=["github"])],
    repository: Annotated[str, Form(min_length=1, max_length=500, examples=["acme/api"])],
    pipeline_id: Annotated[str, Form(min_length=1, max_length=255, examples=["123456"])],
    job_id: Annotated[str, Form(min_length=1, max_length=255, examples=["regression"])],
    external_run_id: Annotated[str | None, Form(max_length=255)] = None,
    branch: Annotated[str | None, Form(max_length=500)] = None,
    commit_sha: Annotated[str | None, Form(max_length=128)] = None,
    repository_url: Annotated[str | None, Form(max_length=2000)] = None,
    pipeline_name: Annotated[str | None, Form(max_length=500)] = None,
    pipeline_url: Annotated[str | None, Form(max_length=2000)] = None,
    job_name: Annotated[str | None, Form(max_length=500)] = None,
    job_url: Annotated[str | None, Form(max_length=2000)] = None,
    run_number: Annotated[int | None, Form(ge=1)] = None,
    run_attempt: Annotated[int, Form(ge=1, examples=[1])] = 1,
    trigger_source: Annotated[str | None, Form(max_length=255)] = None,
    actor: Annotated[str | None, Form(max_length=500)] = None,
    detected_from_ci: Annotated[bool, Form()] = False,
    git_ref: Annotated[str | None, Form(max_length=1000)] = None,
    default_branch: Annotated[str | None, Form(max_length=500)] = None,
    commit_message: Annotated[str | None, Form(max_length=10000)] = None,
    commit_author: Annotated[str | None, Form(max_length=500)] = None,
    change_request_kind: Annotated[ChangeRequestKind | None, Form()] = None,
    change_request_number: Annotated[str | None, Form(max_length=255)] = None,
    change_request_title: Annotated[str | None, Form(max_length=2000)] = None,
    change_request_source_branch: Annotated[str | None, Form(max_length=500)] = None,
    change_request_target_branch: Annotated[str | None, Form(max_length=500)] = None,
    change_request_url: Annotated[str | None, Form(max_length=2000)] = None,
    environment: Annotated[str | None, Form(max_length=100)] = None,
    application_version: Annotated[str | None, Form(max_length=255)] = None,
    build_number: Annotated[str | None, Form(max_length=255)] = None,
    platform: Annotated[str | None, Form(max_length=255)] = None,
    browser: Annotated[str | None, Form(max_length=255)] = None,
    device: Annotated[str | None, Form(max_length=255)] = None,
    test_configuration: Annotated[str | None, Form()] = None,
    report_format: Annotated[str, Form()] = "junit",
) -> IngestionResponse:
    """Safely ingest one complete automated test execution."""

    allowed_types = {"application/xml", "text/xml", "application/x-xml", "application/octet-stream"}
    content_type = (report.content_type or "").partition(";")[0].strip().lower()
    if content_type not in allowed_types:
        raise UnsupportedReportError(f"Unsupported upload content type: {report.content_type}")
    settings = cast(Settings, request.app.state.settings)
    content = await _read_report(report, settings.max_report_size_bytes)
    configuration = _parse_configuration(test_configuration)
    if (change_request_kind is None) != (change_request_number is None):
        raise InvalidReportError(
            "change_request_kind and change_request_number must be provided together"
        )
    result = await service.ingest(
        content=content,
        report_format=report_format,
        pipeline=PipelineContext(
            external_run_id=external_run_id,
            provider=provider,
            repository=repository,
            branch=branch,
            commit_sha=commit_sha,
            pipeline_id=pipeline_id,
            job_id=job_id,
            repository_url=repository_url,
            pipeline_name=pipeline_name,
            pipeline_url=pipeline_url,
            job_name=job_name,
            job_url=job_url,
            run_number=run_number,
            run_attempt=run_attempt,
            trigger_source=trigger_source,
            actor=actor,
            detected_from_ci=detected_from_ci,
            ref=git_ref,
            default_branch=default_branch,
            commit_message=commit_message,
            commit_author=commit_author,
            change_request=(
                ChangeRequestContext(
                    kind=change_request_kind,
                    number_or_iid=change_request_number,
                    title=change_request_title,
                    source_branch=change_request_source_branch,
                    target_branch=change_request_target_branch,
                    url=change_request_url,
                )
                if change_request_kind is not None and change_request_number is not None
                else None
            ),
        ),
        environment=EnvironmentContext(
            environment=environment,
            application_version=application_version,
            build_number=build_number,
            platform=platform,
            browser=browser,
            device=device,
            test_configuration=configuration,
        ),
        session=session,
    )
    response.status_code = 201 if result.created else 200
    return IngestionResponse(created=result.created, test_run=result.test_run)


@router.get("/{run_id}", response_model=TestRun)
async def get_test_run(run_id: UUID, session: SessionDependency) -> TestRun:
    """Return a stored run with suites, cases, and failures."""

    return await service.get(run_id, session)


@router.get("", response_model=TestRunPage)
async def list_test_runs(
    session: SessionDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> TestRunPage:
    """Return a basic newest-first page of stored runs."""

    items, total = await service.list(offset=offset, limit=limit, session=session)
    return TestRunPage(items=items, total=total, offset=offset, limit=limit)


async def _read_report(report: UploadFile, maximum_size: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while chunk := await report.read(64 * 1024):
        size += len(chunk)
        if size > maximum_size:
            raise ReportTooLargeError(f"JUnit report exceeds {maximum_size} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _parse_configuration(value: str | None) -> dict[str, Any]:
    if value is None:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InvalidReportError("test_configuration must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise InvalidReportError("test_configuration must be a JSON object")
    return parsed
