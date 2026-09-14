# GitHub Actions

Vera consumes `GITHUB_ACTIONS`, `GITHUB_REPOSITORY`, `GITHUB_SERVER_URL`, `GITHUB_API_URL`,
`GITHUB_RUN_ID`, `GITHUB_RUN_NUMBER`, `GITHUB_RUN_ATTEMPT`, `GITHUB_WORKFLOW`, `GITHUB_JOB`,
`GITHUB_SHA`, `GITHUB_REF`, `GITHUB_REF_NAME`, `GITHUB_HEAD_REF`, `GITHUB_BASE_REF`,
`GITHUB_ACTOR`, `GITHUB_EVENT_NAME`, and `GITHUB_EVENT_PATH`.

`GITHUB_EVENT_PATH` is read only when GitHub supplies it, is limited to 1 MiB, and must contain a
JSON object. For pull-request events Vera reads the number, title, URL, head branch, and base
branch. Other workflow triggers produce no change-request context. A custom `GITHUB_API_URL` is
used for optional enrichment only when it uses HTTPS and no explicit Vera API URL replaces it.

```yaml
name: regression
on: [push, pull_request]

permissions:
  contents: read
  pull-requests: read

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17-alpine
        env:
          POSTGRES_DB: vera
          POSTGRES_USER: vera
          POSTGRES_PASSWORD: local-ci-only
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U vera"
          --health-interval 5s --health-timeout 3s --health-retries 10
    env:
      VERA_DATABASE_URL: postgresql+asyncpg://vera:local-ci-only@localhost:5432/vera
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - run: uv run pytest --junitxml=report.xml
      - run: uv run alembic upgrade head
      - run: uv run vera ingest report.xml --environment staging
        env:
          GITHUB_TOKEN: ${{ github.token }} # optional enrichment
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: junit-report
          path: report.xml
```

Normal repository, commit, branch, workflow, job, actor, URL, and pull-request metadata requires
no manual Vera flags and no provider API call.
