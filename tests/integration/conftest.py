from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.community.postgres import PostgresContainer

from vera.persistence import Database


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer("postgres:17-alpine", driver=None) as container:
        yield container.get_connection_url().replace("postgresql://", "postgresql+asyncpg://", 1)


@pytest.fixture
def migrated_database_url(postgres_url: str) -> Iterator[str]:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_url)
    command.upgrade(config, "head")
    yield postgres_url
    command.downgrade(config, "base")


@pytest.fixture
async def database_session(migrated_database_url: str) -> Iterator[AsyncSession]:
    database = Database(migrated_database_url)
    try:
        async with database.session_factory() as session:
            yield session
    finally:
        await database.dispose()
