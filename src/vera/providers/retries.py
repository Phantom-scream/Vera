"""Normalize provider rerun grouping without leaking mechanics into scoring."""

import json


def execution_series(
    provider: str, pipeline_id: str, job_id: str, job_name: str | None, external_run_id: str
) -> str:
    """GitLab retries have new IDs; group only when a stable job name is available."""
    job = job_name if provider == "gitlab" and job_name else job_id
    report = None if external_run_id == f"{pipeline_id}:{job_id}" else external_run_id
    return json.dumps([provider, pipeline_id, job, report], separators=(",", ":"))
