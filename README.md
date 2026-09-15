# Vera

Vera is a CI-native automated test reporting and regression intelligence platform. It is
intended to run after regression jobs, normalize their results, retain execution history,
analyze changes, and publish useful reports to engineering tools.

Phase 3 adds deterministic historical regression comparison to CI-aware JUnit ingestion.
Vera selects comparable earlier runs, matches stable test identities, and persists new failures,
existing failures, recoveries, new tests, missing tests, and status transitions. GitHub Actions
and GitLab CI metadata detection remains token-free; optional APIs enrich metadata only.
Flaky-test analysis, performance analysis, artifact storage, and publishers remain planned work.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker with Docker Compose for PostgreSQL and container validation

## Set up the project

```bash
uv sync
cp .env.example .env
```

Run the CLI:

```bash
uv run vera --version
uv run vera health
```

After applying migrations, ingest a JUnit report:

```bash
uv run alembic upgrade head
uv run vera ingest reports/junit.xml \
  --provider gitlab \
  --repository startup/backend \
  --branch main \
  --commit-sha abc123 \
  --pipeline-id 1201 \
  --job-id 8891 \
  --environment staging
```

The command reports the persisted run ID and aggregates. Repeating the same CI identity returns
the existing run without inserting a duplicate.

Inside GitHub Actions or GitLab CI, the normal identity flags are detected automatically:

```bash
uv run vera context
uv run vera context --json
uv run vera ingest reports/junit.xml --environment staging
```

Explicit metadata flags remain available for local execution and override detected values when
provided. Use `--ci-provider github`, `--ci-provider gitlab`, or `--ci-provider local` to override
detection for diagnostics. See [docs/ci-providers.md](docs/ci-providers.md) for precedence,
identity, retry, security, and optional enrichment details.

After ingesting a baseline and a later run on the same repository, branch, and environment:

```bash
uv run vera compare <current-run-id>
uv run vera compare <current-run-id> --baseline <baseline-run-id> --json
uv run vera regressions <current-run-id> --json
```

Comparison is an explicit step, so analysis errors cannot roll back successful ingestion.
A first run returns `no_baseline` (CLI exit 2). Repeating a comparison for the same pair returns
the existing result. Change requests select their target branch; automatic selection excludes
executions in the current pipeline. See [baseline selection](docs/baseline-selection.md) and
[regression comparison](docs/regression-comparison.md) for identity, classifications, and API examples.

Run the API during development:

```bash
uv run uvicorn vera.api.app:create_app --factory --reload
curl http://127.0.0.1:8000/api/v1/health
```

The health endpoint reports process liveness and the installed Vera version. It deliberately
does not use the database, so an unavailable dependency does not turn a liveness probe into a
restart loop.

## Local containers

```bash
docker compose up --build -d
docker compose exec -T vera alembic upgrade head
docker compose ps
curl http://127.0.0.1:8000/api/v1/health
docker compose down
```

Compose keeps PostgreSQL on its private network and stores its data in the named
`postgres-data` volume. Use `docker compose exec postgres psql -U vera` when direct local
database access is needed. Values in `.env.example` are local-only defaults; provide managed
credentials through environment variables in deployed environments. Set `VERA_HOST_PORT` if
port 8000 is already occupied on the development host.

To exercise the CLI within Compose, copy a report into the API container and invoke Vera there:

```bash
docker compose cp reports/junit.xml vera:/tmp/junit.xml
docker compose exec -T vera vera ingest /tmp/junit.xml \
  --provider gitlab --repository startup/backend \
  --pipeline-id 1201 --job-id 8891 --environment staging
```

The provider-neutral upload API accepts normalized metadata as multipart form fields. The API
does not inspect the server process's own CI environment on behalf of a remote caller:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/test-runs/ingest \
  -F 'report=@reports/junit.xml;type=application/xml' \
  -F provider=gitlab \
  -F repository=startup/backend \
  -F pipeline_id=1201 \
  -F job_id=8891 \
  -F environment=staging
```

Retrieve runs with `GET /api/v1/test-runs/{id}` or list them with
`GET /api/v1/test-runs?offset=0&limit=20`. See [docs/ingestion.md](docs/ingestion.md) for the
supported JUnit subset and complete examples.

## Database migrations

Alembic reads `VERA_DATABASE_URL` through Vera's settings and uses the shared SQLAlchemy
metadata. The schema is normalized across runs, suites, cases, failures, and environment
contexts. CI and Git context fields live on `test_runs` because they are one-to-one and central
to history queries.

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe schema change"
```

## Quality checks

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
uv build
```

The database integration test uses a disposable PostgreSQL Testcontainer, so Docker must be
running for the full suite. Install the Git hooks with `uv run pre-commit install`.

## Architecture

Vera is a modular monolith. Thin CLI and API entry points invoke application services; the
domain defines provider-neutral models; parser, CI provider, and publisher protocols form
ports for future adapters; and persistence owns SQLAlchemy resources. This keeps future Jira,
GitHub, GitLab, Slack, and similar code outside the core domain while retaining one deployable
service. See [docs/architecture.md](docs/architecture.md) for boundaries and the planned data
flow.
