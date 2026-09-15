"""Deterministic historical baseline selection."""

from dataclasses import dataclass
from uuid import UUID

from vera.domain.enums import BaselineStrategy
from vera.domain.exceptions import InvalidBaselineError, TestRunNotFoundError
from vera.domain.models import BaselineSelection, TestRun
from vera.persistence.repositories import TestRunRepository


@dataclass(frozen=True, slots=True)
class SelectedBaseline:
    """Selection explanation plus loaded runs for comparison."""

    selection: BaselineSelection
    current: TestRun
    baseline: TestRun | None


class BaselineSelectionService:
    """Select a safe baseline through explicit or deterministic automatic rules."""

    async def select(
        self,
        *,
        current_run_id: UUID,
        explicit_baseline_id: UUID | None,
        repository: TestRunRepository,
    ) -> SelectedBaseline:
        current = await repository.get(current_run_id)
        if current is None:
            raise TestRunNotFoundError(f"Test run {current_run_id} was not found")
        if explicit_baseline_id is not None:
            return await self._explicit(current, explicit_baseline_id, repository)

        branch, strategy = _automatic_branch(current)
        if branch is None or strategy is None:
            return SelectedBaseline(
                selection=BaselineSelection(
                    current_run_id=current.id,
                    reason="No branch or default branch is available for automatic selection",
                ),
                current=current,
                baseline=None,
            )
        baseline = await repository.find_comparable_baseline(current, branch)
        if baseline is None:
            return SelectedBaseline(
                selection=BaselineSelection(
                    current_run_id=current.id,
                    reason=f"No earlier comparable run exists on branch {branch}",
                ),
                current=current,
                baseline=None,
            )
        label = "target branch" if strategy is BaselineStrategy.TARGET_BRANCH else "branch"
        reason = f"Latest earlier comparable run on {label} {branch}"
        return SelectedBaseline(
            selection=BaselineSelection(
                current_run_id=current.id,
                baseline_run_id=baseline.id,
                strategy=strategy,
                reason=reason,
            ),
            current=current,
            baseline=baseline,
        )

    async def _explicit(
        self,
        current: TestRun,
        baseline_id: UUID,
        repository: TestRunRepository,
    ) -> SelectedBaseline:
        baseline = await repository.get(baseline_id)
        if baseline is None:
            raise TestRunNotFoundError(f"Test run {baseline_id} was not found")
        if baseline.id == current.id:
            raise InvalidBaselineError("A test run cannot be its own baseline")
        if baseline.repository != current.repository:
            raise InvalidBaselineError("Explicit baseline must belong to the same repository")
        if baseline.created_at >= current.created_at:
            raise InvalidBaselineError("Explicit baseline must be older than the current run")
        if baseline.started_at > current.started_at:
            raise InvalidBaselineError("Explicit baseline cannot have a future execution start")
        return SelectedBaseline(
            selection=BaselineSelection(
                current_run_id=current.id,
                baseline_run_id=baseline.id,
                strategy=BaselineStrategy.EXPLICIT,
                reason=f"Explicit baseline run {baseline.id}",
            ),
            current=current,
            baseline=baseline,
        )


def _automatic_branch(current: TestRun) -> tuple[str | None, BaselineStrategy | None]:
    if current.change_request is not None:
        if current.change_request.target_branch:
            return current.change_request.target_branch, BaselineStrategy.TARGET_BRANCH
        if current.git_context.default_branch:
            return current.git_context.default_branch, BaselineStrategy.DEFAULT_BRANCH
        return None, None
    if current.branch:
        return current.branch, BaselineStrategy.SAME_BRANCH
    if current.git_context.default_branch:
        return current.git_context.default_branch, BaselineStrategy.DEFAULT_BRANCH
    return None, None
