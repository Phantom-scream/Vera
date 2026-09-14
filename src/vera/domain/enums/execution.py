from enum import StrEnum


class ExecutionStatus(StrEnum):
    """Normalized outcome of a test or test run."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
