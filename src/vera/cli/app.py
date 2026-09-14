import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from vera import __version__
from vera.application.services import IngestionResult, TestRunIngestionService
from vera.config import get_settings
from vera.domain.exceptions import ReportTooLargeError, VeraError
from vera.domain.models import EnvironmentContext, PipelineContext
from vera.persistence import Database

app = typer.Typer(
    name="vera",
    help="CI-native automated test reporting and regression intelligence.",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    """Print Vera's installed version and exit."""

    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    """Run Vera commands."""


@app.command()
def health() -> None:
    """Confirm that the local Vera CLI is operational."""

    typer.echo(json.dumps({"status": "ok", "version": __version__}))


@app.command()
def ingest(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    provider: str = typer.Option(..., help="CI provider name."),
    repository: str = typer.Option(..., help="Provider repository identifier."),
    pipeline_id: str = typer.Option(..., help="CI pipeline identifier."),
    job_id: str = typer.Option(..., help="CI job identifier."),
    external_run_id: str | None = typer.Option(None, help="Optional report execution ID."),
    branch: str | None = typer.Option(None),
    commit_sha: str | None = typer.Option(None),
    environment: str | None = typer.Option(None),
    application_version: str | None = typer.Option(None),
    build_number: str | None = typer.Option(None),
    platform: str | None = typer.Option(None),
    browser: str | None = typer.Option(None),
    device: str | None = typer.Option(None),
    report_format: str = typer.Option("junit", "--format", help="Input report format."),
) -> None:
    """Ingest a test report into Vera's configured PostgreSQL database."""

    try:
        settings = get_settings()
        content = _read_report_file(report, settings.max_report_size_bytes)
        result = asyncio.run(
            _ingest(
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
                ),
                environment=EnvironmentContext(
                    environment=environment,
                    application_version=application_version,
                    build_number=build_number,
                    platform=platform,
                    browser=browser,
                    device=device,
                ),
            )
        )
    except (OSError, SQLAlchemyError, ValidationError, VeraError) as exc:
        typer.echo(f"Ingestion failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    action = "Stored" if result.created else "Already stored"
    run = result.test_run
    typer.echo(
        f"{action} test run {run.id}: {run.total_tests} tests, "
        f"{run.passed_tests} passed, {run.failed_tests} failed, "
        f"{run.skipped_tests} skipped"
    )


async def _ingest(
    *,
    content: bytes,
    report_format: str,
    pipeline: PipelineContext,
    environment: EnvironmentContext,
) -> IngestionResult:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            return await TestRunIngestionService().ingest(
                content=content,
                report_format=report_format,
                pipeline=pipeline,
                environment=environment,
                session=session,
            )
    finally:
        await database.dispose()


def _read_report_file(path: Path, maximum_size: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    with path.open("rb") as report_file:
        while chunk := report_file.read(64 * 1024):
            size += len(chunk)
            if size > maximum_size:
                raise ReportTooLargeError(f"JUnit report exceeds {maximum_size} bytes")
            chunks.append(chunk)
    return b"".join(chunks)
