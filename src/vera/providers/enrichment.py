"""Best-effort orchestration for optional provider API enrichment."""

import logging
import os
from collections.abc import Mapping
from urllib.parse import urlsplit

from vera.config import Settings
from vera.domain.exceptions import ProviderApiError
from vera.domain.models import DetectedCIContext
from vera.providers.github_api import GitHubApiClient
from vera.providers.gitlab_api import GitLabApiClient

logger = logging.getLogger(__name__)


async def enrich_ci_context(
    context: DetectedCIContext,
    settings: Settings,
    environment: Mapping[str, str] | None = None,
) -> DetectedCIContext:
    """Enrich context when credentials exist, preserving valid context on failure."""

    values = environment if environment is not None else os.environ
    if context.ci.provider == "github":
        configured = settings.github_token.get_secret_value() if settings.github_token else None
        token = configured or values.get("GITHUB_TOKEN")
        if not token:
            logger.info("Provider API enrichment skipped provider=github reason=no_token")
            return context
        native_api_url = values.get("GITHUB_API_URL", "")
        github_api_url = settings.github_api_url
        if github_api_url == "https://api.github.com" and native_api_url:
            parsed_native_url = urlsplit(native_api_url)
            if parsed_native_url.scheme == "https" and parsed_native_url.netloc:
                github_api_url = native_api_url.rstrip("/")
            else:
                logger.warning("Ignoring invalid GITHUB_API_URL; expected an HTTPS URL")
        client: GitHubApiClient | GitLabApiClient = GitHubApiClient(
            token=token,
            base_url=github_api_url,
            timeout_seconds=settings.provider_api_timeout,
        )
    elif context.ci.provider == "gitlab":
        token = settings.gitlab_token.get_secret_value() if settings.gitlab_token else None
        if not token:
            logger.info("Provider API enrichment skipped provider=gitlab reason=no_token")
            return context
        client = GitLabApiClient(
            token=token,
            base_url=settings.gitlab_api_url,
            timeout_seconds=settings.provider_api_timeout,
        )
    else:
        return context

    try:
        enriched = await client.enrich(context)
    except ProviderApiError as exc:
        logger.warning(
            "Provider API enrichment unavailable provider=%s error=%s",
            context.ci.provider,
            exc,
        )
        return context
    finally:
        await client.close()
    logger.info("Provider API enrichment succeeded provider=%s", context.ci.provider)
    return enriched
