# Reruns and retries

Vera treats individual test retries and CI job reruns as different evidence.

## Individual test retries

`TestCaseExecution` holds the final normalized JUnit outcome, which keeps Phase 3 comparisons
compatible. `TestCaseAttempt` holds immutable reported attempts for the same stable key. The final
execution's `attempt` is the final observed attempt number; earlier failures are never overwritten.

The JUnit adapter recognizes repeated same-key testcases with contiguous explicit `attempt`
numbers and Maven Surefire retry elements (`flakyFailure`, `flakyError`, `rerunFailure`, and
`rerunError`) where structurally compatible. Ambiguous duplicate identities or non-contiguous
attempt data are rejected rather than silently merged. Other report formats may expose only a
final outcome; Vera records that as one observed attempt and does not invent missing retries.

Repeated ingestion of the same CI execution remains idempotent, so it cannot duplicate attempt
history.

## CI job reruns

A GitHub workflow run attempt or a GitLab retried job is a separate `TestRun`, not another
`TestCaseAttempt`. Provider adapters derive a provider-specific execution series only for
historical grouping:

- GitHub follows its pipeline and job identity. A higher `GITHUB_RUN_ATTEMPT` is a separate run.
- GitLab uses the job name within a pipeline where it is available, because a retried job has a
  new job ID.
- An explicitly supplied external report ID separates otherwise similar executions.

This grouping permits a failed job followed by a passing rerun to contribute CI-rerun recovery
evidence without pretending the test framework retried the individual test. Provider mechanics
do not enter the core scoring algorithm.

## Idempotency and limitations

The existing test-run identity still distinguishes CI attempts. Re-submitting the exact same
execution returns the stored run; a legitimate provider rerun is preserved as a distinct run.
Stable-key duplicate cases inside a single run are diagnosed as ambiguous for historical analysis.

Vera does not currently infer retries from timestamps, log text, or similarly named test cases.
Only retry information carried by the compatible JUnit structure is modeled. Retry-aware support
for other report formats can be added through their parser adapters without changing the history
or scoring contracts.
