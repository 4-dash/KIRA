# Integration Tests - API Keys Configuration Guide

## Overview
Integration tests are now available in `tests/integration/` to validate your system against real services. These tests will **skip gracefully** if API keys or services are not available.

---

## Files That Need API Keys

### 1. **tests/integration/conftest.py**
Shared configuration and fixtures. Add these environment variables to your `.env` file:

```bash
# OpenSearch Configuration
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200

# Azure OpenAI - Embedding Model (for Ingester)
AZURE_OPENAI_API_KEY_EMB=<paste your Azure OpenAI key here>
AZURE_OPENAI_ENDPOINT_EMB=<paste your Azure endpoint here>
AZURE_DEPLOYMENT_NAME_EMB=<paste your deployment name here>
AZURE_OPENAI_API_VERSION_EMB=2024-05-01-preview

# BayernCloud API (for Fetcher)
BAYERNCLOUD_API_KEY=<paste your BayernCloud API key here>
BAYERNCLOUD_API_BASE_URL=<paste your BayernCloud base URL here>
BAYERNCLOUD_DATA_DIR=/data/bayerncloud
BAYERNCLOUD_PAGE_SIZE=100

# Index Names
POI_INDEX=tourism-data-v7
POI_MAP_INDEX=poi-data

# OTP Configuration
OTP_URL=http://localhost:8080/otp/routers/default/index/graphql
```

### 2. **tests/integration/test_ingester_integration.py**
Tests the data ingester with real OpenSearch and Azure OpenAI.

**Required Environment Variables:**
- `OPENSEARCH_HOST` ✓ (from conftest.py)
- `OPENSEARCH_PORT` ✓ (from conftest.py)
- `AZURE_OPENAI_API_KEY_EMB` ✓ (from conftest.py)
- `AZURE_OPENAI_ENDPOINT_EMB` ✓ (from conftest.py)
- `AZURE_DEPLOYMENT_NAME_EMB` ✓ (from conftest.py)
- `POI_MAP_INDEX` ✓ (from conftest.py)
- `POI_INDEX` ✓ (from conftest.py)

**Running:**
```bash
pytest tests/integration -v
```

**What it tests:**
- OpenSearch connection
- Creating vector and map indices
- Indexing documents
- Extracting geographic fields
- Building metadata

---

### 3. **tests/integration/test_trip_planner_integration.py**
Tests trip planning with real OTP service.

**Required Environment Variables:**
- `OTP_URL` ✓ (from conftest.py)

**Running:**
```bash
pytest tests/integration/test_trip_planner_integration.py -v
```

**What it tests:**
- OTP service availability
- Retrieving real coordinates from stops
- Planning actual routes
- Pydantic models with realistic data

---

### 4. **tests/integration/test_api_gateway_integration.py**
Tests API gateway functions with real OpenSearch.

**Required Environment Variables:**
- `OPENSEARCH_HOST` ✓ (from conftest.py)
- `OPENSEARCH_PORT` ✓ (from conftest.py)
- `POI_MAP_INDEX` ✓ (from conftest.py)

**Running:**
```bash
pytest tests/integration/test_api_gateway_integration.py -v
```

**What it tests:**
- Searching POIs in OpenSearch
- Normalizing search results
- Extracting coordinates from various formats
- Request validation and pagination

---

### 5. **tests/integration/test_fetcher_embeddings_integration.py** ⭐ NEW
Tests BayernCloud Fetcher and Ingester with real embeddings.

**Required Environment Variables:**
- `BAYERNCLOUD_API_KEY` ✓ (from conftest.py)
- `BAYERNCLOUD_API_BASE_URL` ✓ (from conftest.py)
- `AZURE_OPENAI_API_KEY_EMB` ✓ (from conftest.py)
- `AZURE_OPENAI_ENDPOINT_EMB` ✓ (from conftest.py)
- `AZURE_DEPLOYMENT_NAME_EMB` ✓ (from conftest.py)
- `OPENSEARCH_HOST` ✓ (from conftest.py)
- `OPENSEARCH_PORT` ✓ (from conftest.py)
- `POI_MAP_INDEX` ✓ (from conftest.py)

**Running:**
```bash
pytest tests/integration/test_fetcher_embeddings_integration.py -v
```

**What it tests:**
- BayernCloud API connection
- API data requests and authentication
- Azure OpenAI embedding generation
- Batch embeddings processing
- Complete ingest pipeline (fetch → parse → embed → index)

---

## Quick Setup Steps

### Step 1: Add to `.env` file
```bash
# Copy your existing .env content and add:
cp src/.env .env  # if needed

# Add these lines:
OPENSEARCH_HOST=localhost
OPENSEARCH_PORT=9200
POI_MAP_INDEX=poi-data
POI_INDEX=tourism-data-v7
OTP_URL=http://localhost:8080/otp/routers/default/index/graphql

# Your Azure OpenAI keys (from Azure Portal):
AZURE_OPENAI_API_KEY_EMB=<KEY>
AZURE_OPENAI_ENDPOINT_EMB=<ENDPOINT>
AZURE_DEPLOYMENT_NAME_EMB=<DEPLOYMENT_NAME>
AZURE_OPENAI_API_VERSION_EMB=2024-05-01-preview
```

### Step 2: Verify Services Are Running
```bash
# Check OpenSearch
curl http://localhost:9200/

# Check OTP (if running locally)
curl -X POST http://localhost:8080/otp/routers/default/index/graphql \
  -H "Content-Type: application/json" \
  -d '{"query": "{ stops { name } }"}'
```

### Step 3: Run Integration Tests
```bash
# Run all integration tests
pytest tests/integration/ -v

# Run specific test file
pytest tests/integration/test_ingester_integration.py -v

# Run specific test
pytest tests/integration/test_ingester_integration.py::TestIngesterIntegration::test_opensearch_connection -v
```

---

## Environment Variables Summary

| Variable | File | Required For | Example |
|----------|------|--------------|---------|
| `OPENSEARCH_HOST` | conftest.py | Ingester, API Gateway tests | `localhost` |
| `OPENSEARCH_PORT` | conftest.py | Ingester, API Gateway tests | `9200` |
| `AZURE_OPENAI_API_KEY_EMB` | conftest.py | Ingester tests | `key-xxx` |
| `AZURE_OPENAI_ENDPOINT_EMB` | conftest.py | Ingester tests | `https://xxx.openai.azure.com/` |
| `AZURE_DEPLOYMENT_NAME_EMB` | conftest.py | Ingester tests | `text-embedding-3-large` |
| `AZURE_OPENAI_API_VERSION_EMB` | conftest.py | Ingester tests | `2024-05-01-preview` |
| `POI_MAP_INDEX` | conftest.py | Ingester, API Gateway | `poi-data` |
| `POI_INDEX` | conftest.py | Ingester | `tourism-data-v7` |
| `OTP_URL` | conftest.py | Trip Planner tests | `http://localhost:8080/otp/routers/default/index/graphql` |

---

## Cost Note

⚠️ **Azure OpenAI charges per API call**
- Each embedding test costs ~$0.0001
- Multiple tests = multiple calls
- You can run integration tests on-demand instead of every commit
- Use mock tests (75 tests in `tests/backend/`) for free CI/CD

---
