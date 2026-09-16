"""Shared test isolation for host CI environments."""

from collections.abc import Callable, Iterator

import pytest

from vera.config import get_settings

GITHUB_CI_VARIABLES = (
    "GITHUB_ACTIONS",
    "GITHUB_REPOSITORY",
    "GITHUB_SERVER_URL",
    "GITHUB_API_URL",
    "GITHUB_RUN_ID",
    "GITHUB_RUN_NUMBER",
    "GITHUB_RUN_ATTEMPT",
    "GITHUB_WORKFLOW",
    "GITHUB_JOB",
    "GITHUB_SHA",
    "GITHUB_REF",
    "GITHUB_REF_NAME",
    "GITHUB_HEAD_REF",
    "GITHUB_BASE_REF",
    "GITHUB_ACTOR",
    "GITHUB_EVENT_NAME",
    "GITHUB_EVENT_PATH",
    "GITHUB_TOKEN",
)
GITLAB_CI_VARIABLES = (
    "GITLAB_CI",
    "CI",
    "CI_PROJECT_PATH",
    "CI_PROJECT_URL",
    "CI_PROJECT_ID",
    "CI_PIPELINE_ID",
    "CI_PIPELINE_IID",
    "CI_PIPELINE_URL",
    "CI_PIPELINE_SOURCE",
    "CI_JOB_ID",
    "CI_JOB_NAME",
    "CI_JOB_URL",
    "CI_COMMIT_SHA",
    "CI_COMMIT_BRANCH",
    "CI_COMMIT_REF_NAME",
    "CI_DEFAULT_BRANCH",
    "CI_COMMIT_MESSAGE",
    "GITLAB_USER_LOGIN",
    "CI_MERGE_REQUEST_IID",
    "CI_MERGE_REQUEST_TITLE",
    "CI_MERGE_REQUEST_SOURCE_BRANCH_NAME",
    "CI_MERGE_REQUEST_TARGET_BRANCH_NAME",
    "CI_MERGE_REQUEST_PROJECT_URL",
)


@pytest.fixture(autouse=True)
def clean_ci_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[], None]]:
    """Clear every provider signal Vera consumes, independent of the pytest host."""

    def clean() -> None:
        for name in GITHUB_CI_VARIABLES + GITLAB_CI_VARIABLES:
            monkeypatch.delenv(name, raising=False)
        get_settings.cache_clear()

    clean()
    yield clean
    get_settings.cache_clear()
