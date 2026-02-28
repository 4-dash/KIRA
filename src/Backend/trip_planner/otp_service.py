import os
import requests
from datetime import datetime
from fastapi import HTTPException

from models import Leg, Location
from otp_queries import GQL_STOPS


OTP_URL = os.getenv(
    "OTP_URL",
    "http://localhost:8080/otp/routers/default/index/graphql"
)
OTP_TIMEOUT_SEC = float(os.getenv("OTP_TIMEOUT_SEC", "30"))

TRANSIT_MODES = {"BUS", "RAIL", "TRAM", "SUBWAY", "TRAIN"}


def otp_graphql(query: str, variables: dict | None = None) -> dict:
    payload = {"query": query}
    if variables is not None:
        payload["variables"] = variables

    try:
        response = requests.post(
            OTP_URL,
            json=payload,
            timeout=OTP_TIMEOUT_SEC,
            headers={"Content-Type": "application/json"},
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"OTP not reachable: {e}")

    if response.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"OTP HTTP {response.status_code}: {response.text}",
        )

    data = response.json()

    if "errors" in data:
        raise HTTPException(status_code=502, detail=data["errors"])

    return data


def extract_primary_transit_leg_from_plan(data: dict) -> Leg | None:
    """
    This is your ORIGINAL functionality, unchanged in meaning.
    """
    plan = data.get("data", {}).get("plan")
    if not plan:
        return None

    itineraries = plan.get("itineraries", [])
    if not itineraries:
        return None

    itinerary = itineraries[0]

    for leg_data in itinerary.get("legs", []):
        #if leg_data.get("mode") not in TRANSIT_MODES:
            #continue

        route_info = leg_data.get("route") or {}
        carrier = (
            route_info.get("shortName")
            or route_info.get("longName")
            or "Unknown"
        )

        return Leg(
            transport_mode=leg_data["mode"],
            start_location=Location(
                name=leg_data["from"]["name"],
                latitude=leg_data["from"]["lat"],
                longitude=leg_data["from"]["lon"],
            ),
            end_location=Location(
                name=leg_data["to"]["name"],
                latitude=leg_data["to"]["lat"],
                longitude=leg_data["to"]["lon"],
            ),
            departure_time=datetime.fromtimestamp(leg_data["startTime"] / 1000),
            arrival_time=datetime.fromtimestamp(leg_data["endTime"] / 1000),
            duration_min=int(leg_data["duration"] / 60),
            carrier_number=carrier,
        )

    return None


def get_stop_coords(stop_name: str):
    data = otp_graphql(GQL_STOPS)
    for stop in data.get("data", {}).get("stops", []):
        if stop["name"] == stop_name:
            return stop["lat"], stop["lon"]

    raise HTTPException(status_code=404, detail=f"Stop not found: {stop_name}")
