from vera.domain.failures import FINGERPRINT_VERSION, normalize_failure


def test_dynamic_uuid_timestamp_request_and_port_do_not_split_family() -> None:
    first = normalize_failure(
        "DatabaseTimeout",
        "request_id=abcde12345 at 2026-09-15 10:02:03 port=51001 "
        "id 8ca1ca9e-15b5-4e11-9cb3-9e0488089b2d",
        'File "/tmp/job-a/test.py", line 42',
    )
    second = normalize_failure(
        "DatabaseTimeout",
        "request_id=zxywv99999 at 2027-03-01 12:00:01 port=53002 "
        "id 9ca1ca9e-15b5-4e11-9cb3-9e0488089b2d",
        'File "/tmp/job-b/test.py", line 99',
    )
    assert first.fingerprint == second.fingerprint
    assert first.version == FINGERPRINT_VERSION


def test_type_and_meaningful_assertion_values_remain_distinct() -> None:
    expected = normalize_failure("AssertionError", "expected 200 got 500", None)
    actual = normalize_failure("AssertionError", "expected 200 got 401", None)
    different_type = normalize_failure("ValueError", "expected 200 got 500", None)
    assert expected.fingerprint != actual.fingerprint
    assert expected.fingerprint != different_type.fingerprint
