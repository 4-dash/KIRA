from datetime import datetime
from typing import List, Optional, Literal, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, ConfigDict


# ==========================
# DOMAIN / STORAGE MODELS
# ==========================

class Location(BaseModel):
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None


class Leg(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: Literal["leg"] = "leg"
    transport_mode: str
    start_location: Location
    end_location: Location
    departure_time: datetime
    arrival_time: datetime
    duration_min: int
    carrier_number: Optional[str] = None


class Activity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: Literal["activity"] = "activity"
    name: str
    description: Optional[str] = None
    location: Location
    start_time: datetime
    end_time: datetime
    duration_min: int
    cost: Optional[float] = 0.0


class Day(BaseModel):
    date: datetime
    itinerary: List[Union[Activity, Leg]] = []
    notes: Optional[str] = None


class Trip(BaseModel):
    trip_id: UUID = Field(default_factory=uuid4)
    version: int = 1
    name: str
    start_date: datetime
    end_date: datetime
    travelers: int = 1
    days: List[Day] = []
    created: datetime = Field(default_factory=datetime.now)
    model_config = ConfigDict(use_enum_values=True)


# ==========================
# MINIMAL API MODELS
# ==========================

class PlanTripRequest(BaseModel):
    from_lat: float = Field(..., ge=-90, le=90)
    from_lon: float = Field(..., ge=-180, le=180)
    to_lat: float = Field(..., ge=-90, le=90)
    to_lon: float = Field(..., ge=-180, le=180)


class TripResponse(BaseModel):
    trip_id: str
    duration_minutes: int
