"""Tests for API Gateway utility functions and models."""
import pytest
from unittest.mock import patch, MagicMock
from typing import Any, Dict, Optional, Tuple
import sys

# Mock missing dependencies before importing
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
    _get_hit_source,
    _get_metadata_dict,
    _extract_hit_coords,
    _coalesce,
    _normalize_poi_hit,
    PoiSearchRequest,
    AddPoiRequest,
)


class TestSafeFloatApiGateway:
    """Test _safe_float utility function in API gateway."""

    def test_safe_float_valid_string(self):
        """Test conversion of valid string to float."""
        assert _safe_float("3.14") == 3.14
        assert _safe_float("42") == 42.0
        assert _safe_float("-10.5") == -10.5

    def test_safe_float_empty_string(self):
        """Test handling of empty string."""
        assert _safe_float("") is None

    def test_safe_float_none(self):
        """Test handling of None value."""
        assert _safe_float(None) is None

    def test_safe_float_invalid_string(self):
        """Test handling of invalid string."""
        assert _safe_float("abc") is None
        assert _safe_float("12.34.56") is None


class TestParseLatLonString:
    """Test _parse_lat_lon_string utility function."""

    def test_parse_valid_string(self):
        """Test parsing valid lat/lon string."""
        lat, lon = _parse_lat_lon_string("48.1351, 11.5820")
        assert lat == 48.1351
        assert lon == 11.5820

    def test_parse_string_with_whitespace(self):
        """Test parsing with extra whitespace."""
        lat, lon = _parse_lat_lon_string("  52.52  ,  13.4  ")
        assert lat == 52.52
        assert lon == 13.4

    def test_parse_invalid_string(self):
        """Test handling of invalid string."""
        lat, lon = _parse_lat_lon_string("invalid")
        assert lat is None
        assert lon is None

    def test_parse_non_string(self):
        """Test handling of non-string input."""
        lat, lon = _parse_lat_lon_string(123)
        assert lat is None
        assert lon is None

    def test_parse_none(self):
        """Test handling of None."""
        lat, lon = _parse_lat_lon_string(None)
        assert lat is None
        assert lon is None


class TestGetHitSource:
    """Test _get_hit_source utility function."""

    def test_get_source_valid(self):
        """Test extracting source from hit."""
        hit = {
            "_id": "123",
            "_source": {
                "name": "Museum",
                "lat": 48.1351
            }
        }
        source = _get_hit_source(hit)
        assert source["name"] == "Museum"
        assert source["lat"] == 48.1351

    def test_get_source_empty(self):
        """Test extracting from hit with no source."""
        hit = {"_id": "123"}
        source = _get_hit_source(hit)
        assert source == {}


class TestGetMetadataDict:
    """Test _get_metadata_dict utility function."""

    def test_get_metadata_dict_valid(self):
        """Test extracting metadata dict."""
        source = {
            "metadata": {
                "city": "Munich",
                "type": "Museum"
            }
        }
        metadata = _get_metadata_dict(source)
        assert metadata["city"] == "Munich"

    def test_get_metadata_dict_fallback(self):
        """Test fallback to metadata_dict."""
        source = {
            "metadata_dict": {
                "city": "Berlin"
            }
        }
        metadata = _get_metadata_dict(source)
        assert metadata["city"] == "Berlin"

    def test_get_metadata_dict_empty(self):
        """Test with no metadata."""
        source = {"name": "POI"}
        metadata = _get_metadata_dict(source)
        assert metadata == {}


class TestExtractHitCoords:
    """Test _extract_hit_coords utility function."""

    def test_extract_coords_from_dict_location(self):
        """Test extracting coordinates from dict location."""
        source = {
            "location": {
                "lat": 48.1351,
                "lon": 11.5820
            }
        }
        lat, lon = _extract_hit_coords(source)
        assert lat == 48.1351
        assert lon == 11.5820

    def test_extract_coords_from_string_location(self):
        """Test extracting coordinates from string location."""
        source = {
            "location": "48.1351, 11.5820"
        }
        lat, lon = _extract_hit_coords(source)
        assert lat == 48.1351
        assert lon == 11.5820

    def test_extract_coords_from_metadata(self):
        """Test extracting coordinates from metadata."""
        source = {
            "metadata": {
                "location": "52.52, 13.4"
            }
        }
        lat, lon = _extract_hit_coords(source)
        assert lat == 52.52
        assert lon == 13.4

    def test_extract_coords_top_level(self):
        """Test extracting top-level coordinates."""
        source = {
            "lat": 50.1109,
            "lon": 14.4369
        }
        lat, lon = _extract_hit_coords(source)
        assert lat == 50.1109
        assert lon == 14.4369

    def test_extract_coords_invalid(self):
        """Test with invalid or missing coordinates."""
        source = {"name": "POI"}
        lat, lon = _extract_hit_coords(source)
        assert lat is None
        assert lon is None


class TestCoalesce:
    """Test _coalesce utility function."""

    def test_coalesce_first_value(self):
        """Test returning first non-None value."""
        result = _coalesce("first", "second", "third")
        assert result == "first"

    def test_coalesce_skip_none(self):
        """Test skipping None values."""
        result = _coalesce(None, None, "third")
        assert result == "third"

    def test_coalesce_skip_empty_string(self):
        """Test skipping empty strings."""
        result = _coalesce("", "  ", "valid")
        assert result == "valid"

    def test_coalesce_all_none(self):
        """Test when all values are None."""
        result = _coalesce(None, None, None)
        assert result is None


class TestNormalizePOIHit:
    """Test _normalize_poi_hit function."""

    def test_normalize_poi_valid(self):
        """Test normalizing a valid POI hit."""
        hit = {
            "_id": "poi_123",
            "_source": {
                "name": "Museum",
                "type": "Museums",
                "location": {"lat": 48.1351, "lon": 11.5820},
                "description": "Beautiful museum",
                "city": "Munich",
                "address": "Main Street 1"
            }
        }
        
        poi = _normalize_poi_hit(hit)
        
        assert poi is not None
        assert poi["name"] == "Museum"
        assert poi["category"] == "Museums"
        assert poi["lat"] == 48.1351
        assert poi["lon"] == 11.5820
        assert poi["description"] == "Beautiful museum"
        assert poi["city"] == "Munich"

    def test_normalize_poi_missing_coords(self):
        """Test that POI without coordinates returns None."""
        hit = {
            "_id": "poi_123",
            "_source": {
                "name": "POI",
                "type": "Museum"
            }
        }
        
        poi = _normalize_poi_hit(hit)
        assert poi is None

    def test_normalize_poi_fallback_values(self):
        """Test fallback values for missing fields."""
        hit = {
            "_id": "poi_123",
            "_source": {
                "location": {"lat": 48.1351, "lon": 11.5820}
            }
        }
        
        poi = _normalize_poi_hit(hit)
        
        assert poi is not None
        assert poi["name"] == "Unbekannt"
        assert poi["category"] == "Ort"


class TestPoiSearchRequest:
    """Test PoiSearchRequest Pydantic model."""

    def test_poi_search_request_valid(self):
        """Test creating valid POI search request."""
        req = PoiSearchRequest(
            north=52.6,
            south=52.4,
            east=13.6,
            west=13.2,
            category="Museums"
        )
        
        assert req.north == 52.6
        assert req.south == 52.4
        assert req.limit == 300  # default

    def test_poi_search_request_defaults(self):
        """Test default values."""
        req = PoiSearchRequest(north=1, south=0, east=1, west=0)
        
        assert req.limit == 300
        assert req.category is None
        assert req.exclude_names == []
        assert req.trip_mode == "all"

    def test_poi_search_request_limit_validation(self):
        """Test limit range validation."""
        with pytest.raises(Exception):
            PoiSearchRequest(north=1, south=0, east=1, west=0, limit=1000)


class TestAddPoiRequest:
    """Test AddPoiRequest Pydantic model."""

    def test_add_poi_request_valid(self):
        """Test creating valid AddPOI request."""
        poi = {"name": "Museum", "lat": 48.1351}
        
        req = AddPoiRequest(poi=poi)
        
        assert req.poi == poi
        assert req.session_id is None

    def test_add_poi_request_optional_fields(self):
        """Test optional fields."""
        req = AddPoiRequest(
            poi={"name": "Museum"},
            day_index=1,
            after_step_index=3
        )
        
        assert req.day_index == 1
        assert req.after_step_index == 3
