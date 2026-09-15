"""Conservative, versioned normalization and fingerprints for failure evidence."""

import hashlib
import re
from dataclasses import dataclass

FINGERPRINT_VERSION = "fingerprint-v1"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b", re.I
)
_TIMESTAMP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?\b"
)
_ADDRESS = re.compile(r"\b0x[0-9a-f]+\b", re.I)
_REQUEST = re.compile(
    r"\b(?:request|session|trace|build)[ _-]?(?:id|number)?[=:]\s*[A-Za-z0-9_-]{6,}\b", re.I
)
_PORT = re.compile(r"\b(?:port|localhost:)[ =:]*(?:[1-9]\d{3,4})\b", re.I)
_TEMP = re.compile(r"(?:/tmp|/var/folders/[^\s/]+/[^\s/]+/T|[A-Za-z]:\\Temp)[^\s'\"]+")
_LINE = re.compile(r"(?<=\bline )\d+\b|(?<=:)(?:\d+)(?=\)?(?:\s|$))", re.I)
_SPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizedFailure:
    """Canonical bounded evidence used solely for deterministic family identity."""

    type: str
    message: str
    stack_frames: tuple[str, ...]
    fingerprint: str
    version: str = FINGERPRINT_VERSION


def normalize_failure(
    failure_type: str | None, message: str | None, stack_trace: str | None
) -> NormalizedFailure:
    """Normalize known volatile tokens without removing ordinary assertion values."""
    kind = _normalize_text(failure_type or "UnknownFailure", 500)
    normalized_message = _normalize_text(message or "", 2_000)
    frames = tuple(
        _normalize_text(line, 500)
        for line in (stack_trace or "").splitlines()
        if line.lstrip().startswith(("File ", "at "))
    )[:8]
    canonical = "\n".join((kind, normalized_message, *frames))
    return NormalizedFailure(
        type=kind,
        message=normalized_message,
        stack_frames=frames,
        fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _normalize_text(value: str, limit: int) -> str:
    value = _CONTROL.sub(" ", value[:limit])
    for pattern, replacement in (
        (_UUID, "<uuid>"),
        (_TIMESTAMP, "<timestamp>"),
        (_ADDRESS, "<address>"),
        (_REQUEST, "<dynamic-id>"),
        (_PORT, "port=<port>"),
        (_TEMP, "<temp-path>"),
        (_LINE, "<line>"),
    ):
        value = pattern.sub(replacement, value)
    return _SPACE.sub(" ", value).strip()
