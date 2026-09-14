# Test-run ingestion

Vera ingests a JUnit XML report plus provider-neutral CI and environment metadata. It calculates
all suite and run totals from parsed test cases, then writes the complete aggregate in one
PostgreSQL transaction.

## Supported JUnit XML

The JUnit adapter accepts either `testsuite` or `testsuites` as the document root, including
namespaced elements. It recognizes direct `testcase` children and these outcomes:

- no outcome child: passed;
- `failure`: failed, with `type`, `message`, and element text retained;
- `error`: errored, with the same failure detail fields;
- `skipped`: skipped.

Optional suite `name`, `package`, and `timestamp` attributes and case `name`, `classname`,
`file`, `time`, and `attempt` attributes are normalized. Missing names receive stable fallback
labels, missing durations become zero, and attempts default to one. Negative, non-finite, or
malformed durations and attempts are rejected.

Declared JUnit `tests`, `failures`, `errors`, `skipped`, and suite `time` totals are not trusted.
Vera derives totals and durations from the actual cases. Errored cases contribute to
`failed_tests`, while the run status remains `error` so the distinction is retained.

XML parsing forbids DTDs and entity expansion. API and CLI reads are bounded by
`VERA_MAX_REPORT_SIZE_BYTES`, which defaults to 10 MiB.

Current limitations:

- only the first failure, error, or skipped outcome child is interpreted for a case;
- `properties`, standard output/error, attachments, and arbitrary extension elements are not
  persisted;
- rerun elements are not merged; producers can supply an `attempt` attribute;
- aggregate-only suites without direct test cases are ignored;
- regression comparison and flaky-test analysis are future phases.

## Idempotency

The identity key is `(provider, repository, pipeline_id, job_id, external_run_id)`. Provider is
normalized to lowercase and identity strings are trimmed. When `external_run_id` is omitted,
Vera uses `pipeline_id:job_id`. PostgreSQL enforces the composite uniqueness rule, and the
service handles both ordinary repeats and concurrent uniqueness races. A repeat returns the
original run with `created: false` and HTTP 200; a new run returns `created: true` and HTTP 201.
The first successfully stored report remains authoritative if a later request reuses the same
identity with different content.

## CLI

Set `VERA_DATABASE_URL`, apply migrations, then run:

```bash
vera ingest reports/junit.xml \
  --provider gitlab \
  --repository startup/backend \
  --branch main \
  --commit-sha abc123 \
  --pipeline-id 1201 \
  --job-id 8891 \
  --environment staging
```

The command exits nonzero for unreadable or oversized files, malformed XML, invalid metadata,
unsupported formats, configuration errors, or database failures.

## API

Upload a report as multipart form data:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/test-runs/ingest \
  -F 'report=@reports/junit.xml;type=application/xml' \
  -F provider=gitlab \
  -F repository=startup/backend \
  -F pipeline_id=1201 \
  -F job_id=8891 \
  -F external_run_id=regression-1201 \
  -F environment=staging \
  -F application_version=2.4.0 \
  -F 'test_configuration={"workers":4}'
```

Supported upload media types are `application/xml`, `text/xml`, `application/x-xml`, and
`application/octet-stream`. Invalid reports return a structured `detail` response. Oversized
reports return 413 and unsupported media types or formats return 415.

Use `GET /api/v1/test-runs/{id}` for a complete run and
`GET /api/v1/test-runs?offset=0&limit=20` for newest-first pagination. Page limits range from 1
to 100.
