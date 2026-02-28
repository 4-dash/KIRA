import pytest

@pytest.mark.asyncio
async def test_gateway_health(gateway_client):
    # 'gateway_client' is automatically injected from conftest.py
    response = await gateway_client.get("/health")
    assert response.status_code == 200