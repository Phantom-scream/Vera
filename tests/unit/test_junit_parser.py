from pathlib import Path

import pytest

from vera.domain.enums import ExecutionStatus
from vera.domain.exceptions import InvalidReportError
from vera.domain.models import ParsedTestReport
from vera.parsers import JUnitXmlParser

FIXTURES = Path(__file__).parents[1] / "fixtures" / "junit"


def parse_fixture(name: str) -> ParsedTestReport:
    return JUnitXmlParser().parse((FIXTURES / name).read_bytes())


def test_parses_testsuite_root_and_ignores_declared_totals() -> None:
    report = parse_fixture("simple.xml")

    assert len(report.suites) == 1
    suite = report.suites[0]
    assert suite.name == "unit"
    assert suite.package == "vera.tests"
    assert suite.total_tests == 1
    assert suite.passed_tests == 1
    assert suite.duration_seconds == pytest.approx(0.125)


def test_parses_mixed_results_and_failure_stack() -> None:
    suite = parse_fixture("mixed.xml").suites[0]

    assert [case.status for case in suite.test_cases] == [
        ExecutionStatus.PASSED,
        ExecutionStatus.FAILED,
        ExecutionStatus.SKIPPED,
    ]
    failure = suite.test_cases[1].failure
    assert failure is not None
    assert failure.type == "AssertionError"
    assert failure.message == "expected true"
    assert failure.stack_trace == "Traceback line 1\nTraceback line 2"
    assert suite.duration_seconds == 0.3
    assert (suite.total_tests, suite.passed_tests, suite.failed_tests, suite.skipped_tests) == (
        3,
        1,
        1,
        1,
    )


def test_treats_error_as_failed_aggregate_with_error_status() -> None:
    suite = parse_fixture("error.xml").suites[0]

    assert suite.test_cases[0].status is ExecutionStatus.ERROR
    assert suite.failed_tests == 1
    assert suite.test_cases[0].failure is not None


def test_parses_testsuites_root_with_multiple_suites() -> None:
    report = parse_fixture("testsuites.xml")

    assert [suite.name for suite in report.suites] == ["unit", "integration"]
    assert sum(suite.total_tests for suite in report.suites) == 2


def test_missing_optional_fields_receive_safe_defaults() -> None:
    suite = parse_fixture("missing_optional.xml").suites[0]

    assert suite.name == "unnamed-suite-1"
    assert suite.test_cases[0].name == "unnamed-test"
    assert suite.test_cases[0].duration_seconds == 0
    assert suite.test_cases[0].attempt == 1


def test_rejects_malformed_xml() -> None:
    with pytest.raises(InvalidReportError, match="Malformed or unsafe JUnit XML"):
        parse_fixture("malformed.xml")


def test_rejects_entity_expansion() -> None:
    content = b"""<!DOCTYPE testsuite [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <testsuite><testcase name="&xxe;" /></testsuite>"""

    with pytest.raises(InvalidReportError, match="Malformed or unsafe JUnit XML"):
        JUnitXmlParser().parse(content)
