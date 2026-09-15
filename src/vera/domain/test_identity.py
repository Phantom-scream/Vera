"""Versioned stable identity for matching logical tests across runs."""

import hashlib
import json

STABLE_TEST_KEY_VERSION = "v1"


def stable_test_key(
    *,
    suite_name: str,
    suite_package: str | None,
    classname: str | None,
    test_name: str,
    file: str | None,
) -> str:
    """Build a compact key while preserving parameterized test names."""

    normalized_classname = _normalize(classname)
    normalized_file = _normalize(file)
    suite_fallback = None
    if normalized_classname is None and normalized_file is None:
        suite_fallback = [_normalize(suite_package), _normalize(suite_name)]
    canonical = json.dumps(
        {
            "classname": normalized_classname,
            "file": normalized_file,
            "name": test_name.strip() or None,
            "suite": suite_fallback,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{STABLE_TEST_KEY_VERSION}:{digest}"


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
