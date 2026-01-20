import uuid
from fastapi import FastAPI
from models import PlanTripRequest, TripResponse
from otp_service import otp_graphql
from otp_queries import GQL_PLAN
from fastapi import Body, HTTPException
from datetime import datetime, timedelta
from otp_service import get_stop_coords


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

@app.post("/plan-by-stops")
def plan_by_stops(payload: dict = Body(...)):
    """
    Body example:
    {
      "from_stop": "Fischen",
      "to_stop": "Sonthofen",
      "date": "2026-01-10",   // optional
      "time": "07:30"        // optional
    }
    """
    from_stop = payload.get("from_stop")
    to_stop = payload.get("to_stop")

    if not from_stop or not to_stop:
        raise HTTPException(status_code=422, detail="from_stop and to_stop are required")

    date = payload.get("date")
    time = payload.get("time")

    # Default: tomorrow 07:30 if date/time not provided
    if not date or not time:
        tomorrow = datetime.now() + timedelta(days=1)
        dt = tomorrow.replace(hour=7, minute=30, second=0, microsecond=0)
        date = date or dt.strftime("%Y-%m-%d")
        time = time or dt.strftime("%H:%M")

    from_lat, from_lon = get_stop_coords(from_stop)
    to_lat, to_lon = get_stop_coords(to_stop)

    variables = {
        "fromLat": from_lat,
        "fromLon": from_lon,
        "toLat": to_lat,
        "toLon": to_lon,
        "date": date,
        "time": time,
    }

    # Return raw OTP result for now (no conversion yet)
    return otp_graphql(GQL_PLAN, variables)
