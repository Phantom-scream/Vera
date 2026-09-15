"""Provider-neutral history selection and bounded evidence retrieval."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from vera.domain.exceptions import TestRunNotFoundError, VeraError
from vera.domain.models import TestRun
from vera.domain.models.stability import HistoryObservation
from vera.persistence.repositories.history import TestHistoryRepository
from vera.persistence.repositories.test_runs import TestRunRepository


class TestHistoryService:
    async def reference(
        self,
        *,
        test_key: str | None,
        repository: str | None,
        run_id: UUID | None,
        session: AsyncSession,
    ) -> TestRun:
        """Require repository or an explicit run; never mix repository histories."""
        if run_id is None:
            if not repository or not test_key:
                raise VeraError("Supply a reference run or both repository and test key")
            run_id = await TestHistoryRepository(session).latest_run_id(repository, test_key)
        if run_id is None:
            raise TestRunNotFoundError("No execution exists for this repository and test key")
        run = await TestRunRepository(session).get(run_id)
        if run is None:
            raise TestRunNotFoundError(f"Test run {run_id} was not found")
        if repository is not None and repository != run.repository:
            raise VeraError("Reference run must belong to the requested repository")
        return run

    async def histories(
        self, reference: TestRun, keys: list[str], window: int, session: AsyncSession
    ) -> dict[str, tuple[HistoryObservation, ...]]:
        if not 1 <= window <= 100:
            raise VeraError("History window must be between 1 and 100")
        return await TestHistoryRepository(session).histories(reference, keys, window)
