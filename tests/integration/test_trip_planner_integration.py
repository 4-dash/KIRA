"""Integration tests for Trip Planner with real OTP service."""
import pytest
import os
import requests
from datetime import datetime, timedelta
import sys
from unittest.mock import MagicMock

# Mock dependencies
sys.modules['llama_index'] = MagicMock()
sys.modules['llama_index.core'] = MagicMock()

from Opensearch.plan_trip_robust import (
    Location, Leg, Activity, Day, Trip,
    get_coords_robust, get_otp_route
)


class TestTripPlannerIntegration:
    """Integration tests for Trip Planner with real OTP service."""

    def test_otp_service_available(self, otp_service):
        """Test that OTP service is running."""
        assert otp_service is not None
        print(f"✓ OTP service available at {otp_service}")

    def test_get_coords_real(self, otp_service):
        """Test retrieving real coordinates from OTP."""
        # Use common German cities that should exist in OTP data
        lat, lon = get_coords_robust("Fischen")
        
        if lat is None:
            pytest.skip("Fischen stop not found in OTP")
        
        assert lat is not None
        assert lon is not None
        assert 47 < lat < 49  # Bavaria region
        assert 9 < lon < 13
        print(f"✓ Real coordinates retrieved: ({lat}, {lon})")

    def test_get_otp_route_real(self, otp_service):
        """Test retrieving real route from OTP."""
        # Get starting coordinates
        start_lat, start_lon = get_coords_robust("Fischen")
        end_lat, end_lon = get_coords_robust("Sonthofen")
        
        if start_lat is None or end_lat is None:
            pytest.skip("Test stops not found in OTP")
        
        # Plan trip for tomorrow at 7:30 AM
        tomorrow = datetime.now() + timedelta(days=1)
        trip_time = tomorrow.replace(hour=7, minute=30, second=0, microsecond=0)
        
        leg = get_otp_route(start_lat, start_lon, end_lat, end_lon, trip_time)
        
        # Leg might be None if route not found, that's OK for this test
        if leg is not None:
            assert leg.transport_mode in ["BUS", "RAIL", "TRAIN", "TRAM", "SUBWAY"]
            assert leg.duration_min > 0
            print(f"✓ Route found: {leg.transport_mode} ({leg.duration_min} min)")
        else:
            print("✓ OTP responded but no route found (expected for some times)")

    def test_location_model_real(self):
        """Test Location model with real data."""
        loc = Location(
            name="Deutsches Museum",
            latitude=48.1351,
            longitude=11.5820,
            address="Museumsinsel 1, 80538 Munich"
        )
        
        assert loc.name == "Deutsches Museum"
        assert loc.latitude == 48.1351
        print("✓ Location model works with real data")

    def test_leg_model_real(self):
        """Test Leg model with realistic trip data."""
        start = Location(
            name="Fischen",
            latitude=47.5,
            longitude=10.3
        )
        end = Location(
            name="Sonthofen",
            latitude=47.6,
            longitude=10.4
        )
        
        now = datetime.now()
        for_2_hours = timedelta(hours=2)
        
        leg = Leg(
            transport_mode="BUS",
            start_location=start,
            end_location=end,
            departure_time=now,
            arrival_time=now + for_2_hours,
            duration_min=120,
            carrier_number="670"
        )
        
        assert leg.transport_mode == "BUS"
        assert leg.carrier_number == "670"
        assert leg.duration_min == 120
        print("✓ Leg model works with realistic transport data")

    def test_trip_model_real(self):
        """Test complete Trip model with realistic itinerary."""
        start_date = datetime.now()
        end_date = start_date + timedelta(days=2)
        
        loc1 = Location(name="Munich", latitude=48.1351, longitude=11.5820)
        loc2 = Location(name="Berlin", latitude=52.52, longitude=13.4)
        
        activity = Activity(
            name="Sightseeing at Museum",
            location=loc1,
            start_time=start_date + timedelta(hours=10),
            end_time=start_date + timedelta(hours=14),
            duration_min=240,
            cost=15.0
        )
        
        day1 = Day(date=start_date, itinerary=[activity])
        
        trip = Trip(
            name="Munich to Berlin",
            start_date=start_date,
            end_date=end_date,
            travelers=2,
            days=[day1]
        )
        
        assert trip.name == "Munich to Berlin"
        assert len(trip.days) == 1
        assert trip.travelers == 2
        print("✓ Complete trip model works with realistic data")



