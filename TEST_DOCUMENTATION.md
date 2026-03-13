# Test Suite Documentation

## Overview
The test suite contains **75 unit tests** organized into 3 test files, covering ingester utilities, trip planner data models, and API gateway functions. All tests use mocks to avoid external dependencies.

---

## 1. Ingester Tests (`tests/backend/Ingester/test_ingester_v2.py`) - 27 tests

### Purpose
Tests the data processing pipeline that ingests POI (Points of Interest) data from BayernCloud API and prepares it for storage in OpenSearch.

### Test Breakdown

#### **TestSafeFloat** (4 tests)
- **Concept**: Validates type conversion to float with error handling
- **Why**: The ingester receives data with mixed types (strings, numbers, None) and needs safe conversion
- **Tests**:
  - `test_safe_float_valid_string`: "3.14" → 3.14 ✓
  - `test_safe_float_invalid_string`: "abc" → None (not crash) ✓
  - `test_safe_float_none`: None → None ✓
  - `test_safe_float_float`: 3.14 → 3.14 ✓

#### **TestParseLocationString** (5 tests)
- **Concept**: Extracts coordinates from "lat, lon" string format
- **Why**: POI locations come as strings but need to be parsed for geo_point fields
- **Tests**:
  - `test_parse_valid_location`: "48.1351, 11.5820" → (48.1351, 11.5820) ✓
  - `test_parse_location_with_whitespace`: Handles extra spaces ✓
  - `test_parse_location_invalid`: "invalid" → (None, None) ✓
  - `test_parse_location_partial`: Missing data → (None, None) ✓

#### **TestCleanHtml** (5 tests)
- **Concept**: Removes HTML tags from descriptions
- **Why**: POI descriptions often contain HTML formatting that needs to be stripped
- **Tests**:
  - `test_clean_html_with_tags`: "<p>Hello</p>" → "Hello" ✓
  - `test_clean_html_empty_string`: "" → "" ✓
  - `test_clean_html_complex`: Nested HTML with multiple tags ✓

#### **TestDeriveTypeFromFilename** (4 tests)
- **Concept**: Extracts POI category from filename
- **Why**: Files are named like `bayerncloud_hotels.json` → type = "Hotels"
- **Tests**:
  - `test_derive_type_standard`: "bayerncloud_hotels.json" → "Hotels" ✓
  - `test_derive_type_restaurants`: "bayerncloud_restaurants.json" → "Restaurants" ✓

#### **TestFormatOpeningHours** (4 tests)
- **Concept**: Structures opening hours into readable format
- **Why**: Raw opening hours data needs to be formatted for display
- **Tests**:
  - `test_format_opening_hours_empty`: [] → "" ✓
  - `test_format_opening_hours_daily`: All 7 days → "Täglich" ✓
  - `test_format_opening_hours_truncate`: Long text → truncated at 1000 chars ✓

#### **TestRichLlamaIngestor** (6 tests)
- **Concept**: Tests the main ingestion workflow
- **Why**: Core class that orchestrates data transformation
- **Tests**:
  - `test_ingestor_initialization`: Object creates without error ✓
  - `test_extract_geo_fields_with_coordinates`: Parses geo data correctly ✓
  - `test_build_metadata_and_text`: Creates proper metadata from raw document ✓
  - `test_build_map_document_valid`: Formats data for map index ✓
  - `test_build_map_document_invalid_location`: Handles missing coordinates gracefully ✓

---

## 2. Trip Planner Tests (`tests/backend/trip_planner/test_trip_planner.py`) - 17 tests

### Purpose
Tests the data models and routing logic for the trip planning system using OTP (OpenTripPlanner) and Pydantic models.

### Test Breakdown

#### **TestLocationModel** (3 tests)
- **Concept**: Validates Location data structure
- **Why**: Locations are stored throughout the trip planning system
- **Tests**:
  - `test_location_creation`: Proper fields set ✓
  - `test_location_required_fields`: Lat/lon are mandatory ✓
  - `test_location_optional_address`: Address can be None ✓

#### **TestLegModel** (2 tests)
- **Concept**: Validates transport segment data
- **Why**: Each leg represents a bus/train/walk segment in a journey
- **Tests**:
  - `test_leg_creation`: All fields properly initialized ✓
  - `test_leg_default_type`: Type always = "leg" ✓

#### **TestActivityModel** (2 tests)
- **Concept**: Validates activity (museum, restaurant, etc.) data
- **Why**: Activities are scheduled between transport legs
- **Tests**:
  - `test_activity_creation`: Proper timing and cost tracked ✓
  - `test_activity_default_cost`: Cost defaults to 0.0 (free) ✓

#### **TestDayModel** (2 tests)
- **Concept**: Validates daily itinerary structure
- **Why**: Trips consist of multiple days with mixed activities/legs
- **Tests**:
  - `test_day_creation`: Can contain both activities and legs ✓
  - `test_day_empty_itinerary`: Can be empty before planning ✓

#### **TestTripModel** (3 tests)
- **Concept**: Validates complete trip structure
- **Why**: Root data model for entire trip
- **Tests**:
  - `test_trip_creation`: All fields initialized ✓
  - `test_trip_default_travelers`: Defaults to 1 person ✓
  - `test_trip_with_days`: Can contain multiple days ✓

#### **TestGetCoordsRobust** (2 tests)
- **Concept**: Tests OTP coordinate retrieval
- **Why**: Must handle missing stops gracefully
- **Tests**:
  - `test_get_coords_error_handling`: Returns (None, None) on error ✓
  - `test_get_coords_invalid_stop`: Unknown stops don't crash ✓

#### **TestGetOtpRoute** (2 tests)
- **Concept**: Tests OTP route planning
- **Why**: Must handle connection failures and invalid routes
- **Tests**:
  - `test_get_otp_route_basic_params`: Accepts valid parameters ✓
  - `test_get_otp_route_returns_leg_or_none`: Returns Leg or None ✓

---

## 3. API Gateway Tests (`tests/backend/opensearch/test_api_models.py`) - 31 tests

### Purpose
Tests utility functions and models for the API gateway that searches POIs and normalizes search results.

### Test Breakdown

#### **TestSafeFloatApiGateway** (4 tests)
- **Concept**: Same as ingester but in API context
- **Why**: API receives float values from clients with mixed types
- **Tests**: Valid/invalid/empty string conversions ✓

#### **TestParseLatLonString** (5 tests)
- **Concept**: Parse coordinates from API requests
- **Why**: API clients send coordinates as strings
- **Tests**: Valid parsing, whitespace handling, error cases ✓

#### **TestGetHitSource** (2 tests)
- **Concept**: Extracts OpenSearch hit data
- **Why**: OpenSearch returns nested JSON structure
- **Tests**:
  - `test_get_source_valid`: Extracts _source field ✓
  - `test_get_source_empty`: Handles missing source ✓

#### **TestGetMetadataDict** (3 tests)
- **Concept**: Finds metadata in nested structures
- **Why**: Metadata can be under `metadata` or `metadata_dict` keys
- **Tests**:
  - `test_get_metadata_dict_valid`: Extracts from `metadata` ✓
  - `test_get_metadata_dict_fallback`: Falls back to `metadata_dict` ✓
  - `test_get_metadata_dict_empty`: Returns {} if missing ✓

#### **TestExtractHitCoords** (5 tests)
- **Concept**: Finds coordinates in multiple possible locations
- **Why**: OpenSearch hits can have coordinates in different formats
- **Tests**:
  - `test_extract_coords_from_dict_location`: {lat, lon} format ✓
  - `test_extract_coords_from_string_location`: "lat, lon" string ✓
  - `test_extract_coords_from_metadata`: Inside metadata field ✓
  - `test_extract_coords_top_level`: At document root ✓
  - `test_extract_coords_invalid`: Returns (None, None) on failure ✓

#### **TestCoalesce** (4 tests)
- **Concept**: Returns first non-empty value from list
- **Why**: API needs fallback values (e.g., name or title)
- **Tests**:
  - `test_coalesce_first_value`: Returns first non-None ✓
  - `test_coalesce_skip_none`: Skips None values ✓
  - `test_coalesce_skip_empty_string`: Skips "" and whitespace ✓
  - `test_coalesce_all_none`: Returns None if all empty ✓

#### **TestNormalizePOIHit** (3 tests)
- **Concept**: Transforms raw OpenSearch hit into API response
- **Why**: API clients need consistently formatted POI objects
- **Tests**:
  - `test_normalize_poi_valid`: Complete POI → clean response ✓
  - `test_normalize_poi_missing_coords`: No coordinates → None ✓
  - `test_normalize_poi_fallback_values`: Uses defaults for missing fields ✓

#### **TestPoiSearchRequest** (3 tests)
- **Concept**: Validates bounding box search parameters
- **Why**: API must validate client requests
- **Tests**:
  - `test_poi_search_request_valid`: Accepts valid bounds ✓
  - `test_poi_search_request_defaults`: Limit = 300 by default ✓
  - `test_poi_search_request_limit_validation`: Rejects limit > 500 ✓

#### **TestAddPoiRequest** (2 tests)
- **Concept**: Validates POI addition parameters
- **Why**: API must validate requests before processing
- **Tests**:
  - `test_add_poi_request_valid`: Accepts valid request ✓
  - `test_add_poi_request_optional_fields`: Optional fields work ✓

---

## Mock Tests vs Integration Tests: Benefits & Tradeoffs

### **Benefits of Mock Tests** ✓
1. **Speed**: Run in milliseconds, no external services needed
2. **Reliability**: No network dependency = no flaky tests
3. **Isolation**: Test one component in isolation
4. **Cost**: Free - no API calls, no paid services
5. **CI/CD**: Can run offline, no infrastructure required
6. **Fast feedback**: Developers get instant results
7. **Coverage**: Easy to test edge cases and error paths

### **Limitations of Mock Tests** ✗
1. **Not testing real behavior**: Mocked objects don't fail like real services
2. **Integration bugs invisible**: Two services might not work together
3. **Version mismatches**: Mocks won't catch API schema changes
4. **Performance unknown**: Mocks are fast; real API might be slow

### **Benefits of Integration Tests** ✓
1. **Real behavior**: Actually tests against real services
2. **Catches integration bugs**: Services actually talk to each other
3. **API contract validation**: Detects breaking changes early
4. **Performance profiling**: Reveals actual latency issues
5. **Full pipeline**: Tests the complete flow

### **Limitations of Integration Tests** ✗
1. **Slow**: Can take seconds or minutes per test
2. **Flaky**: Network issues cause false failures
3. **Expensive**: API calls cost money (Azure OpenAI, etc.)
4. **Infrastructure required**: Need running services
5. **Hard to test edge cases**: Can't easily simulate errors
6. **CI/CD complexity**: Need test environments configured

---

## Recommendation: Layered Approach

### **For Development & CI/CD** (use unit + mocks)
```
Fast feedback loop:
✓ Unit tests (mocks)     - 75 tests run in < 1 second
✓ Fast iteration
✓ Run on every commit
```

### **For Pre-Production** (add integration tests)
```
Sanity checks:
✓ Unit tests (mocks)     - < 1 second
✓ Integration tests      - Real API calls, slower but comprehensive
✓ Run before deployment
```

### **For Production Monitoring** (runtime checks)
```
Health checks:
✓ Smoke tests against live APIs
✓ Alerts on actual failures
```

---

## Your Setup Assessment

**Current state**: ✓ Excellent unit tests with mocks
- Good coverage of edge cases and parsing logic
- Fast, reliable, cost-free
- Perfect for preventing regressions

**What's missing**: Integration tests
- Should test ingester with real OpenSearch + Azure embeddings
- Should test trip planner against real OTP service
- Should run periodically but not on every commit

**Recommendation**: Keep these mock tests as-is. Add integration tests in a separate `tests/integration/` folder that:
1. Run only on-demand or in staging environment
2. Use real OpenSearch + Azure OpenAI (costs money, so not on every commit)
3. Validate end-to-end flows

This gives you **fast feedback in dev** + **real validation before production**.
