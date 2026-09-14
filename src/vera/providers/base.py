from collections.abc import Mapping
from typing import Protocol

from vera.domain.models import DetectedCIContext


class CIProvider(Protocol):
    """Translate one provider's environment into Vera's normalized context."""

    name: str

    def read_context(self, environment: Mapping[str, str]) -> DetectedCIContext:
        """Validate and normalize authoritative CI environment variables."""
        ...
