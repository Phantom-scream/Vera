"""Typed domain models and value objects."""

from vera.domain.models.ci import (
    ChangeRequestContext,
    ChangeRequestKind,
    CIContext,
    DetectedCIContext,
    GitContext,
)
from vera.domain.models.comparison import (
    BaselineSelection,
    ComparisonResult,
    RegressionComparison,
    TestComparisonFinding,
)
from vera.domain.models.test_run import (
    EnvironmentContext,
    ParsedTestReport,
    PipelineContext,
    TestCaseAttempt,
    TestCaseExecution,
    TestFailure,
    TestRun,
    TestSuite,
)

__all__ = [
    "BaselineSelection",
    "CIContext",
    "ChangeRequestContext",
    "ChangeRequestKind",
    "ComparisonResult",
    "DetectedCIContext",
    "EnvironmentContext",
    "GitContext",
    "ParsedTestReport",
    "PipelineContext",
    "RegressionComparison",
    "TestCaseAttempt",
    "TestCaseExecution",
    "TestComparisonFinding",
    "TestFailure",
    "TestRun",
    "TestSuite",
]
