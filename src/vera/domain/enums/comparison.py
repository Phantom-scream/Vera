"""Regression comparison states and classifications."""

from enum import StrEnum


class BaselineStrategy(StrEnum):
    """Deterministic reason category for a selected baseline."""

    EXPLICIT = "explicit"
    SAME_BRANCH = "same_branch"
    TARGET_BRANCH = "target_branch"
    DEFAULT_BRANCH = "default_branch"


class FindingClassification(StrEnum):
    """Mutually exclusive change classification for one stable test identity."""

    NEW_FAILURE = "new_failure"
    EXISTING_FAILURE = "existing_failure"
    RECOVERED = "recovered"
    UNCHANGED_PASS = "unchanged_pass"
    NEW_TEST = "new_test"
    MISSING_TEST = "missing_test"
    NEWLY_SKIPPED = "newly_skipped"
    UNCHANGED_SKIPPED = "unchanged_skipped"
    STATUS_CHANGED = "status_changed"
