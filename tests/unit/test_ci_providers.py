import json
from collections.abc import Callable
from pathlib import Path

import pytest

from vera.domain.exceptions import CIContextError
from vera.providers import CIProviderDetector, resolve_pipeline_context


def gitlab_environment() -> dict[str, str]:
    return {
        "GITLAB_CI": "true",
        "CI": "true",
        "CI_PROJECT_PATH": "acme/backend",
        "CI_PROJECT_URL": "https://gitlab.example/acme/backend",
        "CI_PIPELINE_ID": "4001",
        "CI_PIPELINE_IID": "81",
        "CI_PIPELINE_URL": "https://gitlab.example/acme/backend/-/pipelines/4001",
        "CI_PIPELINE_SOURCE": "merge_request_event",
        "CI_JOB_ID": "9002",
        "CI_JOB_NAME": "test",
        "CI_JOB_URL": "https://gitlab.example/acme/backend/-/jobs/9002",
        "CI_COMMIT_SHA": "abc123",
        "CI_COMMIT_BRANCH": "feature/ci",
        "CI_COMMIT_REF_NAME": "feature/ci",
        "CI_DEFAULT_BRANCH": "main",
        "CI_COMMIT_MESSAGE": "Add CI support",
        "GITLAB_USER_LOGIN": "octocat",
        "CI_MERGE_REQUEST_IID": "17",
        "CI_MERGE_REQUEST_TITLE": "CI metadata",
        "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME": "feature/ci",
        "CI_MERGE_REQUEST_TARGET_BRANCH_NAME": "main",
        "CI_MERGE_REQUEST_PROJECT_URL": "https://gitlab.example/acme/backend",
    }


def github_environment(event_path: str) -> dict[str, str]:
    return {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": "acme/backend",
        "GITHUB_SERVER_URL": "https://github.example",
        "GITHUB_RUN_ID": "7001",
        "GITHUB_RUN_NUMBER": "42",
        "GITHUB_RUN_ATTEMPT": "2",
        "GITHUB_WORKFLOW": "Regression",
        "GITHUB_JOB": "tests",
        "GITHUB_SHA": "def456",
        "GITHUB_REF": "refs/pull/23/merge",
        "GITHUB_REF_NAME": "23/merge",
        "GITHUB_HEAD_REF": "feature/context",
        "GITHUB_BASE_REF": "main",
        "GITHUB_ACTOR": "hubot",
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": event_path,
    }


def test_detects_and_normalizes_gitlab_merge_request() -> None:
    context = CIProviderDetector().detect(gitlab_environment())

    assert context is not None
    assert context.ci.provider == "gitlab"
    assert context.ci.run_number == 81
    assert context.ci.run_attempt == 1
    assert context.git.default_branch == "main"
    assert context.change_request is not None
    assert context.change_request.number_or_iid == "17"
    assert context.change_request.url.endswith("/-/merge_requests/17")


def test_gitlab_branch_pipeline_has_no_change_request() -> None:
    environment = {
        key: value
        for key, value in gitlab_environment().items()
        if not key.startswith("CI_MERGE_REQUEST_")
    }
    context = CIProviderDetector().detect(environment)

    assert context is not None
    assert context.git.branch == "feature/ci"
    assert context.change_request is None


def test_detects_github_and_reads_pull_request_event(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps(
            {
                "number": 23,
                "pull_request": {
                    "title": "CI context",
                    "html_url": "https://github.example/acme/backend/pull/23",
                    "head": {"ref": "payload-head"},
                    "base": {"ref": "payload-base"},
                },
            }
        )
    )

    context = CIProviderDetector().detect(github_environment(str(event_path)))

    assert context is not None
    assert context.ci.provider == "github"
    assert context.ci.pipeline_id == "7001"
    assert context.ci.run_attempt == 2
    assert context.git.branch == "feature/context"
    assert context.change_request is not None
    assert context.change_request.title == "CI context"
    assert context.change_request.source_branch == "payload-head"


def test_github_push_without_event_payload_has_no_change_request() -> None:
    environment = github_environment("")
    environment["GITHUB_EVENT_NAME"] = "push"
    environment["GITHUB_REF"] = "refs/heads/main"
    environment["GITHUB_REF_NAME"] = "main"
    environment["GITHUB_HEAD_REF"] = ""
    environment["GITHUB_BASE_REF"] = ""

    context = CIProviderDetector().detect(environment)

    assert context is not None
    assert context.git.branch == "main"
    assert context.change_request is None


def test_local_weak_signals_and_override_behavior() -> None:
    detector = CIProviderDetector()

    assert detector.detect({"CI": "true", "GITHUB_REPOSITORY": "acme/backend"}) is None
    assert detector.detect(gitlab_environment(), override="local") is None
    forced = detector.detect(gitlab_environment(), override="gitlab")
    assert forced is not None and forced.ci.provider == "gitlab"


def test_conflicting_provider_markers_are_rejected() -> None:
    environment = gitlab_environment() | {"GITHUB_ACTIONS": "true"}
    with pytest.raises(CIContextError, match="Conflicting"):
        CIProviderDetector().detect(environment)


def test_clean_baseline_ignores_parent_ci_markers(
    monkeypatch: pytest.MonkeyPatch, clean_ci_environment: Callable[[], None]
) -> None:
    """A simulated local run remains local even when pytest starts in CI."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITLAB_CI", "true")
    clean_ci_environment()
    assert CIProviderDetector().detect() is None


def test_invalid_github_event_and_missing_identity_are_rejected(tmp_path: Path) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text("not json")
    with pytest.raises(CIContextError, match="invalid JSON"):
        CIProviderDetector().detect(github_environment(str(event_path)))

    with pytest.raises(CIContextError, match="CI_PROJECT_PATH"):
        CIProviderDetector().detect({"GITLAB_CI": "true"})


def test_explicit_metadata_precedence_and_retry_identity() -> None:
    detected = CIProviderDetector().detect(gitlab_environment())
    assert detected is not None

    pipeline = resolve_pipeline_context(
        detected,
        repository="custom/backend",
        branch="manual",
        run_attempt=3,
    )

    assert pipeline.repository == "custom/backend"
    assert pipeline.branch == "manual"
    assert pipeline.run_attempt == 3
    assert pipeline.resolved_external_run_id() == "4001:9002"


def test_manual_context_requires_complete_identity() -> None:
    with pytest.raises(CIContextError, match="identity is incomplete"):
        resolve_pipeline_context(None, provider="local")

    with pytest.raises(CIContextError):
        resolve_pipeline_context(
            None,
            provider="local",
            repository="repo",
            pipeline_id="pipeline",
            job_id="job",
            run_attempt=0,
        )
