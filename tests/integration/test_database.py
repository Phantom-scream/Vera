import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def test_async_database_connectivity(database_session: AsyncSession) -> None:
    result = await database_session.execute(text("SELECT 1"))

    assert result.scalar_one() == 1
