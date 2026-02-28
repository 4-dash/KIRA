import pytest
from httpx import ASGITransport, AsyncClient
from Backend.api_gateway.main import app as gateway_app

@pytest.fixture
async def gateway_client():
    """Fixture to provide an async client for the API Gateway."""
    async with AsyncClient(transport=ASGITransport(app=gateway_app), base_url="http://test") as ac:
        yield ac