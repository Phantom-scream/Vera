import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vera.application.services import TestRunIngestionService as IngestionService
from vera.application.services.failure_intelligence import FailureIntelligenceService
from vera.domain.models import EnvironmentContext, PipelineContext
from vera.persistence.models import FailureFamilyRecord

pytestmark = pytest.mark.integration


async def test_dynamic_failures_group_and_recur(database_session: AsyncSession) -> None:
    service = IngestionService()
    reports = [
        (
            b'<testsuite><testcase name="one"><failure type="DatabaseTimeout" '
            b'message="request_id=abcdef123 at 2026-01-01 00:00:00 port=50001">'
            b'File "/tmp/a.py", line 12</failure></testcase><testcase name="two">'
            b'<failure type="DatabaseTimeout" message="request_id=abcdef456 at 2026-01-01 '
            b'00:00:00 port=50002">File "/tmp/b.py", line 22</failure></testcase></testsuite>'
        ),
        (
            b'<testsuite><testcase name="three"><failure type="DatabaseTimeout" '
            b'message="request_id=abcdef789 at 2026-01-02 00:00:00 port=50003">'
            b'File "/tmp/c.py", line 32</failure></testcase><testcase name="other">'
            b'<failure type="AssertionError" message="expected 200 got 500"/>'
            b"</testcase></testsuite>"
        ),
    ]
    runs = []
    for index, report in enumerate(reports):
        result = await service.ingest(
            content=report,
            report_format="junit",
            pipeline=PipelineContext(
                provider="local", repository="acme/failure", pipeline_id=str(index), job_id="tests"
            ),
            environment=EnvironmentContext(environment="staging"),
            session=database_session,
        )
        runs.append(result.test_run)
    assert await database_session.scalar(select(func.count()).select_from(FailureFamilyRecord)) == 2
    groups = await FailureIntelligenceService().run_families(runs[1].id, database_session)
    timeout = next(item for item in groups if item["canonical_type"] == "DatabaseTimeout")
    assert timeout["occurrence_count"] == 3
    assert timeout["recurrence"] == "recent_recurring"
