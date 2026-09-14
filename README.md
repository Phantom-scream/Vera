# Vera

Vera is a CI-native automated test reporting and regression intelligence platform. It is
intended to run after regression jobs, normalize their results, retain execution history,
analyze changes, and publish useful reports to engineering tools.

This repository currently contains the Phase 0 engineering foundation. It provides a typed
Python package, CLI and API bootstraps, PostgreSQL connectivity, migration tooling, tests,
quality gates, containers, and CI. Result parsing, analysis, and external integrations are
planned and are not implemented yet.

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
docker compose ps
curl http://127.0.0.1:8000/api/v1/health
docker compose down
```

Compose keeps PostgreSQL on its private network and stores its data in the named
`postgres-data` volume. Use `docker compose exec postgres psql -U vera` when direct local
database access is needed. Values in `.env.example` are local-only defaults; provide managed
credentials through environment variables in deployed environments. Set `VERA_HOST_PORT` if
port 8000 is already occupied on the development host.

## Database migrations

Alembic reads `VERA_DATABASE_URL` through Vera's settings and uses the shared SQLAlchemy
metadata. No business tables exist in Phase 0, so the migration history intentionally starts
empty.

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
