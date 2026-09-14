"""Shared configuration for immutable domain values."""

from pydantic import BaseModel, ConfigDict


class DomainModel(BaseModel):
    """Immutable base for validated domain values."""

    model_config = ConfigDict(frozen=True)
