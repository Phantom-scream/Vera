# Regression comparison

Vera compares complete executions using stable logical test identities. It does not compare
failure text, score flakiness, correlate changed files, or detect performance anomalies.

## Stable identity v1

For each case, trim outer whitespace consistently in classname, file, suite package, suite name,
and test name. Preserve internal whitespace because parameter values and filesystem names can
differ by spaces. Preserve case, punctuation, path separators, and parameterized name contents. Empty optional
values become null. Hash canonical sorted-key UTF-8 JSON with SHA-256 and prefix `v1:`:

```json
{"classname":"tests.Login","file":"tests/test_login.py","name":"test_login[user_a]","suite":null}
```

Suite identity is `[package, name]` only when both classname and file are absent; otherwise suite
is null. Qualified tests can move between suites without losing identity. Unqualified tests
moving suites become new/missing tests. Changing file, classname, or parameter name also creates
a new identity; Vera deliberately does not guess that renamed tests are equivalent. Distinct
modules and parameters remain distinct. Outer-whitespace-only distinctions are considered harmless;
if this collapses cases in one run, comparison fails clearly rather than silently choosing one.

Keys are persisted and indexed on cases, including migration backfill for old records. Hashes
are matching identifiers, not UUIDs or confidentiality guarantees. Duplicate keys in either run
raise an ambiguity error (API 422, CLI exit 1) and leave no partial comparison. Ingestion remains
successful so original evidence can be inspected.

## Classifications

| Classification | Meaning |
| --- | --- |
| `new_failure` | Shared test was passed/skipped, now failed/errored |
| `existing_failure` | Shared test failed/errored in both runs |
| `recovered` | Shared test failed/errored, now passed |
| `unchanged_pass` | Passed in both runs |
| `new_test` | Present only in current, regardless of status |
| `missing_test` | Present only in baseline, regardless of status |
| `newly_skipped` | Passed, now skipped |
| `unchanged_skipped` | Skipped in both runs |
| `status_changed` | Other transition: failure/error to skipped, or skipped to passed |

`existing_failure` replaces the redundant `unchanged_failure` category. Original failed/error
statuses remain on findings, including error-to-failure transitions. Disappearance never counts
as recovery. Newly introduced failing tests are `new_test`; their current status remains visible
and they are not included in `new_failures`, which specifically counts regressions of shared tests.

Summary buckets are disjoint. `status_changes` combines `newly_skipped` and `status_changed`;
`unchanged_tests` combines unchanged passes and skips. Existing failures have their own bucket.
Findings cover the union of identities, so summary totals sum to current + baseline - shared.
Empty reports are valid: empty-to-populated is all new tests, the reverse is all missing tests.

The pure algorithm builds two maps and traverses their ordered union in O(n) time and space.
It never scans a full case list per test or mutates historical runs. Database retrieval sorts
findings by test key for stable pagination. Summary and all findings persist in one transaction.
A unique run-pair constraint makes repeated or concurrent comparison idempotent.

## CLI

```bash
vera compare <current-run-id>
vera compare <current-run-id> --baseline <baseline-run-id> --json
vera regressions <current-run-id> --json
```

Human output shows run IDs, baseline reason, totals, and counts. JSON comparison includes the
selection, summary, all findings, and `created` flag. `regressions` shows new-failure findings
from the latest persisted comparison (first 500, with total); use the API for pagination.
Exit 0 means comparison/lookup succeeded, even when regressions exist. Exit 2 means no baseline;
exit 1 means configuration, persistence, missing comparison, or domain validation failure.

## API

```bash
curl -X POST http://127.0.0.1:8000/api/v1/test-runs/<current-id>/compare
curl -X POST http://127.0.0.1:8000/api/v1/test-runs/<current-id>/compare \
  -H 'Content-Type: application/json' -d '{"baseline_run_id":"<baseline-id>"}'
curl 'http://127.0.0.1:8000/api/v1/test-runs/<current-id>/comparison?limit=20&offset=0'
curl 'http://127.0.0.1:8000/api/v1/comparisons/<comparison-id>?classification=new_failure&limit=20'
```

POST returns HTTP 200, `status`, `created`, selection explanation, and summary. GET returns
summary, selection, findings in `items`, filtered `total`, `offset`, and `limit` (1–500).
Filters use the lowercase classifications above. Each finding has key, case IDs, original statuses,
and classification; retrieve the run to resolve case names and failure details. Missing run or
comparison returns 404; invalid explicit baseline returns 400. OpenAPI documents request schemas.

## Fixture expectations

`tests/fixtures/junit/regression_baseline.xml` and `regression_current.xml` each contain six tests.
Comparing them yields seven findings: one new failure, one existing failure (failure → error),
one recovery, one new test, one missing test, one newly skipped, and one unchanged pass.
Tests also cover all transitions, duplicate identities, target branches, explicit overrides,
empty cases, migration backfill, idempotency, pagination, and a 5,000-case synthetic comparison.

Future phases will add rerun/flaky intelligence, richer historical policies, performance analysis,
and publishing. The current baseline policy is conservative and explicit; it does not infer
commit ancestry or compatibility when metadata is absent.
