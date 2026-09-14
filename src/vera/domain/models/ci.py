"""Provider-neutral continuous-integration execution context."""

from enum import StrEnum

from pydantic import Field, field_validator

from vera.domain.models.base import DomainModel


class ChangeRequestKind(StrEnum):
    """Supported review-request categories across source-control providers."""

    PULL_REQUEST = "pull_request"
    MERGE_REQUEST = "merge_request"


class CIContext(DomainModel):
    """Normalized pipeline and job metadata independent of a CI provider."""

    provider: str = Field(min_length=1, max_length=50)
    repository: str = Field(min_length=1, max_length=500)
    repository_url: str | None = Field(default=None, max_length=2000)
    pipeline_id: str = Field(min_length=1, max_length=255)
    pipeline_name: str | None = Field(default=None, max_length=500)
    pipeline_url: str | None = Field(default=None, max_length=2000)
    job_id: str = Field(min_length=1, max_length=255)
    job_name: str | None = Field(default=None, max_length=500)
    job_url: str | None = Field(default=None, max_length=2000)
    run_number: int | None = Field(default=None, ge=1)
    run_attempt: int = Field(default=1, ge=1)
    trigger_source: str | None = Field(default=None, max_length=255)
    actor: str | None = Field(default=None, max_length=500)
    detected_from_ci: bool = False

    @field_validator("provider", mode="before")
    @classmethod
    def normalize_provider(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("repository", "pipeline_id", "job_id", mode="before")
    @classmethod
    def normalize_required(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GitContext(DomainModel):
    """Normalized source revision associated with a test execution."""

    commit_sha: str | None = Field(default=None, max_length=128)
    branch: str | None = Field(default=None, max_length=500)
    ref: str | None = Field(default=None, max_length=1000)
    default_branch: str | None = Field(default=None, max_length=500)
    commit_message: str | None = Field(default=None, max_length=10000)
    commit_author: str | None = Field(default=None, max_length=500)


class ChangeRequestContext(DomainModel):
    """Normalized pull-request or merge-request metadata."""

    kind: ChangeRequestKind
    number_or_iid: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=2000)
    source_branch: str | None = Field(default=None, max_length=500)
    target_branch: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2000)


class DetectedCIContext(DomainModel):
    """Complete normalized context produced by a CI environment adapter."""

    ci: CIContext
    git: GitContext = Field(default_factory=GitContext)
    change_request: ChangeRequestContext | None = None
