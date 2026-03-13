"""Integration tests for Ingester with real OpenSearch and Azure OpenAI."""
import pytest
import os
import json
import tempfile
from unittest.mock import MagicMock
import sys

# Mock llama_index if needed for import
sys.modules['llama_index'] = MagicMock()
sys.modules['llama_index.core'] = MagicMock()
sys.modules['llama_index.core.node_parser'] = MagicMock()
sys.modules['llama_index.embeddings'] = MagicMock()
sys.modules['llama_index.embeddings.azure_openai'] = MagicMock()
sys.modules['llama_index.vector_stores'] = MagicMock()
sys.modules['llama_index.vector_stores.opensearch'] = MagicMock()

from Backend.Ingester.ingestor_v2 import RichLlamaIngestor, safe_float, parse_location_value


class TestIngesterIntegration:
    """Integration tests for RichLlamaIngestor with real OpenSearch."""

    def test_opensearch_connection(self, opensearch_client):
        """Test that we can connect to OpenSearch."""
        info = opensearch_client.info()
        assert "cluster_name" in info or "version" in info
        print("✓ OpenSearch connected successfully")

    def test_ingestor_creates_indices(self, opensearch_client):
        """Test that ingestor can create vector and map indices."""
        ingestor = RichLlamaIngestor()
        
        # Override client with real one
        ingestor.os_client = opensearch_client
        
        # Should not raise
        ingestor.create_vector_index_if_not_exists()
        ingestor.create_map_index_if_not_exists()
        
        print("✓ Indices created successfully")

    def test_index_map_document(self, opensearch_client):
        """Test indexing a real document to OpenSearch."""
        ingestor = RichLlamaIngestor()
        ingestor.os_client = opensearch_client
        
        # Create indices first
        ingestor.create_map_index_if_not_exists()
        
        # Index a test document
        map_doc = {
            "source_id": "test_poi_001",
            "name": "Test Museum",
            "type": "Museums",
            "description": "A test museum",
            "city": "Munich",
            "location": {"lat": 48.1351, "lon": 11.5820},
            "lat": 48.1351,
            "lon": 11.5820,
        }
        
        ingestor.index_map_document(map_doc)
        
        # Verify document was indexed (with small delay for refresh)
        import time
        time.sleep(1)
        
        result = opensearch_client.get(
            index=os.getenv("POI_MAP_INDEX", "poi-data"),
            id="test_poi_001",
            ignore=[404]
        )
        
        assert result.get("found") is True
        assert result["_source"]["name"] == "Test Museum"
        print("✓ Document indexed to OpenSearch successfully")

    def test_extract_geo_fields_real(self, opensearch_client):
        """Test extracting geo fields with real data."""
        ingestor = RichLlamaIngestor()
        
        raw_doc = {
            "geo": {
                "latitude": "48.1351",
                "longitude": "11.5820"
            }
        }
        
        lat, lon, geo_line = ingestor.extract_geo_fields(raw_doc)
        
        assert lat == 48.1351
        assert lon == 11.5820
        print(f"✓ Geo fields extracted: ({lat}, {lon})")

    def test_build_metadata_real(self, opensearch_client):
        """Test building metadata with realistic data."""
        ingestor = RichLlamaIngestor()
        
        raw_doc = {
            "@id": "poi_real_001",
            "name": "Deutsches Museum",
            "description": "<p>A world-class science and technology museum</p>",
            "address": {
                "streetAddress": "Museumsinsel 1",
                "postalCode": "80538",
                "addressLocality": "Munich",
                "addressCountry": "Germany"
            },
            "telephone": "+49 89 2179",
            "url": "https://deutsches-museum.de"
        }
        
        metadata, text = ingestor.build_metadata_and_text(raw_doc, "bayerncloud_museums.json")
        
        assert metadata["name"] == "Deutsches Museum"
        assert metadata["city"] == "Munich"
        assert "science" in text.lower()
        assert "<" not in text  # HTML removed
        print("✓ Metadata built successfully from realistic data")


