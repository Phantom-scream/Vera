# CI provider context

Vera detects GitHub Actions only when `GITHUB_ACTIONS=true` and GitLab CI only when
`GITLAB_CI=true`. Generic variables such as `CI=true` are deliberately insufficient. If both
authoritative markers exist, Vera returns a configuration error. Outside either environment,
Vera stays in local/manual mode and the Phase 1 identity flags remain required.

Run `vera context` for a concise diagnostic or `vera context --json` for the complete normalized
`CIContext`, `GitContext`, and optional `ChangeRequestContext`. Diagnostic output includes no
tokens, authorization headers, or unrelated environment variables.

## Precedence

Explicit `vera ingest` values override detected values. Vera logs the name of an overridden
identity field, without logging either value, when `provider`, `repository`, `pipeline_id`,
`job_id`, or `run_attempt` differs. This supports custom CI systems and debugging while making
the override visible in structured pipeline logs. `--ci-provider` controls the detector itself;
`--provider` supplies the persisted provider value. `VERA_CI_PROVIDER_OVERRIDE` supplies the
same detector override through configuration.

The FastAPI ingestion endpoint never reads the API server's CI environment. Remote callers send
normalized context fields explicitly. Existing Phase 1 multipart requests remain valid.

## Execution identity and retries

The database identity is:

```text
provider + repository + pipeline_id + job_id + external_run_id + run_attempt
```

When `external_run_id` is absent, Vera retains the stable `pipeline_id:job_id` fallback. Repeating
the same exact execution is idempotent.

GitHub keeps `GITHUB_RUN_ID` across workflow reruns and increments `GITHUB_RUN_ATTEMPT`, so the
attempt is part of the identity and each legitimate rerun is retained. `GITHUB_JOB` is the job
key available in the standard environment. Matrix jobs that share a job key should pass an
explicit unique `--job-id` until Vera adds matrix-dimension normalization.

GitLab creates a new `CI_JOB_ID` when a job is retried. Vera therefore stores GitLab
`run_attempt=1`; the new job ID distinguishes the retry while repeated ingestion from that job
remains idempotent.

Downgrading the Phase 2 migration to Phase 1 cannot represent multiple run attempts under the
old constraint. The downgrade retains the earliest attempt for each old identity and removes
later duplicates before restoring the Phase 1 constraint.

## Optional API enrichment

Environment metadata is sufficient for normal ingestion. Configure `VERA_GITHUB_TOKEN` or
`VERA_GITLAB_TOKEN` only when default-branch, commit-author/message, or change-request enrichment
is wanted. Within detected GitHub Actions, the native `GITHUB_TOKEN` is a fallback after
`VERA_GITHUB_TOKEN`. Provider requests use HTTPS, finite timeouts, sanitized errors, and one retry
for timeouts, rate limits, or server failures. Authentication and not-found responses are not
retried. Any enrichment failure preserves the detected context and does not fail ingestion.

Configuration:

```text
VERA_GITHUB_TOKEN
VERA_GITHUB_API_URL=https://api.github.com
VERA_GITLAB_TOKEN
VERA_GITLAB_API_URL=https://gitlab.com/api/v4
VERA_PROVIDER_API_TIMEOUT=5
VERA_CI_PROVIDER_OVERRIDE
```

See [GitHub Actions](github-actions.md) and [GitLab CI](gitlab-ci.md) for mappings and complete
pipeline examples.
