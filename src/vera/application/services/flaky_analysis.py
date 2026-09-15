"""Bounded batched analysis with immutable versioned evidence snapshots."""

import logging
from collections import Counter
from time import perf_counter

from sqlalchemy.ext.asyncio import AsyncSession

from vera.application.services.test_history import TestHistoryService
from vera.domain.exceptions import AmbiguousTestIdentityError, VeraError
from vera.domain.models import TestRun
from vera.domain.models.stability import (
    ScoringPolicy,
    TestStabilityAnalysis,
    environment_fingerprint,
)
from vera.domain.stability import history_metrics, score_stability
from vera.persistence.repositories.history import TestHistoryRepository

logger = logging.getLogger(__name__)


class FlakyTestAnalysisService:
    def __init__(self, policy: ScoringPolicy | None = None) -> None:
        self.policy = policy or ScoringPolicy()

    async def analyze(
        self,
        *,
        reference: TestRun,
        session: AsyncSession,
        window: int = 50,
        keys: list[str] | None = None,
    ) -> list[TestStabilityAnalysis]:
        """Analyze all requested identities in bulk without one query per test."""
        if not 1 <= window <= 100:
            raise VeraError("History window must be between 1 and 100")
        started = perf_counter()
        if keys is None:
            keys = [
                case.stable_test_key
                for suite in reference.suites
                for case in suite.test_cases
                if case.stable_test_key
            ]
            if len(set(keys)) != len(keys):
                raise AmbiguousTestIdentityError(
                    "Current run contains ambiguous duplicate test identities"
                )
        keys = sorted(set(keys))
        repository = TestHistoryRepository(session)
        cached = await repository.snapshots(reference, keys, window, self.policy)
        missing = [key for key in keys if key not in cached]
        histories = await TestHistoryService().histories(reference, missing, window, session)
        results = []
        for key in missing:
            observations = histories[key]
            metrics = history_metrics(observations, self.policy.recent_window)
            reliability, score, classification, reason = score_stability(metrics, self.policy)
            results.append(
                TestStabilityAnalysis(
                    test_key=key,
                    repository=reference.repository,
                    reference_run_id=reference.id,
                    environment_fingerprint=environment_fingerprint(reference.environment),
                    history_window=window,
                    scoring_version=self.policy.version,
                    policy=self.policy,
                    statistics=metrics,
                    reliability_score=reliability,
                    flaky_score=score,
                    classification=classification,
                    reason=reason,
                    observations=observations,
                )
            )
        await repository.store_snapshots(results, self.policy)
        await session.commit()
        cached.update({item.test_key: item for item in results})
        ordered = [cached[key] for key in keys]
        logger.info(
            "Stability analysis reference_run_id=%s analyzed_tests=%s "
            "duration_seconds=%.3f classifications=%s",
            reference.id,
            len(keys),
            perf_counter() - started,
            dict(Counter(item.classification.value for item in ordered)),
        )
        return ordered
