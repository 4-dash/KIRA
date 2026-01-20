import uuid
from fastapi import FastAPI

from models import PlanTripRequest, TripResponse
from otp_service import otp_graphql
from otp_queries import GQL_PLAN


app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/test/otp-gql")
def test_otp_gql(req: PlanTripRequest):
    variables = {
        "fromLat": req.from_lat,
        "fromLon": req.from_lon,
        "toLat": req.to_lat,
        "toLon": req.to_lon,
        "date": "2026-01-10",
        "time": "10:00",
    }
    return otp_graphql(GQL_PLAN, variables)


@app.post("/plan-trip", response_model=TripResponse)
def plan_trip(req: PlanTripRequest):
    variables = {
        "fromLat": req.from_lat,
        "fromLon": req.from_lon,
        "toLat": req.to_lat,
        "toLon": req.to_lon,
        "date": "2026-01-10",
        "time": "10:00",
    }

    data = otp_graphql(GQL_PLAN, variables)

    duration_sec = (
        data["data"]["plan"]["itineraries"][0]["legs"][0]["duration"]
    )

    return TripResponse(
        trip_id="otp-" + uuid.uuid4().hex[:8],
        duration_minutes=int(duration_sec / 60),
    )
