# Vera architecture

## Current Phase 0 foundation

Vera begins as a modular monolith: one Python package and one deployable API process, divided
by responsibilities that are expected to change for different reasons.

- `cli` and `api` are delivery mechanisms. They validate input and delegate work rather than
  owning business rules.
- `application` is reserved for explicit use-case orchestration as ingestion and analysis are
  introduced.
- `domain` contains typed, provider-neutral concepts and errors. It imports no web framework,
  database, or vendor SDK.
- `parsers`, `providers`, and `publishers` define small ports at external-system boundaries.
  Concrete adapters will be added only alongside real use cases.
- `persistence` owns SQLAlchemy metadata, engines, and session lifecycle. Persistence models
  remain separate from API schemas and domain models where their constraints differ.
- `config` loads typed environment settings. `observability` currently supplies structured
  standard-library logging and is a natural integration point for later OpenTelemetry setup.

The API exposes `/api/v1/health`, and the CLI exposes version and local health commands.
PostgreSQL connectivity and Alembic metadata wiring are present, but no business schema or
repository implementation has been invented before its use cases are known.

## Planned data flow

1. Automated tests run in GitHub Actions or GitLab CI and write JUnit XML, JSON, or another
   supported report.
2. A subsequent pipeline job invokes the Vera CLI.
3. A parser adapter normalizes the report into domain data.
4. In team mode, the CLI submits normalized execution data and relevant raw information to the
   Vera API.
5. Application services validate and coordinate persistence of execution history in
   PostgreSQL. Raw artifacts are planned for future S3-compatible storage.
6. Analysis services compare history to identify regressions, flaky behavior, duration
   anomalies, and release readiness.
7. Publisher adapters send derived reports to selected systems such as Jira, Xray, Notion,
   Slack, GitHub, or GitLab.

Steps 3 through 7 describe the intended evolution, not currently shipped product behavior.
The port boundaries prevent vendor concerns from entering the domain and allow asynchronous
network I/O where it improves throughput without forcing the whole domain to be asynchronous.

## Operational decisions

Each FastAPI application instance owns a SQLAlchemy async engine. Request dependencies create
short-lived sessions, and the application lifespan disposes the engine during shutdown. The
health route is a liveness probe; database readiness can be added separately when operational
requirements are defined.

Configuration uses a `VERA_` prefix and can read a local `.env` file. Container images run as
an unprivileged user. Logs are one-line JSON for reliable processing in CI and container
runtimes. OpenTelemetry libraries are deliberately deferred until tracing or metrics have a
defined deployment target.
