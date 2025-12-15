from fastapi import FastAPI
from pydantic import BaseModel

from client import TripRequest, TripResponse, call_trip_planner

app = FastAPI()

class PlanTripRequest(BaseModel):
    origin: str
    destination: str

@app.post("/plan-trip", response_model=TripResponse)
async def plan_trip(request: PlanTripRequest):
    # Forward request to Trip Planner Service (KR3.2)
    internal_request = TripRequest(**request.model_dump())
    result = await call_trip_planner(internal_request)
    return result
