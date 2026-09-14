"""Optional GitHub metadata enrichment isolated from environment detection."""

from typing import Any
from urllib.parse import quote

import httpx

from vera.domain.exceptions import ProviderApiError
from vera.domain.models import DetectedCIContext
from vera.providers.api import ProviderApiClient


class GitHubApiClient:
    """Enrich normalized context through read-only GitHub REST requests."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api = ProviderApiClient(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout_seconds=timeout_seconds,
            client=client,
        )

    async def close(self) -> None:
        await self._api.close()

    async def enrich(self, context: DetectedCIContext) -> DetectedCIContext:
        repository = _repository_path(context.ci.repository)
        repository_data = await self._api.get_json(f"/repos/{repository}")
        default_branch = _string(repository_data, "default_branch") or context.git.default_branch
        commit_message = context.git.commit_message
        commit_author = context.git.commit_author
        if context.git.commit_sha:
            commit = await self._api.get_json(
                f"/repos/{repository}/commits/{quote(context.git.commit_sha, safe='')}"
            )
            nested_commit = commit.get("commit")
            if isinstance(nested_commit, dict):
                commit_message = _string(nested_commit, "message") or commit_message
                author = nested_commit.get("author")
                if isinstance(author, dict):
                    commit_author = _string(author, "name") or commit_author
        change_request = context.change_request
        if change_request is not None:
            pull = await self._api.get_json(
                f"/repos/{repository}/pulls/{quote(change_request.number_or_iid, safe='')}"
            )
            change_request = change_request.model_copy(
                update={
                    "title": _string(pull, "title") or change_request.title,
                    "url": _string(pull, "html_url") or change_request.url,
                }
            )
        return context.model_copy(
            update={
                "git": context.git.model_copy(
                    update={
                        "default_branch": default_branch,
                        "commit_message": commit_message,
                        "commit_author": commit_author,
                    }
                ),
                "change_request": change_request,
            }
        )


def _string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


def _repository_path(repository: str) -> str:
    parts = repository.split("/")
    if len(parts) != 2 or any(part in {"", ".", ".."} for part in parts):
        raise ProviderApiError("GitHub repository identity is invalid")
    return "/".join(quote(part, safe="") for part in parts)
