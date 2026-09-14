from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """Provider-neutral address of a CI artifact."""

    pipeline_id: str
    artifact_path: str


class CIProvider(Protocol):
    """Retrieve test artifacts from a CI system."""

    async def fetch_artifact(self, reference: ArtifactReference) -> bytes:
        """Fetch an artifact without exposing provider details to the domain."""
        ...
