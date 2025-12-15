from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class PlanTripRequest(BaseModel):
    origin: str
    destination: str

class TripResponse(BaseModel):
    trip_id: str
    origin: str
    destination: str
    duration_minutes: int

@app.post("/plan-trip", response_model=TripResponse)
async def plan_trip(request: PlanTripRequest):

    return TripResponse(
        trip_id="mock-trip-001",
        origin=request.origin,
        destination=request.destination,
        duration_minutes=42
    )
