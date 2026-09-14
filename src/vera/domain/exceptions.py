class VeraError(Exception):
    """Base class for errors safe to translate at application boundaries."""


class CIContextError(VeraError):
    """CI environment metadata is missing, contradictory, or invalid."""


class ProviderApiError(VeraError):
    """Optional provider enrichment could not be completed safely."""


class ProviderAuthenticationError(ProviderApiError):
    """A provider rejected the configured credentials."""


class ProviderNotFoundError(ProviderApiError):
    """A requested provider resource was not found."""


class ProviderRateLimitError(ProviderApiError):
    """A provider API rate limit prevented enrichment."""


class InvalidReportError(VeraError):
    """Raised when an external test report cannot be safely normalized."""


class UnsupportedReportError(VeraError):
    """Raised when no parser supports the requested report format."""


class ReportTooLargeError(VeraError):
    """Raised when an ingestion payload exceeds the configured limit."""


class TestRunNotFoundError(VeraError):
    """Raised when a requested test run does not exist."""
