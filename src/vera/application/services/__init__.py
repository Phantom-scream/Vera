"""Application services coordinating domain operations and ports."""

from vera.application.services.baseline_selection import BaselineSelectionService
from vera.application.services.regression_comparison import (
    FindingPage,
    RegressionComparisonService,
)
from vera.application.services.test_run_ingestion import (
    IngestionResult,
    TestRunIngestionService,
)

__all__ = [
    "BaselineSelectionService",
    "FindingPage",
    "IngestionResult",
    "RegressionComparisonService",
    "TestRunIngestionService",
]
