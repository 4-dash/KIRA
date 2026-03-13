"""Shared fixtures for integration tests."""
import pytest
import os
from opensearchpy import OpenSearch, RequestsHttpConnection
from dotenv import load_dotenv

load_dotenv()


@pytest.fixture(scope="session")
def opensearch_client():
    """Fixture to provide real OpenSearch client."""
    # PASTE YOUR OPENSEARCH_HOST HERE (e.g., 'opensearch' for docker, 'localhost' for local)
    OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
    OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
    
    try:
        client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            use_ssl=False,
            verify_certs=False,
            connection_class=RequestsHttpConnection,
            timeout=10,
        )
        # Test connection
        client.info()
        return client
    except Exception as e:
        pytest.skip(f"OpenSearch not available at {OPENSEARCH_HOST}:{OPENSEARCH_PORT}: {e}")


@pytest.fixture(scope="session")
def azure_openai_config():
    """Fixture to provide Azure OpenAI configuration."""
    # PASTE YOUR AZURE OPENAI KEYS HERE
    config = {
        "api_key": os.getenv("AZURE_OPENAI_API_KEY_EMB", ""),
        "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT_EMB", ""),
        "deployment": os.getenv("AZURE_DEPLOYMENT_NAME_EMB", ""),
        "api_version": os.getenv("AZURE_OPENAI_API_VERSION_EMB", "2024-05-01-preview"),
    }
    
    if not all([config["api_key"], config["endpoint"], config["deployment"]]):
        pytest.skip("Azure OpenAI credentials not configured")
    
    return config


@pytest.fixture(scope="session")
def otp_service():
    """Fixture to check OTP service availability."""
    import requests
    # PASTE YOUR OTP_URL HERE if different from default
    otp_url = os.getenv("OTP_URL", "http://localhost:8080/otp/routers/default/index/graphql")
    
    try:
        response = requests.post(
            otp_url,
            json={"query": "{ stops { name } }"},
            timeout=5
        )
        if response.status_code != 200:
            raise Exception(f"OTP returned {response.status_code}")
        return otp_url
    except Exception as e:
        pytest.skip(f"OTP service not available at {otp_url}: {e}")


@pytest.fixture(scope="session")
def bayerncloud_config():
    """Fixture to provide BayernCloud API configuration."""
    # PASTE YOUR BAYERNCLOUD API KEY HERE
    config = {
        "api_key": os.getenv("BAYERNCLOUD_API_KEY", ""),
        "api_base_url": os.getenv("BAYERNCLOUD_API_BASE_URL", ""),
        "data_dir": os.getenv("BAYERNCLOUD_DATA_DIR", "/data/bayerncloud"),
        "page_size": int(os.getenv("BAYERNCLOUD_PAGE_SIZE", "100")),
    }
    
    if not all([config["api_key"], config["api_base_url"]]):
        pytest.skip("BayernCloud API credentials not configured")
    
    return config
