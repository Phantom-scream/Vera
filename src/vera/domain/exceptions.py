class VeraError(Exception):
    """Base class for errors safe to translate at application boundaries."""


class InvalidReportError(VeraError):
    """Raised when an external test report cannot be safely normalized."""


class UnsupportedReportError(VeraError):
    """Raised when no parser supports the requested report format."""


class ReportTooLargeError(VeraError):
    """Raised when an ingestion payload exceeds the configured limit."""


class TestRunNotFoundError(VeraError):
    """Raised when a requested test run does not exist."""
