import httpx
from pydantic import BaseModel

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
            "http://localhost:8001/plan-trip",
            json=req.model_dump()
        )
        response.raise_for_status()
        return TripResponse(**response.json())
