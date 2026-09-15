# Phase 3 completion and validation

Vera 0.4.0 extends the existing ingestion architecture with deterministic historical comparison.
No runtime or development dependencies were added.

## Design and schema

- Stable v1 keys hash canonical JSON containing classname, file, test name, and an unqualified
  suite fallback. Outer whitespace is trimmed; internal spacing and parameter values are retained.
  Keys are indexed and backfilled on existing records.
- Automatic baseline selection uses the same branch or a change request's target/default branch,
  exact environment/configuration dimensions, older creation time, and a non-future execution start.
  The current provider/pipeline is excluded, including retries. Completed failed reports remain
  valid baselines. Explicit overrides permit intentional dimension differences within one repository.
- Migration `20260914_03` adds non-null case keys, `regression_comparisons`, and
  `test_comparison_findings`. Run pairs and finding keys are unique. Restrictive run/case foreign
  keys protect historical evidence; findings cascade with their owning comparison.
- Classification has nine disjoint categories. `existing_failure` replaces redundant
  `unchanged_failure`; failed/error statuses remain distinguishable on findings. Missing tests
  never count as recoveries. Pure matching/classification takes O(n) time and space.
- Analysis is an explicit application-service step after ingestion. A missing baseline returns
  `no_baseline` without persisting a synthetic comparison or affecting ingestion. CLI exit is 2;
  API POST status is 200. Comparison ambiguity aborts analysis with a diagnostic.

See [identity and classifications](regression-comparison.md), [baseline policy](baseline-selection.md),
and [architecture](architecture.md) for the full contracts.

## Commands executed

| Validation | Final result |
| --- | --- |
| `uv sync --frozen` | Passed; 66 installed packages checked |
| `uv run ruff format --check .` | 85 files already formatted |
| `uv run ruff check .` | All checks passed |
| `uv run mypy src` | Success; no issues in 55 source files |
| `uv run pre-commit run --all-files` | Ruff check, Ruff format, and mypy passed |
| `uv run pytest` | 81 passed in 8.84 seconds |
| `uv run pytest --cov=vera` with duplicate coverage addopts removed | 81 passed in 8.68 seconds |
| Coverage, statements plus branches | 90.02%; 1,423/1,542 statements and 192/252 branches covered |
| `uv build` | Built `vera-0.4.0.tar.gz` and `vera-0.4.0-py3-none-any.whl` |
| `docker compose config --quiet` | Passed |
| `docker build .` | Passed, final production source built |
| `VERA_HOST_PORT=18000 docker compose up --build -d` | API and PostgreSQL started |
| `docker compose exec -T vera alembic upgrade head` | Revision `20260914_03` applied |
| `docker compose exec -T vera alembic check` | No new upgrade operations detected |
| Health endpoint | HTTP 200, `{"status":"ok","version":"0.4.0"}` |
| `vera --version` | `0.4.0` |

The coverage invocation was:

```bash
uv run pytest --cov=vera \
  -o 'addopts=--strict-config --strict-markers --cov-report=term-missing'
```

This avoids declaring `--cov=vera` twice because the repository already enables coverage in
pytest addopts. No tests are skipped or excluded by this override. The ordinary pytest invocation
also measures coverage.

## Runtime evidence

Acceptance checks ran against the local Docker stack through the installed container CLI and
the HTTP API, with no provider tokens. They used repository names isolated from prior phase data.

1. Ingested a healthy `simple.xml` first execution; CLI JSON comparison exited 2 with null
   comparison and an explanatory no-baseline selection.
2. Ingested the regression baseline through the CLI and current fixture through multipart API.
   Both contained six cases; the comparison contained seven findings: one new failure, existing
   failure, recovery, new test, missing test, newly skipped test, and unchanged pass.
   Case names, original error/failure status, failure traces, aggregate counts, and paginated API
   findings were verified against fixture expectations.
3. Ran human and JSON CLI comparison, repeated comparison, explicit-baseline API comparison,
   and JSON regression lookup. The pair retained the same comparison UUID and returned
   `created: false`; regression lookup returned one new failure.
4. Simulated GitHub Actions with a representative pull-request event file. Context diagnostics
   exposed the `main` target branch. Automatic comparison selected the prior `main` execution.
   Repeated ingestion reused the run; changing run attempt to 2 created a distinct execution
   and preserved target-branch baseline selection.
5. Simulated GitLab merge-request variables targeting `main`. Context diagnostics and retrieval
   retained the merge-request metadata. Duplicate ingestion reused the run; a retried job with
   a new job ID created a distinct execution and selected the same target-branch baseline.

Automated tests additionally verify explicit-baseline rejection, same-pipeline exclusion,
provider-scoped pipeline IDs, environment incompatibility, every classification, empty runs,
qualified suite moves, duplicate identities, concurrent idempotency, rollback after database
flush, API filtering/pagination, CLI JSON/error redaction, downgrade/upgrade key backfill, schema
drift, and a 5,000-case synthetic comparison.

## Material files

New domain modules define identity, comparison enums/models, and the pure comparison algorithm.
New application services select baselines and orchestrate persistence. New persistence models,
repository, and migration store the canonical pair and findings. Existing ingestion models and
repository now round-trip case keys. CLI and API add comparison and regression retrieval. Tests
add two realistic XML fixtures, domain/baseline tests, and service, migration, API, and CLI checks.
README and architecture documentation were updated; baseline/comparison guides were added.
Package metadata and lockfile project version are now 0.4.0.

## Known limitations and deferred work

Baseline chronology primarily uses ingestion time with a report-start guard; no commit ancestry
or baseline quality heuristics are inferred. Missing configuration matches missing configuration,
not proven compatibility. Explicit overrides require the caller to interpret dimension differences.
Unqualified suite moves and changes to classname/file/parameters appear as new/missing tests.
Ambiguous duplicate identities require caller correction; Phase 4 will address richer rerun models.
The regression CLI displays the first 500 new failures with a total; the API supports pagination.
Newly introduced failing tests are `new_test`, not shared-test `new_failure` regressions.

Flaky scoring, clustering, AI, performance anomaly detection, release readiness, changed-file
correlation, and publishers remain deferred. No historical ingestion data is mutated by comparison.
Commit hashes are included in the delivery message.
