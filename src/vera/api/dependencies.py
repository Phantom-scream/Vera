from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from vera.persistence import Database


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Provide one SQLAlchemy session per request."""

    database = cast(Database, request.app.state.database)
    async for session in database.session():
        yield session
