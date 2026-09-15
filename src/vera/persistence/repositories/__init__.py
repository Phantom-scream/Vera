"""Persistence operations supporting application use cases."""

from vera.persistence.repositories.comparisons import ComparisonRepository
from vera.persistence.repositories.test_runs import TestRunRepository

__all__ = ["ComparisonRepository", "TestRunRepository"]
