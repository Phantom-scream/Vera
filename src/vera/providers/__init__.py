"""CI environment adapters and optional API clients."""

from vera.providers.base import CIProvider
from vera.providers.detector import CIProviderDetector, resolve_pipeline_context
from vera.providers.enrichment import enrich_ci_context
from vera.providers.github import GitHubActionsProvider
from vera.providers.gitlab import GitLabCIProvider

__all__ = [
    "CIProvider",
    "CIProviderDetector",
    "GitHubActionsProvider",
    "GitLabCIProvider",
    "enrich_ci_context",
    "resolve_pipeline_context",
]
