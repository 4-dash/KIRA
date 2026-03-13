"""Tests for Trip Planner data models and core functions."""
import pytest
from datetime import datetime, timedelta
from uuid import UUID
import sys
from unittest.mock import MagicMock

# Mock missing dependencies before importing
sys.modules['llama_index'] = MagicMock()
sys.modules['llama_index.core'] = MagicMock()
sys.modules['llama_index.core.node_parser'] = MagicMock()
sys.modules['llama_index.llms'] = MagicMock()
sys.modules['llama_index.llms.azure_openai'] = MagicMock()
sys.modules['llama_index.embeddings'] = MagicMock()
sys.modules['llama_index.embeddings.azure_openai'] = MagicMock()
sys.modules['requests'] = MagicMock()

from Opensearch.plan_trip_robust import (
    Location,
    Leg,
    Activity,
    Day,
    Trip,
    get_coords_robust,
    get_otp_route,
)


class TestLocationModel:
    """Test Location Pydantic model."""

    def test_location_creation(self):
        """Test creating a valid location."""
        loc = Location(
            name="Munich",
            latitude=48.1351,
            longitude=11.5820,
            address="Marienplatz 8"
        )
        assert loc.name == "Munich"
        assert loc.latitude == 48.1351
        assert loc.longitude == 11.5820
        assert loc.address == "Marienplatz 8"

    def test_location_required_fields(self):
        """Test that required fields are enforced."""
        with pytest.raises(Exception):
            Location(name="Munich")  # Missing latitude/longitude

    def test_location_optional_address(self):
        """Test address is optional."""
        loc = Location(name="Berlin", latitude=52.52, longitude=13.4)
        assert loc.address is None


class TestLegModel:
    """Test Leg Pydantic model."""

    def test_leg_creation(self):
        """Test creating a valid leg."""
        start = Location(name="Munich", latitude=48.1351, longitude=11.5820)
        end = Location(name="Berlin", latitude=52.52, longitude=13.4)
        departure = datetime.now()
        arrival = departure + timedelta(hours=6)
        
        leg = Leg(
            transport_mode="TRAIN",
            start_location=start,
            end_location=end,
            departure_time=departure,
            arrival_time=arrival,
            duration_min=360,
            carrier_number="ICE 123"
        )
        
        assert leg.transport_mode == "TRAIN"
        assert leg.carrier_number == "ICE 123"
        assert leg.type == "leg"
        assert isinstance(leg.id, UUID)

    def test_leg_default_type(self):
        """Test that leg type defaults to 'leg'."""
        start = Location(name="A", latitude=0, longitude=0)
        end = Location(name="B", latitude=1, longitude=1)
        
        leg = Leg(
            transport_mode="BUS",
            start_location=start,
            end_location=end,
            departure_time=datetime.now(),
            arrival_time=datetime.now() + timedelta(hours=2),
            duration_min=120
        )
        
        assert leg.type == "leg"


class TestActivityModel:
    """Test Activity Pydantic model."""

    def test_activity_creation(self):
        """Test creating a valid activity."""
        loc = Location(name="Museum", latitude=48.1351, longitude=11.5820)
        start = datetime.now()
        end = start + timedelta(hours=3)
        
        activity = Activity(
            name="Visit Museum",
            description="Beautiful art museum",
            location=loc,
            start_time=start,
            end_time=end,
            duration_min=180,
            cost=15.0
        )
        
        assert activity.name == "Visit Museum"
        assert activity.description == "Beautiful art museum"
        assert activity.type == "activity"
        assert activity.cost == 15.0

    def test_activity_default_cost(self):
        """Test that cost defaults to 0.0."""
        loc = Location(name="Park", latitude=0, longitude=0)
        activity = Activity(
            name="Walk in park",
            location=loc,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(hours=1),
            duration_min=60
        )
        
        assert activity.cost == 0.0


class TestDayModel:
    """Test Day Pydantic model."""

    def test_day_creation(self):
        """Test creating a valid day."""
        loc = Location(name="Munich", latitude=48.1351, longitude=11.5820)
        activity = Activity(
            name="Sightseeing",
            location=loc,
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(hours=4),
            duration_min=240
        )
        
        day = Day(
            date=datetime.now(),
            itinerary=[activity],
            notes="Great day!"
        )
        
        assert len(day.itinerary) == 1
        assert day.notes == "Great day!"

    def test_day_empty_itinerary(self):
        """Test day with empty itinerary."""
        day = Day(date=datetime.now())
        assert day.itinerary == []
        assert day.notes is None


class TestTripModel:
    """Test Trip Pydantic model."""

    def test_trip_creation(self):
        """Test creating a valid trip."""
        start_date = datetime.now()
        end_date = start_date + timedelta(days=3)
        
        trip = Trip(
            name="Munich Weekend",
            start_date=start_date,
            end_date=end_date,
            travelers=2
        )
        
        assert trip.name == "Munich Weekend"
        assert trip.travelers == 2
        assert trip.version == 1
        assert isinstance(trip.trip_id, UUID)

    def test_trip_default_travelers(self):
        """Test that travelers defaults to 1."""
        trip = Trip(
            name="Solo Trip",
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=1)
        )
        
        assert trip.travelers == 1

    def test_trip_with_days(self):
        """Test creating trip with multiple days."""
        start_date = datetime.now()
        
        day1 = Day(date=start_date)
        day2 = Day(date=start_date + timedelta(days=1))
        
        trip = Trip(
            name="Multi-day Trip",
            start_date=start_date,
            end_date=start_date + timedelta(days=2),
            days=[day1, day2]
        )
        
        assert len(trip.days) == 2


class TestGetCoordsRobust:
    """Test get_coords_robust function."""

    @pytest.mark.asyncio
    def test_get_coords_error_handling(self):
        """Test robust coordinate retrieval."""
        # This test mocks the HTTP request to test error handling
        lat, lon = get_coords_robust(None)
        assert lat is None
        assert lon is None

    @pytest.mark.asyncio
    def test_get_coords_invalid_stop(self):
        """Test behavior with non-existent stop."""
        lat, lon = get_coords_robust("NonExistentStop123456")
        # Should return None, None when stop not found
        assert lat is None
        assert lon is None


class TestGetOtpRoute:
    """Test get_otp_route function."""

    @pytest.mark.asyncio
    def test_get_otp_route_basic_params(self):
        """Test basic OTP route retrieval function exists."""
        # Test that function can be called with valid parameters
        from_lat, from_lon = 48.1351, 11.5820
        to_lat, to_lon = 50.1109, 14.4369
        departure = datetime.now() + timedelta(days=1)
        
        # Function should not raise with valid params
        result = get_otp_route(from_lat, from_lon, to_lat, to_lon, departure)
        # Result may be None if service is down, but should not raise
        assert result is None or isinstance(result, Leg)

    @pytest.mark.asyncio
    def test_get_otp_route_returns_leg_or_none(self):
        """Test that get_otp_route returns Leg or None."""
        result = get_otp_route(0, 0, 1, 1, datetime.now())
        assert result is None or isinstance(result, Leg)
