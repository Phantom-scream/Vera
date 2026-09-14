"""Strong-signal CI provider detection and explicit metadata precedence."""

import logging
import os
from collections.abc import Mapping
from typing import Any

from vera.domain.exceptions import CIContextError
from vera.domain.models import DetectedCIContext, PipelineContext
from vera.providers.github import GitHubActionsProvider
from vera.providers.gitlab import GitLabCIProvider

logger = logging.getLogger(__name__)
SUPPORTED_PROVIDERS = {"github", "gitlab", "local"}


class CIProviderDetector:
    """Select a provider only from authoritative markers or a manual override."""

    def detect(
        self,
        environment: Mapping[str, str] | None = None,
        override: str | None = None,
    ) -> DetectedCIContext | None:
        values = environment if environment is not None else os.environ
        normalized_override = override.strip().lower() if override else None
        if normalized_override is not None and normalized_override not in SUPPORTED_PROVIDERS:
            raise CIContextError(f"Unsupported CI provider override: {override}")
        if normalized_override == "local":
            logger.info("CI provider detection selected local mode by override")
            return None

        github = values.get("GITHUB_ACTIONS", "").lower() == "true"
        gitlab = values.get("GITLAB_CI", "").lower() == "true"
        if normalized_override is None and github and gitlab:
            raise CIContextError("Conflicting GitHub Actions and GitLab CI environments detected")
        selected = normalized_override or ("github" if github else "gitlab" if gitlab else None)
        if selected is None:
            logger.info("No supported CI provider detected; using local/manual mode")
            return None

        adapter = GitHubActionsProvider() if selected == "github" else GitLabCIProvider()
        context = adapter.read_context(values)
        logger.info(
            "Detected CI provider=%s repository=%s pipeline_id=%s job_id=%s run_attempt=%s",
            context.ci.provider,
            context.ci.repository,
            context.ci.pipeline_id,
            context.ci.job_id,
            context.ci.run_attempt,
        )
        return context


def resolve_pipeline_context(
    detected: DetectedCIContext | None,
    *,
    external_run_id: str | None = None,
    **explicit: Any,
) -> PipelineContext:
    """Apply explicit non-null values over detected context and validate identity."""

    values: dict[str, Any] = {"external_run_id": external_run_id}
    if detected is not None:
        values.update(detected.ci.model_dump())
        values.update(detected.git.model_dump())
        values["change_request"] = detected.change_request
    for key, value in explicit.items():
        if value is None:
            continue
        previous = values.get(key)
        if (
            key in {"provider", "repository", "pipeline_id", "job_id", "run_attempt"}
            and previous is not None
            and previous != value
        ):
            logger.warning("Explicit CI metadata overrides detected field=%s", key)
        values[key] = value
    try:
        return PipelineContext.model_validate(values)
    except ValueError as exc:
        raise CIContextError(
            "CI identity is incomplete; provide provider, repository, pipeline ID, and job ID"
        ) from exc
