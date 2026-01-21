import os
import httpx
from pydantic import BaseModel

TRIP_PLANNER_URL = os.getenv("TRIP_PLANNER_URL", "http://trip-planner:8001")

class TripRequest(BaseModel):
    origin: str
    destination: str

class TripResponse(BaseModel):
    trip_id: str
    origin: str
    destination: str
    duration_minutes: int

async def call_trip_planner(req: TripRequest) -> TripResponse:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{TRIP_PLANNER_URL}/plan-trip",
            json=req.model_dump()
        )
        response.raise_for_status()
        return TripResponse(**response.json())
