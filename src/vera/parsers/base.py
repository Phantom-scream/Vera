from typing import Protocol

from vera.domain.models import ParsedTestReport


class TestResultParser(Protocol):
    """Normalize one supported test-report representation."""

    def parse(self, content: bytes) -> ParsedTestReport:
        """Parse raw report bytes into an infrastructure-independent report."""
        ...
