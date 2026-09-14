# GitLab CI

Vera consumes `CI`, `GITLAB_CI`, `CI_PROJECT_PATH`, `CI_PROJECT_URL`, `CI_PROJECT_ID`,
`CI_PIPELINE_ID`, `CI_PIPELINE_IID`, `CI_PIPELINE_URL`, `CI_PIPELINE_SOURCE`, `CI_JOB_ID`,
`CI_JOB_NAME`, `CI_JOB_URL`, `CI_COMMIT_SHA`, `CI_COMMIT_BRANCH`, `CI_COMMIT_REF_NAME`,
`CI_DEFAULT_BRANCH`, `CI_COMMIT_MESSAGE`, `GITLAB_USER_LOGIN`, `CI_MERGE_REQUEST_IID`,
`CI_MERGE_REQUEST_TITLE`, `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME`,
`CI_MERGE_REQUEST_TARGET_BRANCH_NAME`, and `CI_MERGE_REQUEST_PROJECT_URL`.

Merge-request fields are optional and normally exist only in merge-request pipelines. Branch and
tag pipelines remain valid without them. Environment mapping alone supplies normal context; the
GitLab API token is optional.

```yaml
stages: [test, report]

regression:
  stage: test
  image: python:3.12-slim
  script:
    - pip install uv
    - uv sync --frozen
    - uv run pytest --junitxml=report.xml
  artifacts:
    when: always
    reports:
      junit: report.xml
    paths: [report.xml]

vera:
  stage: report
  image: python:3.12-slim
  needs:
    - job: regression
      artifacts: true
  script:
    - pip install uv
    - uv sync --frozen
    - uv run alembic upgrade head
    - uv run vera ingest report.xml --environment staging
```

Set `VERA_DATABASE_URL` and optional `VERA_GITLAB_TOKEN` as masked CI variables. Vera never
prints tokens. A retried GitLab job receives a new `CI_JOB_ID`, so it is retained as a distinct
test execution without a manually supplied attempt number.
