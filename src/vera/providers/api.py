"""Safe HTTP behavior shared by optional provider API clients."""

import asyncio
from typing import Any
from urllib.parse import urlsplit

import httpx

from vera.domain.exceptions import (
    ProviderApiError,
    ProviderAuthenticationError,
    ProviderNotFoundError,
    ProviderRateLimitError,
)


class ProviderApiClient:
    """Issue bounded, sanitized, retry-aware provider GET requests."""

    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed_url = urlsplit(base_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise ValueError("provider API URLs must use HTTPS")
        timeout = httpx.Timeout(timeout_seconds)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=False,
        )

    async def close(self) -> None:
        """Close the internally managed HTTP connection pool."""

        if self._owns_client:
            await self._client.aclose()

    async def get_json(self, path: str) -> dict[str, Any]:
        """Return one JSON object, retrying a transient GET at most once."""

        for attempt in range(2):
            try:
                response = await self._client.get(path)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 0:
                    continue
                raise ProviderApiError("Provider API request failed or timed out") from exc
            if response.status_code in {401, 403}:
                raise ProviderAuthenticationError(
                    f"Provider API rejected credentials with status {response.status_code}"
                )
            if response.status_code == 404:
                raise ProviderNotFoundError("Provider API resource was not found")
            if response.status_code == 429:
                if attempt == 0:
                    await asyncio.sleep(_retry_delay(response))
                    continue
                raise ProviderRateLimitError("Provider API rate limit prevented enrichment")
            if response.status_code >= 500:
                if attempt == 0:
                    continue
                raise ProviderApiError("Provider API is temporarily unavailable")
            if response.is_error:
                raise ProviderApiError(
                    f"Provider API returned unexpected status {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderApiError("Provider API returned invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ProviderApiError("Provider API returned an unexpected response shape")
            return payload
        raise AssertionError("provider request retry loop exhausted")


def _retry_delay(response: httpx.Response) -> float:
    value = response.headers.get("Retry-After", "0")
    try:
        return min(max(float(value), 0.0), 2.0)
    except ValueError:
        return 0.0
