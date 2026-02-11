import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from opensearchpy import OpenSearch


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


# ---- Trip Planner client (microservice call) ----

def _trip_planner_url() -> str:
    return _env("TRIP_PLANNER_URL", "http://trip-planner:8001").rstrip("/")


def plan_journey_logic(start: str, end: str, date: Optional[str] = None, time: Optional[str] = None) -> str:
    """
    Calls trip-planner /plan-by-stops and returns a JSON string.
    This is the "new structure" equivalent of old OTP-direct logic.
    """
    payload: Dict[str, Any] = {
        "from_stop": start,
        "to_stop": end,
    }
    if date:
        payload["date"] = date
    if time:
        payload["time"] = time

    try:
        r = requests.post(f"{_trip_planner_url()}/plan-by-stops", json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()
        return json.dumps({"type": "journey_plan", "payload": data}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"type": "error", "where": "plan_journey", "message": str(e)}, ensure_ascii=False)



# ---- OpenSearch activities search (best-effort text search) ----

def _opensearch_client() -> OpenSearch:
    host = _env("OPENSEARCH_HOST", "opensearch")
    port = int(_env("OPENSEARCH_PORT", "9200"))
    # security disabled in your compose -> no auth, no SSL
    return OpenSearch(hosts=[{"host": host, "port": port}])


def _activity_indices() -> List[str]:
    # Try the old vector-ish index name first, then the new POI index.
    # You can override via POI_INDEX=... if you want a single source of truth.
    override = os.getenv("POI_INDEX", "tourism-data-v-working")
    return [override, "poi-data"]


def plan_activities_logic(location: str, interest: str = "") -> str:
    """
    Searches OpenSearch for POIs. This is intentionally schema-tolerant:
    - old donor index: tourism-data-v6
    - new infra index: poi-data
    """
    q = " ".join([s for s in [location, interest] if s]).strip()
    if not q:
        return json.dumps({"type": "activity_list", "location": location, "items": []}, ensure_ascii=False)

    client = _opensearch_client()
    items: List[Dict[str, Any]] = []

    for idx in _activity_indices():
        try:
            res = client.search(
                index=idx,
                body={
                    "size": 10,
                    "query": {
                        "multi_match": {
                            "query": q,
                            "fields": [
                                "name^3",
                                "description^2",
                                "tags^2",
                                "category^2",
                                "city^2",
                                "location.name^2",
                                "location.address",
                                "metadata.city^2",
                                "metadata.category^2",
                            ],
                            "type": "best_fields",
                        }
                    },
                },
            )

            for hit in res.get("hits", {}).get("hits", []):
                src = hit.get("_source", {}) or {}
                # Normalize a few common shapes
                name = src.get("name") or src.get("title") or src.get("poi_name")
                desc = src.get("description") or src.get("text") or ""
                category = src.get("category") or (src.get("metadata", {}) or {}).get("category")
                city = src.get("city") or (src.get("metadata", {}) or {}).get("city")

                items.append(
                    {
                        "name": name,
                        "category": category,
                        "city": city,
                        "description": desc,
                        "raw": src,
                    }
                )
        except Exception:
            # If an index doesn't exist or query fails, try next index
            continue

    # Deduplicate by (name, city)
    seen: set[Tuple[Optional[str], Optional[str]]] = set()
    deduped: List[Dict[str, Any]] = []
    for it in items:
        key = (it.get("name"), it.get("city"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)

    return json.dumps(
        {"type": "activity_list", "location": location, "interest": interest, "items": deduped[:10]},
        ensure_ascii=False,
    )


def find_best_city_logic(query: str) -> str:
    """
    Internal helper: pick a likely city based on activity search frequency.
    Returns a plain string city name (like old system).
    """
    if not query:
        return "Oberstdorf"

    data = json.loads(plan_activities_logic(location=query, interest=""))
    items = data.get("items", [])

    # Count occurrences of city field
    counts: Dict[str, int] = {}
    for it in items:
        city = it.get("city")
        if isinstance(city, str) and city.strip():
            counts[city.strip()] = counts.get(city.strip(), 0) + 1

    if not counts:
        # fallback: if user typed a city-ish query, just return it
        return query.split(",")[0].strip() or "Oberstdorf"

    return sorted(counts.items(), key=lambda x: x[1], reverse=True)[0][0]


# ---- Simple orchestration (keeps old "multi_step_plan" shape) ----

def plan_multiday_trip_logic(start: str, end: str, days: int = 4, interest: str = "") -> str:
    """
    Creates a coarse multi-day plan:
    - Day 1: travel start->end + some activities
    - Other days: activities in end city
    Returns a JSON string shaped like the old 'multi_step_plan'.
    """
    if not start:
        start = "Fischen"
    if not end:
        end = find_best_city_logic(query=interest or start)

    days = max(1, min(days, 14))

    steps: List[Dict[str, Any]] = []

    # Day 1 travel
    steps.append(
        {
            "type": "day_header",
            "day": 1,
            "title": f"Tag 1: Anreise {start} → {end}",
        }
    )
    steps.append(json.loads(plan_journey_logic(start=start, end=end)))

    # Day 1 activities
    steps.append(json.loads(plan_activities_logic(location=end, interest=interest)))

    # Remaining days: activities
    for d in range(2, days + 1):
        steps.append({"type": "day_header", "day": d, "title": f"Tag {d}: Aktivitäten in {end}"})
        steps.append(json.loads(plan_activities_logic(location=end, interest=interest)))

    return json.dumps(
        {
            "type": "multi_step_plan",
            "intro": f"{days}-Tage Reiseplan von {start} nach {end}" + (f" ({interest})" if interest else ""),
            "steps": steps,
        },
        ensure_ascii=False,
    )


def plan_complete_trip_logic(start: str, end: str, interest: str, num_stops: int = 2) -> str:
    """
    A simple variant that:
    - picks activities in end city
    - optionally treats 'num_stops' as how many activity blocks to include
    """
    if not start:
        start = "Fischen"
    if not end:
        end = find_best_city_logic(query=interest or start)

    num_stops = max(1, min(num_stops, 6))

    steps: List[Dict[str, Any]] = []
    steps.append({"type": "trip_header", "title": f"Kompletter Trip: {start} → {end}"})
    steps.append(json.loads(plan_journey_logic(start=start, end=end)))

    for i in range(num_stops):
        steps.append({"type": "stop_header", "stop": i + 1, "title": f"Aktivitätenblock {i+1} in {end}"})
        steps.append(json.loads(plan_activities_logic(location=end, interest=interest)))

    return json.dumps(
        {
            "type": "multi_step_plan",
            "intro": f"Kompletter Trip Plan ({interest})",
            "steps": steps,
        },
        ensure_ascii=False,
    )
