from __future__ import annotations

import ast
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestsHttpConnection
from openai import AzureOpenAI

from otp_service import otp_graphql


load_dotenv()


def log(msg: str) -> None:
    sys.stderr.write(f"[TRIP-PLANNER] {msg}\n")
    sys.stderr.flush()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OTP_URL = os.getenv("OTP_URL", "http://otp:8080/otp/routers/default/index/graphql")

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "opensearch")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))

# In compose you already have OPENSEARCH_POI_INDEX
POI_INDEX = os.getenv("OPENSEARCH_POI_INDEX", os.getenv("POI_INDEX", "tourism-data-v7"))

EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))

AZURE_EMBED_ENDPOINT = os.getenv("AZURE_EMBED_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT"))
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_EMBED_DEPLOYMENT = os.getenv("AZURE_DEPLOYMENT_NAME_EMBED", os.getenv("AZURE_DEPLOYMENT_NAME", "text-embedding-3-large"))
AZURE_EMBED_API_VERSION = os.getenv("AZURE_API_VERSION_EMBED", os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def calculate_distance(lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float]) -> float:
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 99999.0
    R = 6371.0
    dLat = radians(lat2 - lat1)
    dLon = radians(lon2 - lon1)
    a = sin(dLat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dLon / 2) ** 2
    c = 2 * asin(sqrt(a))
    return R * c


def check_is_open(opening_data: Any, query_dt: datetime) -> bool:
    if not opening_data:
        return True
    try:
        rules = ast.literal_eval(opening_data) if isinstance(opening_data, str) else opening_data
    except Exception:
        return True

    current_date_str = query_dt.strftime("%Y-%m-%d")
    current_time_str = query_dt.strftime("%H:%M")
    days_map = {
        0: "https://schema.org/Monday",
        1: "https://schema.org/Tuesday",
        2: "https://schema.org/Wednesday",
        3: "https://schema.org/Thursday",
        4: "https://schema.org/Friday",
        5: "https://schema.org/Saturday",
        6: "https://schema.org/Sunday",
    }
    today_url = days_map[query_dt.weekday()]

    for rule in rules:
        valid_from = rule.get("validFrom", "1900-01-01")
        valid_through = rule.get("validThrough", "2099-12-31")
        if not (valid_from <= current_date_str <= valid_through):
            continue
        days = rule.get("dayOfWeek", [])
        if today_url in days:
            opens = rule.get("opens", "00:00")
            closes = rule.get("closes", "23:59") or "23:59"
            if opens <= current_time_str <= closes:
                return True
    return False


def _encode_value(value: int, result: List[str]) -> None:
    value = ~(value << 1) if value < 0 else (value << 1)
    while value >= 0x20:
        result.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    result.append(chr(value + 63))


def encode_polyline(points: List[List[float]]) -> str:
    result: List[str] = []
    last_lat = 0
    last_lon = 0
    for lat_f, lon_f in points:
        lat = int(round(lat_f * 1e5))
        lon = int(round(lon_f * 1e5))
        d_lat = lat - last_lat
        d_lon = lon - last_lon
        _encode_value(d_lat, result)
        _encode_value(d_lon, result)
        last_lat = lat
        last_lon = lon
    return "".join(result)


def parse_time_str(time_str: str) -> datetime:
    # Only implements the behavior used in agent_server: "tomorrow HH:MM".
    dt = datetime.now()
    if "tomorrow" in (time_str or "").lower():
        dt = dt + timedelta(days=1)
        parts = (time_str or "").split()
        if parts and ":" in parts[-1]:
            h, m = map(int, parts[-1].split(":")[:2])
            dt = dt.replace(hour=h, minute=m, second=0, microsecond=0)
        else:
            dt = dt.replace(hour=7, minute=30, second=0, microsecond=0)
    return dt


def get_coords(place_name: str) -> Tuple[Optional[float], Optional[float]]:
    # Nominatim fix from agent_server.py
    try:
        headers = {"User-Agent": "KIRA-TripPlanner/1.0"}
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={place_name}"
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        log(f"Nominatim error for '{place_name}': {e}")
    return None, None


# ---------------------------------------------------------------------------
# OTP Route
# ---------------------------------------------------------------------------


GQL_PLAN_ULTRA_LAZY = """
query PlanTrip($fromLat: Float!, $fromLon: Float!, $toLat: Float!, $toLon: Float!, $date: String!, $time: String!) {
  plan(
    from: {lat: $fromLat, lon: $fromLon}
    to: {lat: $toLat, lon: $toLon}
    date: $date
    time: $time
    numItineraries: 3
    transportModes: [{mode: TRANSIT}, {mode: WALK}]
    walkReluctance: 500.0
    waitReluctance: 0.1
    maxWalkDistance: 5000.0
  ) {
    itineraries {
      duration
      legs {
        mode
        startTime
        endTime
        duration
        legGeometry { points }
        route { shortName longName }
        from { name lat lon }
        to { name lat lon }
        intermediateStops { name lat lon }
      }
    }
  }
}
"""


def plan_journey_logic(
    start: str,
    end: str,
    time_str: str = "tomorrow 07:30",
    start_coords_override: Optional[List[float]] = None,
    end_coords_override: Optional[List[float]] = None,
) -> Dict[str, Any]:
    trip_time = parse_time_str(time_str)

    if start_coords_override:
        start_lat, start_lon = float(start_coords_override[0]), float(start_coords_override[1])
    else:
        start_lat, start_lon = get_coords(start)

    if end_coords_override:
        end_lat, end_lon = float(end_coords_override[0]), float(end_coords_override[1])
    else:
        end_lat, end_lon = get_coords(end)

    if not start_lat or not end_lat:
        return {"error": f"Koordinaten nicht gefunden für {start} oder {end}"}

    variables = {
        "fromLat": start_lat,
        "fromLon": start_lon,
        "toLat": end_lat,
        "toLon": end_lon,
        "date": trip_time.strftime("%Y-%m-%d"),
        "time": trip_time.strftime("%H:%M"),
    }

    # Use the existing otp_graphql helper (it uses OTP_URL env)
    data = otp_graphql(GQL_PLAN_ULTRA_LAZY, variables)

    plan = data.get("data", {}).get("plan")
    itins = (plan or {}).get("itineraries") or []
    if not itins:
        return {"error": "Keine Verbindung gefunden"}

    itin = itins[0]
    out: Dict[str, Any] = {
        "start": start,
        "end": end,
        "date": trip_time.strftime("%d.%m.%Y"),
        "total_duration": int((itin.get("duration") or 0) / 60),
        "legs": [],
    }

    for leg in itin.get("legs", []):
        start_t = datetime.fromtimestamp(leg["startTime"] / 1000).strftime("%H:%M")
        end_t = datetime.fromtimestamp(leg["endTime"] / 1000).strftime("%H:%M")
        line_name = ""
        if leg.get("route"):
            line_name = leg["route"].get("shortName") or leg["route"].get("longName") or ""

        from_node = leg["from"]
        to_node = leg["to"]
        from_name = start if from_node.get("name") == "Origin" else from_node.get("name")
        to_name = end if to_node.get("name") == "Destination" else to_node.get("name")

        out["legs"].append(
            {
                "mode": leg.get("mode"),
                "from": from_name,
                "to": to_name,
                "from_coords": [from_node.get("lat"), from_node.get("lon")],
                "to_coords": [to_node.get("lat"), to_node.get("lon")],
                "stops": [],
                "start_time": start_t,
                "end_time": end_t,
                "line": line_name,
                "duration": int((leg.get("duration") or 0) / 60),
                "geometry": (leg.get("legGeometry") or {}).get("points", ""),
            }
        )

    return out


# ---------------------------------------------------------------------------
# Activities (OpenSearch query + optional Azure embeddings)
# ---------------------------------------------------------------------------


def _os_client() -> OpenSearch:
    return OpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        use_ssl=False,
        verify_certs=False,
        connection_class=RequestsHttpConnection,
    )


def _embed_query(text: str) -> Optional[List[float]]:
    if not (AZURE_OPENAI_API_KEY and AZURE_EMBED_ENDPOINT and AZURE_EMBED_DEPLOYMENT):
        return None
    try:
        client = AzureOpenAI(
            azure_endpoint=AZURE_EMBED_ENDPOINT,
            api_key=AZURE_OPENAI_API_KEY,
            api_version=AZURE_EMBED_API_VERSION,
        )
        emb = client.embeddings.create(model=AZURE_EMBED_DEPLOYMENT, input=text)
        vec = emb.data[0].embedding
        if isinstance(vec, list) and len(vec) > 0:
            return vec
    except Exception as e:
        log(f"Embedding failed, falling back to text search: {e}")
    return None


def plan_activities_logic(location: str, interest: str = "") -> Dict[str, Any]:
    center_lat, center_lon = get_coords(location)
    if not center_lat:
        return {"type": "activity_list", "location": location, "items": []}

    search_query = f"{interest} in {location}" if interest else f"Highlights in {location}"
    max_radius = 15.0
    lower_interest = (interest or "").lower()
    if "museum" in lower_interest:
        search_query = f"Museum Ausstellung Geschichte Kultur in {location}"
        max_radius = 3.0
    elif "food" in lower_interest or "essen" in lower_interest or "restaurant" in lower_interest:
        search_query = f"Restaurant Gasthof Essen Traditionelle Küche in {location}"
        max_radius = 3.0

    os_client = _os_client()
    vec = _embed_query(search_query)

    # Retrieve many, then filter by radius + dedupe like agent_server
    size = 500

    if vec is not None:
        # Try "knn" query first
        query_body = {"size": size, "query": {"knn": {"embedding": {"vector": vec, "k": size}}}}
        try:
            res = os_client.search(index=POI_INDEX, body=query_body)
        except Exception:
            # Fallback to top-level knn syntax (newer OpenSearch)
            query_body = {
                "size": size,
                "query": {"match_all": {}},
                "knn": {"field": "embedding", "query_vector": vec, "k": size, "num_candidates": size},
            }
            res = os_client.search(index=POI_INDEX, body=query_body)
    else:
        # Text fallback
        query_body = {
            "size": size,
            "query": {
                "multi_match": {
                    "query": search_query,
                    "fields": ["name^3", "description^2", "city", "type"],
                }
            },
        }
        res = os_client.search(index=POI_INDEX, body=query_body)

    hits = (res.get("hits") or {}).get("hits") or []
    activities: List[Dict[str, Any]] = []
    seen = set()

    for h in hits:
        src = h.get("_source") or {}
        name = src.get("name") or "Unbekannt"
        if name in seen:
            continue

        # Coordinates
        lat = src.get("lat") or src.get("latitude")
        lon = src.get("lon") or src.get("longitude")
        if (lat is None or lon is None) and isinstance(src.get("location"), dict):
            lat = src["location"].get("lat") or src["location"].get("latitude")
            lon = src["location"].get("lon") or src["location"].get("longitude")
        try:
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
        except Exception:
            lat, lon = None, None
        if lat is None or lon is None:
            continue

        if calculate_distance(center_lat, center_lon, lat, lon) > max_radius:
            continue

        # Geometry parsing (geo_line -> encoded polyline)
        encoded_geometry = None
        raw_geo = src.get("geo_line")
        if raw_geo is not None:
            try:
                if isinstance(raw_geo, str):
                    raw_geo = json.loads(raw_geo.replace("'", '"'))
                coords_source: List[List[float]] = []
                if raw_geo.get("type") == "LineString":
                    coords_source = raw_geo.get("coordinates") or []
                elif raw_geo.get("type") == "MultiLineString":
                    for seg in raw_geo.get("coordinates") or []:
                        coords_source.extend(seg)
                pts: List[List[float]] = []
                for p in coords_source:
                    if isinstance(p, list) and len(p) >= 2:
                        pts.append([p[1], p[0]])
                if pts:
                    encoded_geometry = encode_polyline(pts)
            except Exception as e:
                log(f"Geometry parse failed for {name}: {e}")

        cat_display = src.get("type", "Attraction")
        ln = (name or "").lower()
        if "museum" in ln or "heimathaus" in ln:
            cat_display = "Museum"
        elif "gasthof" in ln or "restaurant" in ln:
            cat_display = "Restaurant"

        desc = (src.get("description") or "")
        item = {
            "name": name,
            "category": cat_display,
            "city": src.get("city", location),
            "description": (desc[:150] + "...") if len(desc) > 150 else desc,
            "lat": lat,
            "lon": lon,
            "source": src.get("source", "unknown"),
            "geometry": encoded_geometry,
            "opening_hours": src.get("openingHoursSpecification"),
        }

        activities.append(item)
        seen.add(name)
        if len(activities) >= 15:
            break

    return {"type": "activity_list", "location": location, "items": activities}


# ---------------------------------------------------------------------------
# Full planning (ported from agent_server.py)
# ---------------------------------------------------------------------------


def plan_complete_trip_logic(
    start: str,
    end: str,
    interest: str,
    num_stops: int = 2,
    avoid_places: Optional[List[str]] = None,
) -> Dict[str, Any]:
    avoid_places = avoid_places or []
    log(f"[LOGIC] Plane Rundreise: {start} -> {end} ({interest}) -> {start}")

    start_lat, start_lon = get_coords(start)
    if not start_lat:
        return {"type": "error", "message": f"Startort {start} nicht gefunden."}
    start_coords = (start_lat, start_lon)

    interests_to_search: List[str] = []
    lower_int = (interest or "").lower()
    wants_museum = "museum" in lower_int or "kultur" in lower_int
    wants_food = "food" in lower_int or "essen" in lower_int or "restaurant" in lower_int
    if wants_museum and wants_food:
        interests_to_search = ["Museum Geschichte Kultur", "Gasthof Restaurant Essen"]
    else:
        interests_to_search = [interest, interest]

    pools: List[List[Dict[str, Any]]] = []
    for sub_interest in interests_to_search:
        act_data = plan_activities_logic(location=end, interest=sub_interest)
        pools.append(act_data.get("items", []))

    steps: List[Dict[str, Any]] = []
    current_coords = start_coords
    current_name = start
    seen_names = set()
    stops_found = 0

    current_time_obj = datetime.now() + timedelta(days=1)
    current_time_obj = current_time_obj.replace(hour=9, minute=0, second=0, microsecond=0)

    for pool in pools:
        if stops_found >= num_stops:
            break

        check_time = current_time_obj + timedelta(minutes=45)
        stop = None
        for item in pool:
            if item["name"] not in seen_names and item["name"] not in avoid_places and check_is_open(item.get("opening_hours"), check_time):
                stop = item
                break
        if not stop:
            for item in pool:
                if item["name"] not in seen_names and item["name"] not in avoid_places:
                    stop = item
                    log(f"[WARN] Fallback: {stop['name']} (Öffnungszeiten unklar/geschlossen)")
                    break
        if not stop:
            continue

        seen_names.add(stop["name"])
        stops_found += 1
        stop_name = stop["name"]
        stop_coords = (stop["lat"], stop["lon"])
        label = f"Anreise zu: {stop['category']} ({stop_name})"
        time_str_dynamic = f"tomorrow {current_time_obj.strftime('%H:%M')}"

        trip_data = plan_journey_logic(
            start=current_name,
            end=stop_name,
            time_str=time_str_dynamic,
            start_coords_override=[current_coords[0], current_coords[1]],
            end_coords_override=[stop_coords[0], stop_coords[1]],
        )

        trip_duration_minutes = 30
        if "legs" in trip_data:
            steps.append({"type": "trip", "data": trip_data, "label": label})
            trip_duration_minutes = trip_data.get("total_duration", 30)
        else:
            steps.append({"type": "error", "message": f"Kein Weg nach {stop_name}"})

        current_time_obj += timedelta(minutes=trip_duration_minutes)

        if stop.get("geometry"):
            hike_duration = 120
            visual_trip = {
                "start": stop["name"],
                "end": stop["name"],
                "date": current_time_obj.strftime("%d.%m.%Y"),
                "total_duration": hike_duration,
                "legs": [
                    {
                        "mode": "WALK",
                        "from": stop["name"],
                        "to": stop["name"],
                        "from_coords": [stop["lat"], stop["lon"]],
                        "to_coords": [stop["lat"], stop["lon"]],
                        "start_time": current_time_obj.strftime("%H:%M"),
                        "end_time": (current_time_obj + timedelta(minutes=hike_duration)).strftime("%H:%M"),
                        "line": "Wanderweg",
                        "duration": hike_duration,
                        "geometry": stop["geometry"],
                    }
                ],
            }
            steps.append({"type": "trip", "data": visual_trip, "label": f"Route: {stop['name']}"})
            current_time_obj += timedelta(minutes=hike_duration)
        else:
            current_time_obj += timedelta(minutes=90)

        steps.append({"type": "activity", "data": stop})
        current_coords = stop_coords
        current_name = stop_name

    time_str_return = f"tomorrow {current_time_obj.strftime('%H:%M')}"
    final_trip_data = plan_journey_logic(
        start=current_name,
        end=start,
        time_str=time_str_return,
        start_coords_override=[current_coords[0], current_coords[1]],
        end_coords_override=[start_coords[0], start_coords[1]],
    )

    if "legs" in final_trip_data:
        steps.append({"type": "trip", "data": final_trip_data, "label": "Heimreise"})
    else:
        steps.append({"type": "error", "message": "Keine Rückverbindung gefunden."})

    intro_msg = f"Ich habe einen Ausflug von {start} nach {end} mit {stops_found} Stopps geplant:"
    if stops_found == 0:
        intro_msg = f"Keine passenden Aktivitäten in {end} gefunden."
    return {"type": "multi_step_plan", "intro": intro_msg, "steps": steps}


def plan_multiday_trip_logic(
    start: str,
    end: str,
    days: int = 4,
    hotel_pref: str = "Hotel Unterkunft Central",
    activity_pref: str = "Wandern Natur Freizeit",
    food_pref: str = "Restaurant Gaststätte",
    culture_pref: str = "Museum",
    avoid_places: Optional[List[str]] = None,
) -> Dict[str, Any]:
    avoid_places = avoid_places or []
    if days < 1:
        days = 1
    log(f"[LOGIC] Plane Trip für {days} Tage nach {end} (Basis-Strategie: Zentral)")

    start_lat, start_lon = get_coords(start)
    start_coords = (start_lat, start_lon) if start_lat else None

    end_lat, end_lon = get_coords(end)
    if not end_lat:
        return {"type": "error", "message": f"Zielort {end} nicht gefunden."}

    hotels_data = plan_activities_logic(end, hotel_pref)
    hotel = None
    for h in hotels_data.get("items", []):
        if h["name"] in avoid_places:
            continue
        if calculate_distance(end_lat, end_lon, h["lat"], h["lon"]) <= 2.5:
            hotel = h
            break

    if hotel:
        base_name = hotel["name"]
        base_coords = (hotel["lat"], hotel["lon"])
        intro_text = f"Ich habe eine Reise nach {end} geplant. Deine Basis ist das **{base_name}**."
    else:
        base_name = f"{end} Zentrum"
        base_coords = (end_lat, end_lon)
        intro_text = f"Ich habe eine Reise nach {end} geplant. Da ich kein zentrales Hotel in der Datenbank gefunden habe, starten wir vom Zentrum."
        log(f"[WARN] Kein Hotel gefunden. Nutze Koordinaten von {end} als Basis.")

    museums = plan_activities_logic(end, culture_pref)
    food = plan_activities_logic(end, food_pref)
    leisure = plan_activities_logic(end, activity_pref)

    pool_museums = museums.get("items", [])
    pool_food = food.get("items", [])
    pool_leisure = leisure.get("items", [])

    steps: List[Dict[str, Any]] = []

    def get_item(pool: List[Dict[str, Any]], time_str: str = "tomorrow 12:00") -> Optional[Dict[str, Any]]:
        check_time = parse_time_str(time_str)
        for i, item in enumerate(list(pool)):
            if item["name"] not in avoid_places and check_is_open(item.get("opening_hours"), check_time):
                return pool.pop(i)
        while pool:
            item = pool.pop(0)
            if item["name"] not in avoid_places:
                log(f"[WARN] Fallback in Mehrtagesreise: {item['name']} (Öffnungszeiten unklar/geschlossen)")
                return item
        return None

    def add_route(origin_name: str, origin_coords: Tuple[float, float], dest_name: str, dest_coords: Tuple[float, float], time_str: str, label: str) -> None:
        dist = calculate_distance(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1])
        if dist < 0.2:
            return
        trip = plan_journey_logic(
            start=origin_name,
            end=dest_name,
            time_str=time_str,
            start_coords_override=[origin_coords[0], origin_coords[1]],
            end_coords_override=[dest_coords[0], dest_coords[1]],
        )
        if "legs" in trip:
            steps.append({"type": "trip", "data": trip, "label": label})
        else:
            steps.append({"type": "error", "message": f"Kein Weg von {origin_name} nach {dest_name}"})

    def add_visual_tracking(activity: Dict[str, Any]) -> None:
        if activity.get("geometry"):
            visual_trip = {
                "start": activity["name"],
                "end": activity["name"],
                "date": "Wandertag",
                "total_duration": 120,
                "legs": [
                    {
                        "mode": "WALK",
                        "from": activity["name"],
                        "to": activity["name"],
                        "from_coords": [activity["lat"], activity["lon"]],
                        "to_coords": [activity["lat"], activity["lon"]],
                        "start_time": "10:30",
                        "end_time": "12:30",
                        "line": "Wanderweg",
                        "duration": 120,
                        "geometry": activity["geometry"],
                    }
                ],
            }
            steps.append({"type": "trip", "data": visual_trip, "label": f"Route: {activity['name']}"})

    curr_name = start
    curr_coords = start_coords

    steps.append({"type": "header", "title": "📅 Tag 1: Anreise & Start"})
    if curr_coords:
        add_route(curr_name, curr_coords, base_name, base_coords, "tomorrow 11:00", f"Anreise nach {end}")
    if hotel:
        steps.append({"type": "activity", "data": hotel})
    curr_name = base_name
    curr_coords = base_coords

    act1 = get_item(pool_leisure) or get_item(pool_museums)
    if act1:
        act1_coords = (act1["lat"], act1["lon"])
        add_route(curr_name, curr_coords, act1["name"], act1_coords, "tomorrow 14:30", "Erster Ausflug")
        add_visual_tracking(act1)
        steps.append({"type": "activity", "data": act1})
        curr_name = act1["name"]
        curr_coords = act1_coords

    dinner1 = get_item(pool_food)
    if dinner1:
        dinner_coords = (dinner1["lat"], dinner1["lon"])
        add_route(curr_name, curr_coords, dinner1["name"], dinner_coords, "tomorrow 18:30", "Zum Abendessen")
        steps.append({"type": "activity", "data": dinner1})
        add_route(dinner1["name"], dinner_coords, base_name, base_coords, "tomorrow 20:30", "Zurück zur Unterkunft")
    else:
        add_route(curr_name, curr_coords, base_name, base_coords, "tomorrow 19:00", "Zurück zur Unterkunft")

    for i in range(2, days):
        steps.append({"type": "header", "title": f"📅 Tag {i}: Entdeckungstour"})
        curr_name = base_name
        curr_coords = base_coords

        act_am = get_item(pool_leisure)
        if act_am:
            act_am_coords = (act_am["lat"], act_am["lon"])
            add_route(curr_name, curr_coords, act_am["name"], act_am_coords, "tomorrow 09:30", "Ausflug am Morgen")
            add_visual_tracking(act_am)
            steps.append({"type": "activity", "data": act_am})
            curr_name = act_am["name"]
            curr_coords = act_am_coords

        act_pm = get_item(pool_museums)
        if act_pm:
            act_pm_coords = (act_pm["lat"], act_pm["lon"])
            add_route(curr_name, curr_coords, act_pm["name"], act_pm_coords, "tomorrow 14:00", "Kultur am Nachmittag")
            steps.append({"type": "activity", "data": act_pm})
            curr_name = act_pm["name"]
            curr_coords = act_pm_coords

        act_eve = get_item(pool_food)
        if act_eve:
            act_eve_coords = (act_eve["lat"], act_eve["lon"])
            add_route(curr_name, curr_coords, act_eve["name"], act_eve_coords, "tomorrow 19:00", "Abendessen")
            steps.append({"type": "activity", "data": act_eve})
            add_route(act_eve["name"], act_eve_coords, base_name, base_coords, "tomorrow 21:00", "Zurück zur Unterkunft")
        else:
            add_route(curr_name, curr_coords, base_name, base_coords, "tomorrow 20:00", "Zurück zur Unterkunft")

    steps.append({"type": "header", "title": f"📅 Tag {days}: Heimreise"})
    curr_name = base_name
    curr_coords = base_coords

    last_act = get_item(pool_leisure) or get_item(pool_museums)
    if last_act:
        last_coords = (last_act["lat"], last_act["lon"])
        add_route(curr_name, curr_coords, last_act["name"], last_coords, "tomorrow 10:00", "Letzter Ausflug")
        add_visual_tracking(last_act)
        steps.append({"type": "activity", "data": last_act})
        curr_name = last_act["name"]
        curr_coords = last_coords

    if curr_coords and start_coords:
        add_route(curr_name, curr_coords, start, start_coords, "tomorrow 15:00", "Heimreise")

    return {"type": "multi_step_plan", "intro": intro_text, "steps": steps}


def find_best_city_logic(query: str) -> str:
    # If OS is down or empty, match old fallback semantics.
    try:
        data = plan_activities_logic(location="Allgäu", interest=query)
        cities = [i.get("city") for i in data.get("items", []) if i.get("city")]
        if not cities:
            return "Sonthofen"
        return Counter(cities).most_common(1)[0][0]
    except Exception:
        return "Oberstdorf"
