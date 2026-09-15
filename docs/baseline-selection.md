# Historical baseline selection

Run `vera compare <current-run-id>` after ingestion. Analysis is explicit: ingestion neither
selects a baseline nor fails because comparison is unavailable.

## Automatic precedence

1. A pull/merge request uses its normalized target branch. If absent, use its default branch.
2. A normal execution uses its branch. If absent, use its default branch.
3. With no appropriate branch or eligible candidate, return a structured `no_baseline` result.

There is no silent fallback from an unavailable target branch to a feature branch or another
repository. Candidates must have the same repository and exact environment, platform, browser,
device, and JSON test configuration. Missing values match missing values; they are not wildcards.
Application version and build number intentionally differ across executions and are not filters.

Candidates must have an earlier persisted `created_at` and an execution `started_at` no later
than the current execution. Select newest `created_at`, then descending UUID for deterministic
ties. Both passed and failed completed reports are valid: a failed baseline is necessary to
identify existing failures and recoveries. Vera ingestion stores complete report aggregates;
it has no partial/running run state. Report timestamps can be imperfect, so order primarily uses
ingestion time; this phase does not infer source-control ancestry or require execution intervals
to be disjoint.

Exclude the current run and every run with its provider and pipeline ID. This deliberately excludes retries,
reruns, and sibling jobs from the current pipeline, including GitHub run attempts. A previous
independent pipeline remains eligible. Providers are not a comparability filter: normalized data
from GitHub, GitLab, and local execution can compare within the same repository. Pipeline IDs
are scoped to their provider, so coincident IDs across providers do not exclude independent runs.

The result records selected run ID, strategy (`same_branch`, `target_branch`, `default_branch`,
or `explicit`), and a human-readable reason. Logs record IDs and the reason without failure traces.

## Explicit intent

```bash
vera compare <current-run-id> --baseline <older-run-id>
```

An explicit baseline must exist, be a different run in the same repository, have strictly older
creation time, and not start in the future relative to the current execution. Explicit intent
allows cross-branch, cross-environment/configuration, and same-pipeline comparison. Review these
differences before interpreting the result. Invalid baselines produce a domain validation error,
not a fallback selection.

One comparison is canonical for each current/baseline pair. If that pair already exists, an
explicit or automatic repeat returns its original strategy, reason, ID, and findings. Changing
the baseline creates a separate comparison. The run lookup returns the most recently created
comparison, not the most recently requested cached comparison.

## CI examples

For GitHub `pull_request` workflows, detected event context supplies `target_branch` from the
pull request's base ref. Ingest a prior `main` execution and a later PR execution with the same
environment, then run:

```bash
vera ingest reports/junit.xml --environment staging
vera compare <stored-pr-run-id>
```

For GitLab merge-request pipelines, `CI_MERGE_REQUEST_TARGET_BRANCH_NAME=main` drives the same
provider-neutral rule. A prior `main` pipeline is eligible; retries within the merge-request's
current pipeline are excluded. Existing [GitHub](github-actions.md) and [GitLab](gitlab-ci.md)
pipeline examples can add `vera compare` after capturing the stored run UUID.

## No baseline

POST comparison returns HTTP 200 with `status: no_baseline`, a selection reason, and null
comparison. CLI comparison prints the reason (or structured JSON) and exits 2. No empty comparison
is persisted. GET comparison returns 404 until a comparison exists. Analysis can be retried when
appropriate historical data is available; successful ingestion stays intact.
