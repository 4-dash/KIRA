"""Integration tests for API Gateway with real OpenSearch."""
import pytest
import os
import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules['llama_index'] = MagicMock()
sys.modules['llama_index.core'] = MagicMock()
sys.modules['llama_index.core.node_parser'] = MagicMock()
sys.modules['llama_index.llms'] = MagicMock()
sys.modules['llama_index.llms.azure_openai'] = MagicMock()
sys.modules['llama_index.embeddings'] = MagicMock()
sys.modules['llama_index.embeddings.azure_openai'] = MagicMock()
sys.modules['agent_server'] = MagicMock()

from Backend.api import (
    _safe_float,
    _parse_lat_lon_string,
    _normalize_poi_hit,
    _extract_hit_coords,
    PoiSearchRequest,
)


class TestAPIGatewayIntegration:
    """Integration tests for API Gateway with real OpenSearch."""

    def test_opensearch_poi_search(self, opensearch_client):
        """Test searching for POIs in real OpenSearch."""
        # Index a test POI first
        poi_map_index = os.getenv("POI_MAP_INDEX", "poi-data")
        
        test_poi = {
            "name": "Integration Test Museum",
            "type": "Museums",
            "description": "A test POI for integration testing",
            "city": "Munich",
            "location": {"lat": 48.1351, "lon": 11.5820},
            "lat": 48.1351,
            "lon": 11.5820,
        }
        
        opensearch_client.index(
            index=poi_map_index,
            id="integration_test_poi_001",
            body=test_poi,
            refresh=True
        )
        
        # Search for it
        response = opensearch_client.search(
            index=poi_map_index,
            body={
                "query": {"match": {"name": "Museum"}},
                "size": 10
            }
        )
        
        assert response["hits"]["total"]["value"] > 0
        print(f"✓ Found {response['hits']['total']['value']} POIs in OpenSearch")

    def test_normalize_poi_hit_integration(self, opensearch_client):
        """Test normalizing a real OpenSearch hit."""
        # Index a test POI
        poi_map_index = os.getenv("POI_MAP_INDEX", "poi-data")
        
        test_poi = {
            "source_id": "integration_test_002",
            "name": "Marienplatz",
            "type": "Landmarks",
            "description": "Central square in Munich",
            "city": "Munich",
            "location": {"lat": 48.1374, "lon": 11.5755},
            "lat": 48.1374,
            "lon": 11.5755,
            "address": "Marienplatz 8, 80331 Munich"
        }
        
        opensearch_client.index(
            index=poi_map_index,
            id="marienplatz_test",
            body=test_poi,
            refresh=True
        )
        
        # Get it back as a hit
        response = opensearch_client.get(
            index=poi_map_index,
            id="marienplatz_test"
        )
        
        hit = {"_id": response["_id"], "_source": response["_source"]}
        
        # Normalize it
        poi = _normalize_poi_hit(hit)
        
        assert poi is not None
        assert poi["name"] == "Marienplatz"
        assert poi["category"] == "Landmarks"
        assert poi["lat"] == 48.1374
        assert poi["lon"] == 11.5755
        print(f"✓ POI normalized successfully: {poi['name']}")

    def test_extract_hit_coords_real(self):
        """Test extracting coordinates from various real formats."""
        # Dict format
        source_dict = {
            "location": {"lat": 52.52, "lon": 13.4}
        }
        lat, lon = _extract_hit_coords(source_dict)
        assert lat == 52.52
        assert lon == 13.4
        
        # String format
        source_string = {
            "location": "52.52, 13.4"
        }
        lat, lon = _extract_hit_coords(source_string)
        assert lat == 52.52
        assert lon == 13.4
        
        # Top-level format
        source_toplevel = {
            "lat": 50.1109,
            "lon": 14.4369
        }
        lat, lon = _extract_hit_coords(source_toplevel)
        assert lat == 50.1109
        assert lon == 14.4369
        
        print("✓ Coordinates extracted from all formats")

    def test_poi_search_request_validation(self):
        """Test POI search request validation."""
        # Valid request
        req = PoiSearchRequest(
            north=52.6,
            south=52.4,
            east=13.6,
            west=13.2,
            limit=100,
            category="Museums"
        )
        
        assert req.north == 52.6
        assert req.limit == 100
        print("✓ Valid POI search request accepted")
        
        # Request with defaults
        req2 = PoiSearchRequest(
            north=52.6,
            south=52.4,
            east=13.6,
            west=13.2
        )
        
        assert req2.limit == 300  # default
        assert req2.trip_mode == "all"  # default
        print("✓ POI search request defaults applied correctly")

    def test_poi_search_pagination(self, opensearch_client):
        """Test POI search with pagination."""
        poi_map_index = os.getenv("POI_MAP_INDEX", "poi-data")
        
        # Index multiple test POIs
        for i in range(5):
            poi = {
                "name": f"Test Attraction {i}",
                "type": "Attractions",
                "city": "Munich",
                "location": {"lat": 48.1 + i*0.01, "lon": 11.5 + i*0.01},
                "lat": 48.1 + i*0.01,
                "lon": 11.5 + i*0.01,
            }
            opensearch_client.index(
                index=poi_map_index,
                id=f"attraction_test_{i}",
                body=poi,
                refresh=True
            )
        
        # Search with limit
        response = opensearch_client.search(
            index=poi_map_index,
            body={
                "query": {"match": {"type": "Attractions"}},
                "size": 3
            }
        )
        
        assert len(response["hits"]["hits"]) <= 3
        print(f"✓ Pagination working: got {len(response['hits']['hits'])} results with limit 3")



