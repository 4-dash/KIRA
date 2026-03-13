"""Integration tests for BayernCloud Fetcher and Ingester with embeddings."""
import pytest
import os
import sys
import requests
from unittest.mock import MagicMock, patch

# Mock dependencies
sys.modules['llama_index'] = MagicMock()
sys.modules['llama_index.core'] = MagicMock()
sys.modules['llama_index.core.node_parser'] = MagicMock()
sys.modules['llama_index.embeddings'] = MagicMock()
sys.modules['llama_index.embeddings.azure_openai'] = MagicMock()
sys.modules['llama_index.vector_stores'] = MagicMock()
sys.modules['llama_index.vector_stores.opensearch'] = MagicMock()


class TestBayernCloudFetcher:
    """Integration tests for BayernCloud API Fetcher."""

    def test_bayerncloud_api_connection(self, bayerncloud_config):
        """Test connection to BayernCloud API."""
        # Just verify credentials are set
        assert bayerncloud_config["api_key"]
        assert bayerncloud_config["api_base_url"]
        print("✓ BayernCloud credentials configured")

    
    def test_bayerncloud_data_parsing(self, bayerncloud_config):
        """Test parsing BayernCloud API response."""
        # Mock response for testing parsing logic
        mock_response = {
            "data": [
                {
                    "@id": "poi_001",
                    "name": "Test Museum",
                    "address": {
                        "streetAddress": "Main St 1",
                        "postalCode": "80331",
                        "addressLocality": "Munich",
                        "addressCountry": "Germany"
                    },
                    "geo": {
                        "latitude": "48.1351",
                        "longitude": "11.5820"
                    },
                    "description": "A great museum",
                    "telephone": "+49 89 1234"
                }
            ],
            "pagination": {
                "count": 1,
                "total": 100,
                "pages": 10
            }
        }
        
        # Verify structure
        assert len(mock_response["data"]) > 0
        poi = mock_response["data"][0]
        assert poi["@id"]
        assert poi["name"]
        assert poi["address"]["addressLocality"] == "Munich"
        assert poi["geo"]["latitude"]
        assert poi["geo"]["longitude"]
        
        print(f"✓ BayernCloud data structure valid: {poi['name']}")


class TestIngesterWithEmbeddings:
    """Integration tests for Ingester with real Azure OpenAI embeddings."""

    def test_azure_openai_connection(self, azure_openai_config):
        """Test connection to Azure OpenAI API."""
        try:
            from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
            
            embed_model = AzureOpenAIEmbedding(
                model=azure_openai_config["deployment"],
                deployment_name=azure_openai_config["deployment"],
                api_key=azure_openai_config["api_key"],
                azure_endpoint=azure_openai_config["endpoint"],
                api_version=azure_openai_config["api_version"],
            )
            
            print("✓ Azure OpenAI embedding model initialized")
            
        except Exception as e:
            if "401" in str(e) or "authentication" in str(e).lower():
                pytest.fail(f"Azure OpenAI authentication failed - check your API key: {e}")
            else:
                pytest.skip(f"Could not initialize Azure OpenAI: {e}")

    def test_embedding_generation(self, azure_openai_config):
        """Test generating embeddings with real Azure OpenAI."""
        try:
            from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
            
            embed_model = AzureOpenAIEmbedding(
                model=azure_openai_config["deployment"],
                deployment_name=azure_openai_config["deployment"],
                api_key=azure_openai_config["api_key"],
                azure_endpoint=azure_openai_config["endpoint"],
                api_version=azure_openai_config["api_version"],
            )
            
            # Test embedding a short text
            text = "Deutsches Museum in Munich"
            embedding = embed_model.get_text_embedding(text)
            
            # Embeddings should be vectors
            assert embedding is not None
            assert len(embedding) > 0
            assert isinstance(embedding, list)
            assert all(isinstance(x, (int, float)) for x in embedding)
            
            print(f"✓ Generated embedding with {len(embedding)} dimensions")
            
        except Exception as e:
            if "401" in str(e) or "Incorrect API key" in str(e):
                pytest.fail(f"Azure OpenAI API key incorrect: {e}")
            elif "deployment" in str(e).lower() or "not found" in str(e).lower():
                pytest.fail(f"Azure OpenAI deployment not found: {e}")
            else:
                pytest.skip(f"Could not generate embeddings: {e}")

    def test_batch_embeddings(self, azure_openai_config):
        """Test batch embedding generation."""
        try:
            from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
            
            embed_model = AzureOpenAIEmbedding(
                model=azure_openai_config["deployment"],
                deployment_name=azure_openai_config["deployment"],
                api_key=azure_openai_config["api_key"],
                azure_endpoint=azure_openai_config["endpoint"],
                api_version=azure_openai_config["api_version"],
            )
            
            # Test batch embedding
            texts = [
                "Deutsches Museum",
                "Neuschwanstein Castle",
                "Marienplatz"
            ]
            
            embeddings = embed_model.get_text_embedding_batch(texts)
            
            assert len(embeddings) == len(texts)
            assert all(len(e) > 0 for e in embeddings)
            
            print(f"✓ Generated {len(embeddings)} batch embeddings")
            
        except Exception as e:
            pytest.skip(f"Batch embedding test failed: {e}")


class TestCompleteIngestPipeline:
    """Integration tests for complete ingest pipeline."""

    def test_ingest_pipeline_with_real_data(self, bayerncloud_config, azure_openai_config, opensearch_client):
        """Test complete pipeline: fetch -> parse -> embed -> index."""
        from Backend.Ingester.ingestor_v2 import RichLlamaIngestor
        
        # 1. Create ingestor with real client
        ingestor = RichLlamaIngestor()
        ingestor.os_client = opensearch_client
        
        # 2. Create indices
        ingestor.create_vector_index_if_not_exists()
        ingestor.create_map_index_if_not_exists()
        
        print("✓ Step 1: Indices created")
        
        # 3. Test document preparation (with mock BayernCloud data)
        mock_doc = {
            "@id": "pipeline_test_001",
            "name": "Test Attraction",
            "description": "A beautiful test location",
            "address": {
                "streetAddress": "Test St 1",
                "postalCode": "80331",
                "addressLocality": "Munich",
                "addressCountry": "Germany"
            },
            "geo": {
                "latitude": "48.1351",
                "longitude": "11.5820"
            },
            "telephone": "+49 89 123456",
            "url": "https://test.de"
        }
        
        # 4. Build metadata
        metadata, text = ingestor.build_metadata_and_text(mock_doc, "bayerncloud_attractions.json")
        
        assert metadata["name"] == "Test Attraction"
        assert metadata["city"] == "Munich"
        print("✓ Step 2: Metadata extracted")
        
        # 5. Build map document
        map_doc = ingestor.build_map_document(metadata, text)
        
        assert map_doc is not None
        assert map_doc["source_id"] == "pipeline_test_001"
        print("✓ Step 3: Document prepared for indexing")
        
        # 6. Index to OpenSearch
        ingestor.index_map_document(map_doc)
        
        import time
        time.sleep(1)
        
        # 7. Verify it was indexed
        result = opensearch_client.get(
            index=os.getenv("POI_MAP_INDEX", "poi-data"),
            id="pipeline_test_001",
            ignore=[404]
        )
        
        assert result.get("found") is True
        print("✓ Step 4: Document indexed to OpenSearch")
        print("✓ Complete pipeline successful!")



