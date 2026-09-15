# Failure fingerprinting

Phase 5 derives `fingerprint-v1` from a conservative canonical form of failure type, message,
and up to eight stack frames. The SHA-256 fingerprint never includes a run UUID or raw timestamp.
Raw messages and traces remain unchanged in `test_failures`.

Normalization replaces UUIDs, ISO timestamps, request/session IDs, memory addresses, random ports,
temporary paths, and stack line numbers. Ordinary assertion values such as `expected 200 got 500`
remain intact, so meaningful failures do not collapse merely because their text is similar. Inputs
are bounded and control characters are removed before normalization.

This conservative approach has known tradeoffs: identical normalized exceptions can share a family,
while unknown dynamic formats can create separate families. The stored algorithm version makes
future normalization changes auditable.
