import pytest
from httpx import ASGITransport, AsyncClient

from vera import __version__
from vera.api import create_app
from vera.config import Environment, Settings


@pytest.mark.asyncio
async def test_health_endpoint() -> None:
    settings = Settings(environment=Environment.TEST, _env_file=None)
    app = create_app(settings)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
