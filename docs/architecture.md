# Vera architecture

## Current Phase 4 implementation

Vera begins as a modular monolith: one Python package and one deployable API process, divided
by responsibilities that are expected to change for different reasons.

- `cli` and `api` are delivery mechanisms. They validate input and delegate work rather than
  owning business rules.
- `application` contains `TestRunIngestionService`, which selects the parser, calculates
  aggregates, and coordinates atomic/idempotent persistence. `BaselineSelectionService` selects
  historical candidates, `RegressionComparisonService` orchestrates atomic comparison storage,
  and `FlakyTestAnalysisService` calculates bounded, environment-compatible stability history.
- `domain` contains typed, provider-neutral concepts and errors. It imports no web framework,
  database, or vendor SDK.
- `parsers` defines a parser port and a safe JUnit XML adapter. `providers` maps GitHub Actions
  and GitLab CI inputs into normalized domain context and isolates optional HTTP enrichment.
  `publishers` remains a port for future external integrations.
- `persistence` owns SQLAlchemy metadata, engines, and session lifecycle. Persistence models
  remain separate from API schemas and domain models where their constraints differ.
- `config` loads typed environment settings. `observability` currently supplies structured
  standard-library logging and is a natural integration point for later OpenTelemetry setup.

The API exposes health, ingestion, retrieval, paginated listing, comparison execution, filtered
finding retrieval, and stability history. The CLI exposes version, health, CI-context diagnostics,
ingestion, comparison, regression lookup, and flaky/history analysis. PostgreSQL stores normalized
run aggregates and embedded one-to-one CI metadata through a schema protected by foreign keys,
uniqueness rules, indexes, and consistency checks.

## Planned data flow

1. Automated tests run in GitHub Actions or GitLab CI and write JUnit XML, JSON, or another
   supported report.
2. A subsequent pipeline job invokes the Vera CLI, which detects and normalizes CI context.
3. The JUnit parser adapter normalizes the report into domain data.
4. The CLI can persist directly, while clients can upload a report and metadata to the Vera
   API.
5. The ingestion service calculates aggregates and atomically persists execution history in
   PostgreSQL. Raw artifacts are planned for future S3-compatible storage.
6. Analysis services compare history to identify regressions, flaky behavior, duration
   anomalies, and release readiness.
7. Publisher adapters send derived reports to selected systems such as Jira, Xray, Notion,
   Slack, GitHub, or GitLab.

Steps 2 through 5 are implemented for GitHub Actions, GitLab CI, local/manual metadata, and
compatible JUnit XML. Step 6 now supports historical comparison and deterministic flakiness;
duration analysis, release readiness, and publishing remain future work. Provider
environment parsing and HTTP clients are separate from report parsing and persistence. The port
boundaries prevent vendor concerns from entering the domain and allow asynchronous network I/O
where it improves throughput without forcing the whole domain to be asynchronous.

## Operational decisions

Each FastAPI application instance owns a SQLAlchemy async engine. Request dependencies create
short-lived sessions, and the application lifespan disposes the engine during shutdown. The
health route is a liveness probe; database readiness can be added separately when operational
requirements are defined.

Configuration uses a `VERA_` prefix and can read a local `.env` file. Container images run as
an unprivileged user. Logs are one-line JSON for reliable processing in CI and container
runtimes. OpenTelemetry libraries are deliberately deferred until tracing or metrics have a
defined deployment target.

## Historical comparison boundaries

Stable identity generation and status classification are pure domain functions. They import no
provider or database code. The application layer chooses branches, enforces baseline safety, and
owns transactions; the persistence layer queries exact comparison dimensions and stores summaries
and findings. API routes and CLI commands delegate to the same services.

Comparison runs explicitly after ingestion. This makes no-baseline and ambiguous-identity errors
visible without jeopardizing execution history and leaves a clean boundary for future asynchronous
analysis. Historical runs are never modified during comparison. A migration backfills v1 keys on
existing cases; new ingestion computes the same algorithm during domain normalization.

Run pairs have one canonical persisted comparison. Run/case foreign keys use restrictive deletion
to protect historical evidence; findings are deleted only with their owning comparison. No run
deletion API is provided. See [baseline selection](baseline-selection.md) and
[comparison rules](regression-comparison.md) for the precise contracts.

## Retry and stability boundaries

`TestCaseExecution` represents the final reported outcome and remains the input to historical
comparison. `TestCaseAttempt` preserves every normalized individual retry reported by JUnit. A CI
job rerun is a distinct `TestRun`; provider-specific series grouping lives in `providers`, outside
the domain scoring code. The history repository uses two bounded bulk PostgreSQL queries, indexed
by repository, stable key, and compatible environment dimensions, so run-level analysis does not
issue one query per test.

The domain scoring function is pure and versioned (`flaky-v1`). Snapshot records retain the inputs,
policy key, score, and classification for auditability without changing raw execution history or
persisted regression classifications. See [flaky-test analysis](flaky-tests.md) and
[reruns and retries](reruns-and-retries.md) for the contracts.
