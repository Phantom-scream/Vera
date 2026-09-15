"""Normalized SQLAlchemy persistence models."""

from vera.persistence.models.comparison import (
    RegressionComparisonRecord,
    TestComparisonFindingRecord,
)
from vera.persistence.models.test_run import (
    EnvironmentContextRecord,
    TestCaseExecutionRecord,
    TestFailureRecord,
    TestRunRecord,
    TestSuiteRecord,
)

__all__ = [
    "EnvironmentContextRecord",
    "RegressionComparisonRecord",
    "TestCaseExecutionRecord",
    "TestComparisonFindingRecord",
    "TestFailureRecord",
    "TestRunRecord",
    "TestSuiteRecord",
]
