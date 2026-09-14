"""Typed domain models and value objects."""

from vera.domain.models.ci import (
    ChangeRequestContext,
    ChangeRequestKind,
    CIContext,
    DetectedCIContext,
    GitContext,
)
from vera.domain.models.test_run import (
    EnvironmentContext,
    ParsedTestReport,
    PipelineContext,
    TestCaseExecution,
    TestFailure,
    TestRun,
    TestSuite,
)

__all__ = [
    "CIContext",
    "ChangeRequestContext",
    "ChangeRequestKind",
    "DetectedCIContext",
    "EnvironmentContext",
    "GitContext",
    "ParsedTestReport",
    "PipelineContext",
    "TestCaseExecution",
    "TestFailure",
    "TestRun",
    "TestSuite",
]
