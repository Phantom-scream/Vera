from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_comparison import run

from vera.application.services.baseline_selection import BaselineSelectionService
from vera.domain.enums import BaselineStrategy
from vera.domain.exceptions import InvalidBaselineError
from vera.domain.exceptions import TestRunNotFoundError as RunNotFoundError
from vera.domain.models import ChangeRequestContext, ChangeRequestKind
from vera.persistence.repositories import TestRunRepository as RunRepository


@pytest.mark.parametrize(
    ("branch", "default_branch", "target", "has_request", "expected", "strategy"),
    [
        ("feature", "main", None, False, "feature", BaselineStrategy.SAME_BRANCH),
        (None, "main", None, False, "main", BaselineStrategy.DEFAULT_BRANCH),
        ("feature", "main", "release", True, "release", BaselineStrategy.TARGET_BRANCH),
        ("feature", "main", None, True, "main", BaselineStrategy.DEFAULT_BRANCH),
        (None, None, None, False, None, None),
        ("feature", None, None, True, None, None),
    ],
)
async def test_automatic_branch_precedence(
    branch: str | None,
    default_branch: str | None,
    target: str | None,
    has_request: bool,
    expected: str | None,
    strategy: BaselineStrategy | None,
) -> None:
    baseline = run(sequence=1)
    original = run(sequence=2)
    current = original.model_copy(
        update={
            "branch": branch,
            "git_context": original.git_context.model_copy(
                update={"default_branch": default_branch}
            ),
            "change_request": ChangeRequestContext(
                kind=ChangeRequestKind.PULL_REQUEST, number_or_iid="1", target_branch=target
            )
            if has_request
            else None,
        }
    )
    repository = AsyncMock(spec=RunRepository)
    repository.get.return_value = current
    repository.find_comparable_baseline.return_value = baseline

    selected = await BaselineSelectionService().select(
        current_run_id=current.id, explicit_baseline_id=None, repository=repository
    )

    assert selected.selection.strategy == strategy
    if expected is None:
        assert selected.baseline is None
        repository.find_comparable_baseline.assert_not_called()
    else:
        assert selected.selection.found
        repository.find_comparable_baseline.assert_awaited_once_with(current, expected)


@pytest.mark.parametrize("invalid", ["self", "repository", "created", "started", "missing"])
async def test_explicit_baseline_validation(invalid: str) -> None:
    current = run(sequence=2)
    baseline = run(sequence=1)
    if invalid == "self":
        baseline = current
    elif invalid == "repository":
        baseline = baseline.model_copy(update={"repository": "other/repo"})
    elif invalid == "created":
        baseline = baseline.model_copy(update={"created_at": current.created_at})
    elif invalid == "started":
        baseline = baseline.model_copy(
            update={"started_at": current.started_at + timedelta(days=1)}
        )
    repository = AsyncMock(spec=RunRepository)
    repository.get.side_effect = [current, None if invalid == "missing" else baseline]

    with pytest.raises(RunNotFoundError if invalid == "missing" else InvalidBaselineError):
        await BaselineSelectionService().select(
            current_run_id=current.id, explicit_baseline_id=baseline.id, repository=repository
        )


async def test_missing_current_run() -> None:
    repository = AsyncMock(spec=RunRepository)
    repository.get.return_value = None
    with pytest.raises(RunNotFoundError):
        await BaselineSelectionService().select(
            current_run_id=uuid4(), explicit_baseline_id=None, repository=repository
        )
