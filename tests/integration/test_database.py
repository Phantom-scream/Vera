import asyncio

import pytest
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from vera.persistence import Database

pytestmark = pytest.mark.integration


def test_async_database_connectivity() -> None:
    with PostgresContainer("postgres:17-alpine", driver=None) as container:

        async def verify_connection() -> None:
            sync_url = container.get_connection_url()
            database = Database(sync_url.replace("postgresql://", "postgresql+asyncpg://", 1))
            try:
                async with database.session_factory() as session:
                    result = await session.execute(text("SELECT 1"))
                    assert result.scalar_one() == 1
            finally:
                await database.dispose()

        asyncio.run(verify_connection())
