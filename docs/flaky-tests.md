# Flaky-test intelligence

Phase 4 identifies historically unstable tests from persisted execution evidence. It is a
deterministic analysis, not an AI prediction: the same compatible history and policy always
produce the same result.

## Compatible history

Vera matches `stable_test_key` values and considers only executions from the same repository and
the same environment, platform, browser, device, and test configuration. This prevents a
Chrome-only failure from changing the assessment for Firefox. Queries are bounded to a requested
window of 1 through 100 observations; the default is 50.

The default policy (`flaky-v1`) needs ten independent decisive pipelines before it assigns a
strong class. Passed, failed, and errored initial outcomes are decisive. Skipped and unknown
initial outcomes are retained and reported, but do not count as pass/failure evidence. A test
with fewer than ten independent decisive pipeline identities is `INSUFFICIENT_HISTORY`.

## Score and classes

For enough history, the flaky score is a 0–100 value:

```text
100 × (
  0.35 × 4 × failure_rate × (1 − failure_rate)
  + 0.30 × max(history_flip_rate, retry_flip_rate)
  + 0.15 × 4 × recent_failure_rate × (1 − recent_failure_rate)
  + 0.20 × max(test_retry_success_rate, ci_rerun_recovery_rate)
)
```

`recent_failure_rate` covers the latest five decisive observations. If at least two test-retry or
CI-rerun recoveries exist, a retry-evidence floor of `60 × recovery_rate` is also applied. The
policy and its SHA-256 policy key are stored with each snapshot so a future scoring version can be
distinguished from `flaky-v1`.

The classes are:

| Class | Meaning |
| --- | --- |
| `STABLE` | At least 20 independent pipelines and no observed failure or retry recovery. |
| `LIKELY_STABLE` | Some history, but too little instability evidence for suspicion. A one-off failure stays here. |
| `INSUFFICIENT_HISTORY` | Fewer than ten independent decisive pipelines. |
| `SUSPECTED_FLAKY` | Repeated independent failure evidence and a score from 18 through 49.99. |
| `FLAKY` | Repeated independent failure evidence and a score of at least 50. |
| `CONSISTENTLY_FAILING` | Every decisive initial outcome failed or errored and no reported attempt passed. |

Always-passing and always-failing tests therefore do not become flaky simply because their
outcomes are undesirable. A fail-pass transition by itself is also insufficient: history and
independent-pipeline gates prevent a single recovery from receiving a strong flaky label.

## Regression findings

Regression classification and stability are separate facts. A transition from pass to failure
remains `NEW_FAILURE`; when requested, its finding additionally includes `stability`,
`flaky_score`, and `stability_scoring_version`. Stability enrichment never mutates a persisted
comparison or its raw historical cases.

## CLI and API

```bash
vera flaky tests.auth::test_refresh_token --repository startup/backend --window 50
vera flaky --run <run-id> --json
vera history tests.auth::test_refresh_token --repository startup/backend --sequence --json
```

```text
GET /api/v1/tests/{test_key}/history?repository=startup/backend&window=50&offset=0&limit=20
GET /api/v1/tests/{test_key}/stability?repository=startup/backend&window=50&include_sequence=true
GET /api/v1/test-runs/{run_id}/flaky-tests?classification=FLAKY&window=50
GET /api/v1/test-runs/{run_id}/comparison?include_stability=true
```

Snapshots are idempotent for the reference run, test key, history window, and scoring-policy key.
They are retained for auditability and do not replace execution records.
