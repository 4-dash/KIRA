import pytest
from httpx import ASGITransport, AsyncClient

@pytest.fixture
async def gateway_client():
    """Fixture to provide an async client for the API Gateway."""
    try:
        from Backend.api import app as gateway_app
        async with AsyncClient(transport=ASGITransport(app=gateway_app), base_url="http://test") as ac:
            yield ac
    except ImportError:
        # Skip if dependencies not available (e.g., llama_index)
        pytest.skip("Backend dependencies not available")