"""GitLab CI environment adapter."""

from collections.abc import Mapping

from vera.domain.exceptions import CIContextError
from vera.domain.models import (
    ChangeRequestContext,
    ChangeRequestKind,
    CIContext,
    DetectedCIContext,
    GitContext,
)


class GitLabCIProvider:
    """Map authoritative GitLab predefined variables into Vera models."""

    name = "gitlab"

    def read_context(self, environment: Mapping[str, str]) -> DetectedCIContext:
        repository = _required(environment, "CI_PROJECT_PATH")
        pipeline_id = _required(environment, "CI_PIPELINE_ID")
        job_id = _required(environment, "CI_JOB_ID")
        project_url = _optional(environment, "CI_PROJECT_URL")
        merge_request_iid = _optional(environment, "CI_MERGE_REQUEST_IID")
        merge_project_url = _optional(environment, "CI_MERGE_REQUEST_PROJECT_URL") or project_url
        merge_request_url = (
            f"{merge_project_url.rstrip('/')}/-/merge_requests/{merge_request_iid}"
            if merge_request_iid and merge_project_url
            else None
        )
        change_request = (
            ChangeRequestContext(
                kind=ChangeRequestKind.MERGE_REQUEST,
                number_or_iid=merge_request_iid,
                title=_optional(environment, "CI_MERGE_REQUEST_TITLE"),
                source_branch=_optional(environment, "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME"),
                target_branch=_optional(environment, "CI_MERGE_REQUEST_TARGET_BRANCH_NAME"),
                url=merge_request_url,
            )
            if merge_request_iid
            else None
        )
        return DetectedCIContext(
            ci=CIContext(
                provider=self.name,
                repository=repository,
                repository_url=project_url,
                pipeline_id=pipeline_id,
                pipeline_name=repository,
                pipeline_url=_optional(environment, "CI_PIPELINE_URL"),
                job_id=job_id,
                job_name=_optional(environment, "CI_JOB_NAME"),
                job_url=_optional(environment, "CI_JOB_URL"),
                run_number=_positive_int(environment, "CI_PIPELINE_IID"),
                trigger_source=_optional(environment, "CI_PIPELINE_SOURCE"),
                actor=_optional(environment, "GITLAB_USER_LOGIN"),
                detected_from_ci=True,
            ),
            git=GitContext(
                commit_sha=_optional(environment, "CI_COMMIT_SHA"),
                branch=_optional(environment, "CI_COMMIT_BRANCH")
                or _optional(environment, "CI_COMMIT_REF_NAME"),
                ref=_optional(environment, "CI_COMMIT_REF_NAME"),
                default_branch=_optional(environment, "CI_DEFAULT_BRANCH"),
                commit_message=_optional(environment, "CI_COMMIT_MESSAGE"),
            ),
            change_request=change_request,
        )


def _required(environment: Mapping[str, str], name: str) -> str:
    value = _optional(environment, name)
    if value is None:
        raise CIContextError(f"GitLab CI variable {name} is required")
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
        raise CIContextError(f"GitLab CI variable {name} must be a positive integer") from exc
    if result < 1:
        raise CIContextError(f"GitLab CI variable {name} must be a positive integer")
    return result
