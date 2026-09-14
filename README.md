# Vera

Vera is a CI-native automated test reporting and regression intelligence platform. It is
intended to run after regression jobs, normalize their results, retain execution history,
analyze changes, and publish useful reports to engineering tools.

Phase 1 provides Vera's first product capability: safe JUnit XML normalization and atomic,
idempotent persistence of test runs, suites, cases, failures, pipeline metadata, and execution
environment context. Regression comparison, flaky-test analysis, artifact storage, and
external integrations remain planned work.

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

The upload API accepts the same metadata as multipart form fields:

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
metadata. The initial schema is normalized across runs, suites, cases, failures, and
environment contexts.

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
