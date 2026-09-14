"""Safe normalization of common JUnit XML report structures."""

import math
from datetime import datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from vera.domain.enums import ExecutionStatus
from vera.domain.exceptions import InvalidReportError
from vera.domain.models import ParsedTestReport, TestCaseExecution, TestFailure, TestSuite


class JUnitXmlParser:
    """Parse structurally compatible JUnit XML without resolving external entities."""

    def parse(self, content: bytes) -> ParsedTestReport:
        """Normalize a ``testsuite`` or ``testsuites`` document."""

        if not content.strip():
            raise InvalidReportError("JUnit report is empty")
        try:
            root = ElementTree.fromstring(content, forbid_dtd=True)
        except (ElementTree.ParseError, DefusedXmlException) as exc:
            raise InvalidReportError(f"Malformed or unsafe JUnit XML: {exc}") from exc

        root_name = _local_name(root.tag)
        if root_name not in {"testsuite", "testsuites"}:
            raise InvalidReportError("JUnit root element must be testsuite or testsuites")

        suite_elements = _executable_suites(root)
        if not suite_elements and root_name == "testsuite":
            suite_elements = [root]
        suites = tuple(
            self._parse_suite(element, index) for index, element in enumerate(suite_elements)
        )
        timestamps = [timestamp for element in suite_elements if (timestamp := _timestamp(element))]
        return ParsedTestReport(suites=suites, started_at=min(timestamps) if timestamps else None)

    def _parse_suite(self, element: Element, index: int) -> TestSuite:
        cases = tuple(
            self._parse_case(child) for child in element if _local_name(child.tag) == "testcase"
        )
        return TestSuite.from_cases(
            name=_optional_text(element.get("name")) or f"unnamed-suite-{index + 1}",
            package=_optional_text(element.get("package")),
            test_cases=cases,
        )

    def _parse_case(self, element: Element) -> TestCaseExecution:
        outcome = next(
            (
                child
                for child in element
                if _local_name(child.tag) in {"failure", "error", "skipped"}
            ),
            None,
        )
        outcome_name = _local_name(outcome.tag) if outcome is not None else None
        status = {
            "failure": ExecutionStatus.FAILED,
            "error": ExecutionStatus.ERROR,
            "skipped": ExecutionStatus.SKIPPED,
            None: ExecutionStatus.PASSED,
        }[outcome_name]
        failure = None
        if outcome_name in {"failure", "error"} and outcome is not None:
            failure = TestFailure(
                type=_optional_text(outcome.get("type")),
                message=_optional_text(outcome.get("message")),
                stack_trace=_optional_text(outcome.text),
            )

        return TestCaseExecution(
            name=_optional_text(element.get("name")) or "unnamed-test",
            classname=_optional_text(element.get("classname")),
            file=_optional_text(element.get("file")),
            duration_seconds=_duration(element.get("time")),
            status=status,
            attempt=_attempt(element.get("attempt")),
            failure=failure,
        )


def _executable_suites(root: Element) -> list[Element]:
    suites: list[Element] = []
    for element in root.iter():
        if _local_name(element.tag) != "testsuite":
            continue
        if any(_local_name(child.tag) == "testcase" for child in element):
            suites.append(element)
    return suites


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _duration(value: str | None) -> float:
    if value is None or not value.strip():
        return 0.0
    try:
        duration = float(value)
    except ValueError as exc:
        raise InvalidReportError(f"Invalid JUnit duration: {value!r}") from exc
    if duration < 0 or not math.isfinite(duration):
        raise InvalidReportError(f"Invalid JUnit duration: {value!r}")
    return duration


def _attempt(value: str | None) -> int:
    if value is None or not value.strip():
        return 1
    try:
        attempt = int(value)
    except ValueError as exc:
        raise InvalidReportError(f"Invalid JUnit attempt: {value!r}") from exc
    if attempt < 1:
        raise InvalidReportError(f"Invalid JUnit attempt: {value!r}")
    return attempt


def _timestamp(element: Element) -> datetime | None:
    value = _optional_text(element.get("timestamp"))
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidReportError(f"Invalid JUnit timestamp: {value!r}") from exc
