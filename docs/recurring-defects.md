# Recurring defect intelligence

`FailureFamily` groups failures by `fingerprint-v1`. A family stores first and latest runs,
canonical evidence, and total occurrence count. Several tests sharing a timeout in one run create
one family while their raw failure records remain separate.

`NEW_FAILURE_PATTERN` means all observed evidence is in the current group; otherwise Vera reports
`RECENT_RECURRING`. Recurrence is not severity, flaky-test classification, or regression class.

```bash
vera failures --run <run-id>
vera failure <family-id> --json
vera recurring --json
```

The API provides run grouping, family lookup, and paginated family listing. Summary endpoints never
return unbounded raw stack traces.
