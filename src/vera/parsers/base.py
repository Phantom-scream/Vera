from typing import Protocol

from vera.domain.models import TestRun


class TestResultParser(Protocol):
    """Normalize one supported test-report representation."""

    def parse(self, content: bytes) -> TestRun:
        """Parse raw report bytes into an infrastructure-independent test run."""
        ...
