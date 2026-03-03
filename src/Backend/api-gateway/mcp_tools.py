"""Thin tool wrappers for api-gateway.

Goal: keep *all* business logic (routing, POI retrieval, itinerary building)
inside the trip-planner service. The gateway only orchestrates chat + forwards
tool calls.

These functions keep the original names/signatures expected by chat_ws.py.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()


TRIP_PLANNER_URL = os.getenv("TRIP_PLANNER_URL", "http://trip-planner:8001").rstrip("/")
GATEWAY_TIMEOUT_SEC = float(os.getenv("GATEWAY_TIMEOUT_SEC", "30"))


def _post(path: str, payload: Dict[str, Any]) -> str:
    url = f"{TRIP_PLANNER_URL}{path}"
    r = requests.post(url, json=payload, timeout=GATEWAY_TIMEOUT_SEC)
    r.raise_for_status()
    # Keep as string so chat_ws can forward it verbatim to the frontend
    return r.text


def _get(path: str, params: Dict[str, Any]) -> str:
    url = f"{TRIP_PLANNER_URL}{path}"
    r = requests.get(url, params=params, timeout=GATEWAY_TIMEOUT_SEC)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------------------
# Tools (same public interface as the old MCP server)
# ---------------------------------------------------------------------------


def plan_journey_logic(
    start: str,
    end: str,
    time_str: str = "tomorrow 07:30",
    start_coords_override: Optional[List[float]] = None,
    end_coords_override: Optional[List[float]] = None,
) -> str:
    """Pure A->B route."""
    return _post(
        "/journey",
        {
            "start": start,
            "end": end,
            "time_str": time_str,
            "start_coords_override": start_coords_override,
            "end_coords_override": end_coords_override,
        },
    )


def plan_activities_logic(location: str, interest: str = "") -> str:
    """POI retrieval (activity list)."""
    return _get("/activities/search", {"location": location, "interest": interest})


def plan_complete_trip_logic(
    start: str,
    end: str,
    interest: str,
    num_stops: int = 2,
    avoid_places: Optional[List[str]] = None,
) -> str:
    """Single-day multi-step plan."""
    return _post(
        "/plan/single-day",
        {
            "start": start,
            "end": end,
            "interest": interest,
            "num_stops": num_stops,
            "avoid_places": avoid_places or [],
        },
    )


def plan_multiday_trip_logic(
    start: str,
    end: str,
    days: int = 3,
    hotel_pref: str = "Hotel Unterkunft Central",
    activity_pref: str = "Wandern Natur Freizeit",
    food_pref: str = "Restaurant Gaststätte",
    culture_pref: str = "Museum",
    avoid_places: Optional[List[str]] = None,
) -> str:
    """Multi-day multi-step plan."""
    return _post(
        "/plan/multiday",
        {
            "start": start,
            "end": end,
            "days": days,
            "hotel_pref": hotel_pref,
            "activity_pref": activity_pref,
            "food_pref": food_pref,
            "culture_pref": culture_pref,
            "avoid_places": avoid_places or [],
        },
    )


def find_best_city_logic(query: str) -> str:
    """Returns a city name string (matches old behavior)."""
    raw = _post("/city/best", {"query": query})
    try:
        obj = json.loads(raw)
        return obj.get("city") or obj.get("best_city") or raw
    except Exception:
        return raw
