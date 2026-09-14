"""Optional GitLab metadata enrichment isolated from environment detection."""

from typing import Any
from urllib.parse import quote

import httpx

from vera.domain.models import DetectedCIContext
from vera.providers.api import ProviderApiClient


class GitLabApiClient:
    """Enrich normalized context through read-only GitLab REST requests."""

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
            headers={"PRIVATE-TOKEN": token},
            timeout_seconds=timeout_seconds,
            client=client,
        )

    async def close(self) -> None:
        await self._api.close()

    async def enrich(self, context: DetectedCIContext) -> DetectedCIContext:
        project = quote(context.ci.repository, safe="")
        project_data = await self._api.get_json(f"/projects/{project}")
        default_branch = _string(project_data, "default_branch") or context.git.default_branch
        commit_message = context.git.commit_message
        commit_author = context.git.commit_author
        if context.git.commit_sha:
            commit = await self._api.get_json(
                f"/projects/{project}/repository/commits/{quote(context.git.commit_sha, safe='')}"
            )
            commit_message = _string(commit, "message") or commit_message
            commit_author = _string(commit, "author_name") or commit_author
        change_request = context.change_request
        if change_request is not None:
            merge_request = await self._api.get_json(
                f"/projects/{project}/merge_requests/{quote(change_request.number_or_iid, safe='')}"
            )
            change_request = change_request.model_copy(
                update={
                    "title": _string(merge_request, "title") or change_request.title,
                    "url": _string(merge_request, "web_url") or change_request.url,
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
