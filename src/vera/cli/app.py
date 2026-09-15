import asyncio
import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from vera import __version__
from vera.application.services import (
    FindingPage,
    IngestionResult,
    RegressionComparisonService,
    TestRunIngestionService,
)
from vera.application.services.flaky_analysis import FlakyTestAnalysisService
from vera.application.services.test_history import TestHistoryService
from vera.config import get_settings
from vera.domain.enums import FindingClassification
from vera.domain.exceptions import ReportTooLargeError, VeraError
from vera.domain.models import (
    ComparisonResult,
    DetectedCIContext,
    EnvironmentContext,
    PipelineContext,
)
from vera.domain.models.stability import TestStabilityAnalysis
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
def flaky(
    test_key: Annotated[str | None, typer.Argument(help="Stable v1 test key.")] = None,
    run_id: Annotated[
        UUID | None, typer.Option("--run", help="Reference run and environment.")
    ] = None,
    repository: str | None = typer.Option(None),
    window: int = typer.Option(50, min=1, max=100),
    json_output: bool = typer.Option(False, "--json"),
    sequence: bool = typer.Option(False, "--sequence"),
) -> None:
    """Analyze a test or every test in a run using bounded comparable history."""
    try:
        results = asyncio.run(_stability_analysis(test_key, repository, run_id, window))
    except SQLAlchemyError as exc:
        typer.echo("Stability failed: database operation failed", err=True)
        raise typer.Exit(1) from exc
    except (VeraError, ValidationError) as exc:
        typer.echo(f"Stability failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    if json_output:
        typer.echo(
            json.dumps(
                [
                    item.model_dump(mode="json", exclude=set() if sequence else {"observations"})
                    for item in results
                ]
            )
        )
    else:
        for item in results:
            stats = item.statistics
            typer.echo(
                f"Test: {item.test_key}\nHistory: {stats.total_executions} executions "
                f"({stats.independent_pipelines} independent pipelines)\n"
                f"Passed: {stats.passed_executions} Failed: {stats.failed_executions} "
                f"Errored: {stats.errored_executions} Skipped: {stats.skipped_executions}\n"
                f"Failure rate: {stats.failure_rate:.1%} Status flips: {stats.status_flip_count}\n"
                f"Retry recoveries: {stats.retry_recoveries}\n"
                f"Reliability score: {item.reliability_score}/100\n"
                f"Flaky score: {item.flaky_score}/100\n"
                f"Classification: {item.classification.value}\n"
                f"Scoring version: {item.scoring_version}\nReason: {item.reason}"
            )
            if sequence:
                typer.echo(
                    "Sequence: "
                    + ", ".join(
                        f"{obs.initial_status or 'unknown'}->{obs.final_status}"
                        for obs in item.observations
                    )
                )


@app.command()
def history(
    test_key: str,
    run_id: Annotated[UUID | None, typer.Option("--run")] = None,
    repository: str | None = typer.Option(None),
    window: int = typer.Option(50, min=1, max=100),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Show a bounded recent execution sequence for a stable test identity."""
    try:
        results = asyncio.run(_stability_analysis(test_key, repository, run_id, window))
    except SQLAlchemyError as exc:
        typer.echo("History failed: database operation failed", err=True)
        raise typer.Exit(1) from exc
    except (VeraError, ValidationError) as exc:
        typer.echo(f"History failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    result = results[0]
    if json_output:
        typer.echo(result.model_dump_json())
    else:
        typer.echo(f"Test: {test_key} History: {result.statistics.total_executions} executions")
        for item in reversed(result.observations):
            typer.echo(
                f"{item.created_at.isoformat()} {item.run_id} "
                f"initial={item.initial_status or 'unknown'} final={item.final_status} "
                f"attempts={len(item.attempt_statuses)}"
            )


async def _stability_analysis(
    test_key: str | None, repository: str | None, run_id: UUID | None, window: int
) -> list[TestStabilityAnalysis]:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            reference = await TestHistoryService().reference(
                test_key=test_key, repository=repository, run_id=run_id, session=session
            )
            return await FlakyTestAnalysisService(settings.stability_policy).analyze(
                reference=reference,
                session=session,
                window=window,
                keys=[test_key] if test_key else None,
            )
    finally:
        await database.dispose()


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
def compare(
    current_run_id: UUID,
    baseline: Annotated[
        UUID | None, typer.Option(help="Explicit historical baseline run ID.")
    ] = None,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Compare a test run with an automatic or explicit baseline."""

    try:
        result = asyncio.run(_compare_run(current_run_id, baseline))
    except SQLAlchemyError as exc:
        typer.echo(
            "Comparison failed: database operation failed; check connectivity and migrations",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except (ValidationError, VeraError) as exc:
        typer.echo(f"Comparison failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(result.model_dump_json())
    elif result.comparison is None:
        typer.echo(f"No baseline: {result.selection.reason}")
    else:
        comparison = result.comparison
        typer.echo(
            f"Current run: {comparison.current_run_id}\n"
            f"Baseline: {comparison.baseline_run_id}\n"
            f"Baseline reason: {comparison.baseline_reason}\n\n"
            f"Tests\nCurrent: {comparison.current_total}\n"
            f"Baseline: {comparison.baseline_total}\n\n"
            f"Changes\nNew failures: {comparison.new_failures}\n"
            f"Existing failures: {comparison.existing_failures}\n"
            f"Recovered: {comparison.recovered_tests}\n"
            f"New tests: {comparison.new_tests}\n"
            f"Missing tests: {comparison.missing_tests}\n"
            f"Status changes: {comparison.status_changes}"
        )
    if result.comparison is None:
        raise typer.Exit(code=2)


@app.command()
def regressions(
    run_id: UUID,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show new failures from a run's latest persisted comparison."""

    try:
        page = asyncio.run(_regressions(run_id))
    except SQLAlchemyError as exc:
        typer.echo(
            "Regression lookup failed: database operation failed; "
            "check connectivity and migrations",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except (ValidationError, VeraError) as exc:
        typer.echo(f"Regression lookup failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "comparison": page.comparison.model_dump(mode="json"),
                    "items": [finding.model_dump(mode="json") for finding in page.findings],
                    "total": page.total,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"New failures: {page.total}")
        for finding in page.findings:
            typer.echo(
                f"- {finding.test_key} regression={finding.classification.value} "
                f"stability={finding.stability or 'not_analyzed'} score={finding.flaky_score}"
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


async def _compare_run(current_run_id: UUID, baseline_run_id: UUID | None) -> ComparisonResult:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            return await RegressionComparisonService().compare(
                current_run_id=current_run_id,
                baseline_run_id=baseline_run_id,
                session=session,
            )
    finally:
        await database.dispose()


async def _regressions(run_id: UUID) -> FindingPage:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            service = RegressionComparisonService()
            page = await service.for_run(
                run_id=run_id,
                offset=0,
                limit=500,
                classification=FindingClassification.NEW_FAILURE,
                session=session,
            )
            return await service.enrich(page, session, settings.stability_policy)
    finally:
        await database.dispose()


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
