import httpx
import pytest

from vera.config import Settings
from vera.domain.exceptions import (
    ProviderApiError,
    ProviderAuthenticationError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)
from vera.domain.models import CIContext, DetectedCIContext, GitContext
from vera.providers.api import ProviderApiClient
from vera.providers.enrichment import enrich_ci_context
from vera.providers.github_api import GitHubApiClient
from vera.providers.gitlab_api import GitLabApiClient


def context(provider: str) -> DetectedCIContext:
    return DetectedCIContext(
        ci=CIContext(
            provider=provider,
            repository="acme/backend",
            pipeline_id="1",
            job_id="test",
            detected_from_ci=True,
        ),
        git=GitContext(commit_sha="abc123"),
    )


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (404, ProviderNotFoundError),
        (429, ProviderRateLimitError),
        (500, ProviderApiError),
    ],
)
async def test_provider_api_maps_errors_without_response_details(
    status: int, error: type[ProviderApiError]
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="secret-token response", request=request)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = ProviderApiClient(
        base_url="https://provider.example",
        headers={"Authorization": "Bearer secret-token"},
        timeout_seconds=0.1,
        client=http,
    )
    with pytest.raises(error) as raised:
        await client.get_json("/resource")

    assert "secret-token" not in str(raised.value)
    assert calls == (2 if status in {429, 500} else 1)
    await http.aclose()


async def test_provider_api_retries_timeout_then_succeeds() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"ok": True}, request=request)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://provider.example"
    )
    client = ProviderApiClient(
        base_url="https://provider.example", headers={}, timeout_seconds=0.1, client=http
    )
    assert await client.get_json("/resource") == {"ok": True}
    assert calls == 2
    await http.aclose()


async def test_github_client_enriches_repository_and_commit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits/abc123"):
            return httpx.Response(
                200,
                json={"commit": {"message": "Fix tests", "author": {"name": "Ada"}}},
                request=request,
            )
        return httpx.Response(200, json={"default_branch": "trunk"}, request=request)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.example"
    )
    client = GitHubApiClient(
        token="token", base_url="https://api.github.example", timeout_seconds=1, client=http
    )
    enriched = await client.enrich(context("github"))

    assert enriched.git.default_branch == "trunk"
    assert enriched.git.commit_message == "Fix tests"
    assert enriched.git.commit_author == "Ada"
    await http.aclose()


async def test_github_client_rejects_repository_path_injection() -> None:
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
        base_url="https://api.github.example",
    )
    client = GitHubApiClient(
        token="token", base_url="https://api.github.example", timeout_seconds=1, client=http
    )
    unsafe = context("github").model_copy(
        update={"ci": context("github").ci.model_copy(update={"repository": "../admin"})}
    )

    with pytest.raises(ProviderApiError, match="repository identity is invalid"):
        await client.enrich(unsafe)
    await http.aclose()


async def test_gitlab_client_enriches_repository_and_commit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/repository/commits/" in request.url.path:
            return httpx.Response(
                200, json={"message": "Fix tests", "author_name": "Grace"}, request=request
            )
        return httpx.Response(200, json={"default_branch": "main"}, request=request)

    http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://gitlab.example/api/v4"
    )
    client = GitLabApiClient(
        token="token",
        base_url="https://gitlab.example/api/v4",
        timeout_seconds=1,
        client=http,
    )
    enriched = await client.enrich(context("gitlab"))

    assert enriched.git.default_branch == "main"
    assert enriched.git.commit_message == "Fix tests"
    assert enriched.git.commit_author == "Grace"
    await http.aclose()


async def test_optional_enrichment_failure_preserves_detected_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def enrich(self, _context: DetectedCIContext) -> DetectedCIContext:
            raise ProviderApiError("provider unavailable")

        async def close(self) -> None:
            pass

    monkeypatch.setattr("vera.providers.enrichment.GitHubApiClient", FailingClient)
    original = context("github")
    settings = Settings(github_token="very-secret", _env_file=None)

    result = await enrich_ci_context(original, settings, {})

    assert result == original
    assert "very-secret" not in repr(settings)
