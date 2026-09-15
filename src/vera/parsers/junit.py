"""Safe normalization of common JUnit XML report structures."""

import math
from datetime import datetime
from xml.etree.ElementTree import Element

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from vera.domain.enums import ExecutionStatus
from vera.domain.exceptions import InvalidReportError
from vera.domain.models import (
    ParsedTestReport,
    TestCaseAttempt,
    TestCaseExecution,
    TestFailure,
    TestSuite,
)
from vera.domain.test_identity import stable_test_key


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
        name = _optional_text(element.get("name")) or f"unnamed-suite-{index + 1}"
        package = _optional_text(element.get("package"))
        cases = [
            self._parse_case(child) for child in element if _local_name(child.tag) == "testcase"
        ]
        grouped: dict[str, list[TestCaseExecution]] = {}
        for case in cases:
            key = stable_test_key(
                suite_name=name,
                suite_package=package,
                classname=case.classname,
                test_name=case.name,
                file=case.file,
            )
            grouped.setdefault(key, []).append(case)
        normalized: list[TestCaseExecution] = []
        for group in grouped.values():
            if len(group) == 1 or all(case.attempt == 1 for case in group):
                normalized.extend(group)
                continue
            ordered = sorted(group, key=lambda case: case.attempt)
            numbers = [case.attempt for case in ordered]
            if (
                numbers != list(range(1, len(group) + 1))
                or len(group) > 100
                or any(len(case.attempts) != 1 for case in group)
            ):
                raise InvalidReportError(
                    "Repeated testcase retries require unique contiguous attempts starting at 1"
                )
            attempts = tuple(case.attempts[0] for case in ordered)
            normalized.append(
                ordered[-1].model_copy(
                    update={
                        "attempts": attempts,
                        "duration_seconds": round(
                            math.fsum(item.duration_seconds for item in attempts), 9
                        ),
                    }
                )
            )
        return TestSuite.from_cases(
            name=name,
            package=package,
            test_cases=tuple(normalized),
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

        attempts = [
            TestCaseAttempt(
                attempt=_attempt(element.get("attempt")),
                status=status,
                duration_seconds=_duration(element.get("time")),
                failure=failure,
            )
        ]
        flaky = [
            child for child in element if _local_name(child.tag) in {"flakyFailure", "flakyError"}
        ]
        reruns = [
            child for child in element if _local_name(child.tag) in {"rerunFailure", "rerunError"}
        ]
        if flaky or reruns:
            if (
                element.get("attempt") is not None
                or (flaky and (reruns or outcome is not None))
                or (reruns and status not in {ExecutionStatus.FAILED, ExecutionStatus.ERROR})
            ):
                raise InvalidReportError("Conflicting JUnit retry representations")
            retries = flaky or reruns
            observed = [] if flaky else attempts
            for child in retries:
                trace = next(
                    (nested.text for nested in child if _local_name(nested.tag) == "stackTrace"),
                    child.text,
                )
                observed.append(
                    TestCaseAttempt(
                        attempt=len(observed) + 1,
                        status=ExecutionStatus.ERROR
                        if _local_name(child.tag).endswith("Error")
                        else ExecutionStatus.FAILED,
                        duration_seconds=0,
                        failure=TestFailure(
                            type=_optional_text(child.get("type")),
                            message=_optional_text(child.get("message")),
                            stack_trace=_optional_text(trace),
                        ),
                    )
                )
            if flaky:
                observed.append(
                    TestCaseAttempt(
                        attempt=len(observed) + 1,
                        status=ExecutionStatus.PASSED,
                        duration_seconds=_duration(element.get("time")),
                    )
                )
            attempts = observed
            status, failure = attempts[-1].status, attempts[-1].failure
        if len(attempts) > 100:
            raise InvalidReportError("JUnit test retries exceed 100 observed attempts")
        return TestCaseExecution(
            name=_optional_text(element.get("name")) or "unnamed-test",
            classname=_optional_text(element.get("classname")),
            file=_optional_text(element.get("file")),
            duration_seconds=_duration(element.get("time")),
            status=status,
            attempt=attempts[-1].attempt,
            failure=failure,
            attempts=tuple(attempts),
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
