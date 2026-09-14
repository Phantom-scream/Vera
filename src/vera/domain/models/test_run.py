from dataclasses import dataclass
from datetime import datetime

from vera.domain.enums import ExecutionStatus


@dataclass(frozen=True, slots=True)
class TestCaseResult:
    """A normalized individual test result."""

    name: str
    status: ExecutionStatus
    duration_seconds: float
    suite: str | None = None


@dataclass(frozen=True, slots=True)
class TestRun:
    """A normalized test execution produced by a parser."""

    external_id: str
    started_at: datetime
    results: tuple[TestCaseResult, ...]
