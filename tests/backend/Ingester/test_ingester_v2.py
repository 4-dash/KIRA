"""Tests for Ingester utility functions and RichLlamaIngestor class."""
import pytest
from unittest.mock import Mock, patch, MagicMock
import os
import json
import tempfile
import sys

# Mock missing dependencies before importing
sys.modules['shapely'] = MagicMock()
sys.modules['shapely.wkt'] = MagicMock()
sys.modules['shapely.geometry'] = MagicMock()
sys.modules['llama_index'] = MagicMock()
sys.modules['llama_index.core'] = MagicMock()
sys.modules['llama_index.core.node_parser'] = MagicMock()
sys.modules['llama_index.core.node_parser.SentenceSplitter'] = MagicMock()
sys.modules['llama_index.embeddings'] = MagicMock()
sys.modules['llama_index.embeddings.azure_openai'] = MagicMock()
sys.modules['llama_index.embeddings.azure_openai.AzureOpenAIEmbedding'] = MagicMock()
sys.modules['llama_index.vector_stores'] = MagicMock()
sys.modules['llama_index.vector_stores.opensearch'] = MagicMock()

from Backend.Ingester.ingestor_v2 import (
    safe_float,
    parse_location_string,
    clean_html,
    derive_type_from_filename,
    format_opening_hours,
    RichLlamaIngestor,
)


class TestSafeFloat:
    """Test safe_float utility function."""

    def test_safe_float_valid_string(self):
        """Test conversion of valid string to float."""
        assert safe_float("3.14") == 3.14
        assert safe_float("42") == 42.0
        assert safe_float("-10.5") == -10.5

    def test_safe_float_invalid_string(self):
        """Test handling of invalid string."""
        assert safe_float("abc") is None
        assert safe_float("12.34.56") is None

    def test_safe_float_none(self):
        """Test handling of None value."""
        assert safe_float(None) is None

    def test_safe_float_float(self):
        """Test that float is passed through."""
        assert safe_float(3.14) == 3.14


class TestParseLocationString:
    """Test parse_location_string utility function."""

    def test_parse_valid_location(self):
        """Test parsing valid comma-separated coordinates."""
        lat, lon = parse_location_string("48.1351, 11.5820")
        assert lat == 48.1351
        assert lon == 11.5820

    def test_parse_location_with_whitespace(self):
        """Test parsing coordinates with extra whitespace."""
        lat, lon = parse_location_string("  48.1351  ,  11.5820  ")
        assert lat == 48.1351
        assert lon == 11.5820

    def test_parse_location_invalid(self):
        """Test handling of invalid location strings."""
        lat, lon = parse_location_string("invalid")
        assert lat is None
        assert lon is None

    def test_parse_location_none(self):
        """Test handling of None."""
        lat, lon = parse_location_string(None)
        assert lat is None
        assert lon is None

    def test_parse_location_partial(self):
        """Test handling of incomplete location string."""
        lat, lon = parse_location_string("48.1351")
        assert lat is None
        assert lon is None


class TestCleanHtml:
    """Test clean_html utility function."""

    def test_clean_html_with_tags(self):
        """Test removal of HTML tags."""
        html = "<p>Hello <b>World</b></p>"
        result = clean_html(html)
        assert "Hello" in result
        assert "World" in result
        assert "<" not in result

    def test_clean_html_empty_string(self):
        """Test handling of empty string."""
        assert clean_html("") == ""

    def test_clean_html_none(self):
        """Test handling of None."""
        result = clean_html(None)
        assert result == ""

    def test_clean_html_plain_text(self):
        """Test handling of plain text."""
        text = "Just plain text"
        result = clean_html(text)
        assert "Just plain text" in result

    def test_clean_html_complex(self):
        """Test cleaning complex HTML."""
        html = "<div><p>Restaurant</p><br/><span>Open daily</span></div>"
        result = clean_html(html)
        assert "Restaurant" in result
        assert "Open daily" in result


class TestDeriveTypeFromFilename:
    """Test derive_type_from_filename utility function."""

    def test_derive_type_standard(self):
        """Test standard filename pattern."""
        result = derive_type_from_filename("bayerncloud_hotels.json")
        assert result == "Hotels"

    def test_derive_type_restaurants(self):
        """Test restaurants type."""
        result = derive_type_from_filename("bayerncloud_restaurants.json")
        assert result == "Restaurants"

    def test_derive_type_unknown(self):
        """Test unknown type fallback."""
        result = derive_type_from_filename("somefile.json")
        assert result == "Somefile"

    def test_derive_type_no_extension(self):
        """Test filename without extension."""
        result = derive_type_from_filename("bayerncloud_museums")
        assert result == "Museums"


class TestFormatOpeningHours:
    """Test format_opening_hours utility function."""

    def test_format_opening_hours_empty(self):
        """Test handling of empty data."""
        assert format_opening_hours(None) == ""
        assert format_opening_hours([]) == ""

    def test_format_opening_hours_dict(self):
        """Test conversion of dict to list."""
        oh_data = {
            "opens": "09:00",
            "closes": "17:00",
            "dayOfWeek": ["Monday", "Tuesday"]
        }
        result = format_opening_hours(oh_data)
        assert "09:00" in result
        assert "17:00" in result

    def test_format_opening_hours_daily(self):
        """Test formatting with all days."""
        oh_data = [{
            "opens": "08:00",
            "closes": "20:00",
            "dayOfWeek": [
                "Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday", "Sunday"
            ]
        }]
        result = format_opening_hours(oh_data)
        assert "Täglich" in result

    def test_format_opening_hours_truncate(self):
        """Test truncation of long strings."""
        oh_data = [{
            "description": "x" * 2000
        }]
        result = format_opening_hours(oh_data)
        assert len(result) <= 1000


class TestRichLlamaIngestor:
    """Test RichLlamaIngestor class."""

    @patch('Backend.Ingester.ingestor_v2.OpenSearch')
    def test_ingestor_initialization(self, mock_opensearch):
        """Test ingestor initialization."""
        ingestor = RichLlamaIngestor()
        assert ingestor.os_client is not None
        mock_opensearch.assert_called_once()

    @patch('Backend.Ingester.ingestor_v2.OpenSearch')
    def test_extract_geo_fields_with_coordinates(self, mock_opensearch):
        """Test extracting geographic fields with valid coordinates."""
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

    @patch('Backend.Ingester.ingestor_v2.OpenSearch')
    def test_extract_geo_fields_invalid(self, mock_opensearch):
        """Test extracting geographic fields with invalid data."""
        ingestor = RichLlamaIngestor()
        raw_doc = {"geo": {}}
        lat, lon, geo_line = ingestor.extract_geo_fields(raw_doc)
        assert lat is None
        assert lon is None

    @patch('Backend.Ingester.ingestor_v2.OpenSearch')
    def test_build_metadata_and_text(self, mock_opensearch):
        """Test building metadata and text from raw document."""
        ingestor = RichLlamaIngestor()
        raw_doc = {
            "@id": "poi_123",
            "name": "Test Museum",
            "description": "<p>Beautiful museum</p>",
            "address": {
                "streetAddress": "Main St",
                "postalCode": "80801",
                "addressLocality": "Munich",
                "addressCountry": "Germany"
            }
        }
        metadata, text = ingestor.build_metadata_and_text(raw_doc, "bayerncloud_museums.json")
        
        assert metadata["source_id"] == "poi_123"
        assert metadata["name"] == "Test Museum"
        assert metadata["type"] == "Museums"
        assert metadata["city"] == "Munich"
        assert "Beautiful museum" in text

    @patch('Backend.Ingester.ingestor_v2.OpenSearch')
    def test_build_map_document_valid(self, mock_opensearch):
        """Test building map document."""
        ingestor = RichLlamaIngestor()
        metadata = {
            "source_id": "poi_123",
            "name": "Museum",
            "type": "Museums",
            "city": "Munich",
            "location": "48.1351,11.5820"
        }
        text = "Beautiful museum"
        
        map_doc = ingestor.build_map_document(metadata, text)
        
        assert map_doc is not None
        assert map_doc["source_id"] == "poi_123"
        assert map_doc["location"]["lat"] == 48.1351
        assert map_doc["location"]["lon"] == 11.5820

    @patch('Backend.Ingester.ingestor_v2.OpenSearch')
    def test_build_map_document_invalid_location(self, mock_opensearch):
        """Test building map document with invalid location."""
        ingestor = RichLlamaIngestor()
        metadata = {
            "source_id": "poi_123",
            "name": "Museum",
            "location": "invalid"
        }
        text = "Beautiful museum"
        
        map_doc = ingestor.build_map_document(metadata, text)
        
        assert map_doc is None
