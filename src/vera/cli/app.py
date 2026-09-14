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
from vera.domain.models import DetectedCIContext, EnvironmentContext, PipelineContext
from vera.persistence import Database
from vera.providers import CIProviderDetector, enrich_ci_context, resolve_pipeline_context

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
def context(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    ci_provider: str | None = typer.Option(None, help="Override CI detection."),
) -> None:
    """Show normalized CI metadata without displaying credentials."""

    try:
        settings = get_settings()
        detected = CIProviderDetector().detect(
            override=ci_provider or settings.ci_provider_override
        )
    except (ValidationError, VeraError) as exc:
        typer.echo(f"CI context failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        payload = (
            {"mode": "local", "context": None}
            if detected is None
            else {"mode": detected.ci.provider, "context": detected.model_dump(mode="json")}
        )
        typer.echo(json.dumps(payload, sort_keys=True))
    elif detected is None:
        typer.echo("CI context: local/manual mode (no supported CI provider detected)")
    else:
        ci = detected.ci
        typer.echo(
            f"CI context: {ci.provider} repository={ci.repository} "
            f"pipeline={ci.pipeline_id} job={ci.job_id} attempt={ci.run_attempt}"
        )


@app.command()
def ingest(
    report: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    provider: str | None = typer.Option(None, help="Explicit CI provider name."),
    repository: str | None = typer.Option(None, help="Explicit repository identifier."),
    pipeline_id: str | None = typer.Option(None, help="Explicit pipeline identifier."),
    job_id: str | None = typer.Option(None, help="Explicit job identifier."),
    ci_provider: str | None = typer.Option(None, help="Override automatic CI detection."),
    external_run_id: str | None = typer.Option(None, help="Optional report execution ID."),
    branch: str | None = typer.Option(None),
    commit_sha: str | None = typer.Option(None),
    run_attempt: int | None = typer.Option(None, min=1),
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
        detected = CIProviderDetector().detect(
            override=ci_provider or settings.ci_provider_override
        )
        result = asyncio.run(
            _prepare_and_ingest(
                content=content,
                report_format=report_format,
                detected=detected,
                external_run_id=external_run_id,
                explicit_pipeline={
                    "provider": provider,
                    "repository": repository,
                    "branch": branch,
                    "commit_sha": commit_sha,
                    "pipeline_id": pipeline_id,
                    "job_id": job_id,
                    "run_attempt": run_attempt,
                },
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


async def _prepare_and_ingest(
    *,
    content: bytes,
    report_format: str,
    detected: DetectedCIContext | None,
    external_run_id: str | None,
    explicit_pipeline: dict[str, object],
    environment: EnvironmentContext,
) -> IngestionResult:
    settings = get_settings()
    normalized = detected
    if normalized is not None:
        normalized = await enrich_ci_context(normalized, settings)
    pipeline = resolve_pipeline_context(
        normalized,
        external_run_id=external_run_id,
        **explicit_pipeline,
    )
    return await _ingest(
        content=content,
        report_format=report_format,
        pipeline=pipeline,
        environment=environment,
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
