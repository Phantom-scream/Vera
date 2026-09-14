"""GitHub Actions environment and event-payload adapter."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from vera.domain.exceptions import CIContextError
from vera.domain.models import (
    ChangeRequestContext,
    ChangeRequestKind,
    CIContext,
    DetectedCIContext,
    GitContext,
)

MAX_EVENT_BYTES = 1024 * 1024


class GitHubActionsProvider:
    """Map authoritative GitHub Actions variables into Vera models."""

    name = "github"

    def read_context(self, environment: Mapping[str, str]) -> DetectedCIContext:
        repository = _required(environment, "GITHUB_REPOSITORY")
        run_id = _required(environment, "GITHUB_RUN_ID")
        job = _required(environment, "GITHUB_JOB")
        server_url = _optional(environment, "GITHUB_SERVER_URL") or "https://github.com"
        run_url = f"{server_url.rstrip('/')}/{repository}/actions/runs/{run_id}"
        event = _read_event(_optional(environment, "GITHUB_EVENT_PATH"))
        change_request = _pull_request_context(event)
        head_ref = _optional(environment, "GITHUB_HEAD_REF")
        base_ref = _optional(environment, "GITHUB_BASE_REF")
        if change_request is not None:
            change_request = change_request.model_copy(
                update={
                    "source_branch": change_request.source_branch or head_ref,
                    "target_branch": change_request.target_branch or base_ref,
                }
            )
        return DetectedCIContext(
            ci=CIContext(
                provider=self.name,
                repository=repository,
                repository_url=f"{server_url.rstrip('/')}/{repository}",
                pipeline_id=run_id,
                pipeline_name=_optional(environment, "GITHUB_WORKFLOW"),
                pipeline_url=run_url,
                job_id=job,
                job_name=job,
                job_url=run_url,
                run_number=_positive_int(environment, "GITHUB_RUN_NUMBER"),
                run_attempt=_positive_int(environment, "GITHUB_RUN_ATTEMPT") or 1,
                trigger_source=_optional(environment, "GITHUB_EVENT_NAME"),
                actor=_optional(environment, "GITHUB_ACTOR"),
                detected_from_ci=True,
            ),
            git=GitContext(
                commit_sha=_optional(environment, "GITHUB_SHA"),
                branch=head_ref or _optional(environment, "GITHUB_REF_NAME"),
                ref=_optional(environment, "GITHUB_REF"),
                default_branch=base_ref,
            ),
            change_request=change_request,
        )


def _read_event(path_value: str | None) -> dict[str, Any]:
    if path_value is None:
        return {}
    path = Path(path_value)
    try:
        if path.stat().st_size > MAX_EVENT_BYTES:
            raise CIContextError(f"GitHub event payload exceeds {MAX_EVENT_BYTES} bytes")
        parsed = json.loads(path.read_bytes())
    except CIContextError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CIContextError("GitHub event payload is unreadable or invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise CIContextError("GitHub event payload must be a JSON object")
    return parsed


def _pull_request_context(event: Mapping[str, Any]) -> ChangeRequestContext | None:
    pull_request = event.get("pull_request")
    if not isinstance(pull_request, dict):
        return None
    number = event.get("number")
    if not isinstance(number, int | str) or isinstance(number, bool):
        return None
    head = pull_request.get("head")
    base = pull_request.get("base")
    return ChangeRequestContext(
        kind=ChangeRequestKind.PULL_REQUEST,
        number_or_iid=str(number),
        title=_string(pull_request.get("title")),
        source_branch=_nested_ref(head),
        target_branch=_nested_ref(base),
        url=_string(pull_request.get("html_url")),
    )


def _nested_ref(value: object) -> str | None:
    return _string(value.get("ref")) if isinstance(value, dict) else None


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required(environment: Mapping[str, str], name: str) -> str:
    value = _optional(environment, name)
    if value is None:
        raise CIContextError(f"GitHub Actions variable {name} is required")
    return value


def _optional(environment: Mapping[str, str], name: str) -> str | None:
    value = environment.get(name, "").strip()
    return value or None


def _positive_int(environment: Mapping[str, str], name: str) -> int | None:
    value = _optional(environment, name)
    if value is None:
        return None
    try:
        result = int(value)
    except ValueError as exc:
        raise CIContextError(f"GitHub Actions variable {name} must be a positive integer") from exc
    if result < 1:
        raise CIContextError(f"GitHub Actions variable {name} must be a positive integer")
    return result
