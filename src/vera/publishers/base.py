from typing import Protocol

from vera.domain.models import TestRun


class ReportPublisher(Protocol):
    """Publish a normalized run to an external engineering system."""

    async def publish(self, run: TestRun) -> None:
        """Publish a run using an adapter-specific representation."""
        ...
