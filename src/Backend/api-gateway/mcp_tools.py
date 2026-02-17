import json
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import Counter

# --- LlamaIndex & OpenSearch Imports ---
from llama_index.core import VectorStoreIndex, Settings
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from opensearchpy import OpenSearch, RequestsHttpConnection


# ============================================================================
# 0. GEO + POLYLINE HELPERS (ported from old branch)
# ============================================================================

def calculate_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in km."""
    from math import radians, sin, cos, sqrt, atan2
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c


def _encode_value(value: int) -> str:
    value = ~(value << 1) if value < 0 else (value << 1)
    encoded = ""
    while value >= 0x20:
        encoded += chr((0x20 | (value & 0x1f)) + 63)
        value >>= 5
    encoded += chr(value + 63)
    return encoded


def encode_polyline(points_latlon: List[List[float]]) -> str:
    """Encode [[lat, lon], ...] to Google polyline."""
    last_lat = 0
    last_lon = 0
    out = ""
    for lat, lon in points_latlon:
        lat_e5 = int(round(lat * 1e5))
        lon_e5 = int(round(lon * 1e5))
        dlat = lat_e5 - last_lat
        dlon = lon_e5 - last_lon
        out += _encode_value(dlat)
        out += _encode_value(dlon)
        last_lat = lat_e5
        last_lon = lon_e5
    return out


def geocode_location_nominatim(query: str) -> Optional[List[float]]:
    """Best-effort geocoding via Nominatim. Returns [lat, lon] or None."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "KIRA/1.0 (merge-tooling)"},
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        return [float(data[0]["lat"]), float(data[0]["lon"])]
    except Exception:
        return None


def _extract_lat_lon(meta: Dict[str, Any]) -> Optional[List[float]]:
    """Extract [lat, lon] from common metadata formats."""
    lat = meta.get("lat") or meta.get("latitude")
    lon = meta.get("lon") or meta.get("lng") or meta.get("longitude")
    if lat is None or lon is None:
        loc = meta.get("location")
        if isinstance(loc, str) and "," in loc:
            try:
                a, b = loc.split(",", 1)
                lat = float(a.strip())
                lon = float(b.strip())
            except Exception:
                pass
        elif isinstance(loc, dict):
            lat = loc.get("lat") or loc.get("latitude")
            lon = loc.get("lon") or loc.get("lng") or loc.get("longitude")
    if lat is None or lon is None:
        return None
    try:
        return [float(lat), float(lon)]
    except Exception:
        return None


def _extract_encoded_geometry(meta: Dict[str, Any]) -> Optional[str]:
    """If meta contains a GeoJSON LineString/MultiLineString in 'geo_line', encode it."""
    raw_geo = meta.get("geo_line")
    if not raw_geo:
        return None
    try:
        if isinstance(raw_geo, str):
            # tolerate single quotes from older ingests
            raw_geo = json.loads(raw_geo.replace("'", '"'))
        geo_type = raw_geo.get("type")
        coords_source: List[List[float]] = []
        if geo_type == "LineString":
            coords_source = raw_geo.get("coordinates") or []
        elif geo_type == "MultiLineString":
            for seg in raw_geo.get("coordinates") or []:
                coords_source.extend(seg)
        points: List[List[float]] = []
        for p in coords_source:
            if isinstance(p, list) and len(p) >= 2:
                # [lon, lat, (z)] -> [lat, lon]
                points.append([float(p[1]), float(p[0])])
        return encode_polyline(points) if points else None
    except Exception:
        return None


def add_visual_tracking_step(steps: List[Dict[str, Any]], activity_item: Dict[str, Any]) -> None:
    """If an activity has encoded 'geometry', add a fake WALK leg so the frontend can draw the trail."""
    geom = activity_item.get("geometry")
    if not geom:
        return
    name = activity_item.get("name", "Route")
    lat = activity_item.get("lat")
    lon = activity_item.get("lon")
    leg = {
        "mode": "WALK",
        "from": name,
        "to": name,
        "from_coords": [lat, lon] if lat is not None and lon is not None else None,
        "to_coords": [lat, lon] if lat is not None and lon is not None else None,
        "stops": [],
        "start_time": "",
        "end_time": "",
        "line": "Wanderweg",
        "duration": 0,
        "geometry": geom,
    }
    steps.append({"type": "trip", "data": {"start": name, "end": name, "date": "", "total_duration": 0, "legs": [leg]}, "label": "Route"})


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        return ""
    return v

# ============================================================================
# 1. INITIALIZATION (DB Connections & Embeddings)
# ============================================================================

# Configuration
TRIP_PLANNER_URL = _env("TRIP_PLANNER_URL", "http://trip-planner:8001").rstrip("/")
OPENSEARCH_HOST = _env("OPENSEARCH_HOST", "opensearch")
OPENSEARCH_PORT = int(_env("OPENSEARCH_PORT", "9200") or "9200")
OPENSEARCH_USER = _env("OPENSEARCH_USER", "admin")
OPENSEARCH_PASS = _env("OPENSEARCH_PASS", "admin")
POI_INDEX = _env("POI_INDEX", "poi-data")

# Globals
activity_engine = None
activity_client = None

def init_activity_engine():
    """
    Initializes LlamaIndex with OpenSearch vector store.
    (Called lazily to allow container startup ordering.)
    """
    global activity_engine, activity_client

    try:
        print("[INIT] Connecting to OpenSearch + LlamaIndex...")

        # --- OpenSearch client ---
        activity_client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            http_auth=(OPENSEARCH_USER, OPENSEARCH_PASS),
            use_ssl=False,
            verify_certs=False,
            connection_class=RequestsHttpConnection,
        )

        # --- Embedding model ---
        embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/all-MiniLM-L6-v2")
        Settings.embed_model = embed_model

        # --- Vector store ---
        vector_client = OpensearchVectorClient(
            endpoint=f"http://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}",
            index=POI_INDEX,
            dim=384,
            embedding_field="embedding",
            text_field="content",
        )

        vector_store = OpensearchVectorStore(vector_client)
        index = VectorStoreIndex.from_vector_store(vector_store)

        # --- Query engine ---
        activity_engine = index.as_query_engine(similarity_top_k=10)

        print("[INIT] ✅ LlamaIndex activity_engine initialized.")
    except Exception as e:
        print(f"[INIT ERROR] {e}")
        activity_engine = None


# ============================================================================
# 2. TOOL LOGIC FUNCTIONS (called by API-Gateway)
# ============================================================================

def plan_journey_logic(start: str, end: str, time_str: str = "tomorrow 07:30") -> str:
    """
    Plans a journey using the Trip Planner microservice but formats the result
    specifically for the frontend (matching Eric's logic).
    """
    print(f"[LOGIC] Searching route {start} -> {end} ({time_str})")

    # 1. Parse Date/Time locally to format the request for the microservice
    try:
        trip_time = datetime.now()
        if "tomorrow" in time_str.lower():
            trip_time = trip_time + timedelta(days=1)
            parts = time_str.split()
            if len(parts) > 1 and ":" in parts[-1]:
                h, m = map(int, parts[-1].split(':'))
                trip_time = trip_time.replace(hour=h, minute=m, second=0)
            else:
                trip_time = trip_time.replace(hour=7, minute=30)

        # Formats required by trip-planner API
        date_param = trip_time.strftime("%Y-%m-%d")
        time_param = trip_time.strftime("%H:%M")
    except Exception as e:
        return json.dumps({"error": f"Date parse error: {str(e)}"})

    # 2. Call Trip Planner Microservice
    payload = {
        "from_stop": start,
        "to_stop": end,
        "date": date_param,
        "time": time_param
    }

    try:
        r = requests.post(f"{TRIP_PLANNER_URL}/plan-by-stops", json=payload, timeout=60)
        r.raise_for_status()
        data = r.json()  # raw OTP GraphQL response
    except Exception as e:
        return json.dumps({"error": f"Trip planner service error: {str(e)}"})

    # 3. Process JSON (Logic from old agent_server.py)
    if data and data.get('data') and data['data'].get('plan') and data['data']['plan'].get('itineraries'):
        itin = data['data']['plan']['itineraries'][0]

        frontend_data = {
            "start": start,
            "end": end,
            "date": trip_time.strftime("%d.%m.%Y"),
            "total_duration": int(itin['duration'] / 60),
            "legs": []
        }

        for leg in itin['legs']:
            mode = leg['mode']
            start_t = datetime.fromtimestamp(leg['startTime'] / 1000).strftime('%H:%M')
            end_t = datetime.fromtimestamp(leg['endTime'] / 1000).strftime('%H:%M')

            line_name = ""
            if leg.get('route'):
                line_name = leg['route'].get('shortName') or leg['route'].get('longName') or ""

            from_name = leg['from']['name']
            to_name = leg['to']['name']

            # Fix "Origin"/"Destination" names
            if from_name == "Origin": from_name = start
            if to_name == "Destination": to_name = end

            from_coords = [leg["from"].get("lat"), leg["from"].get("lon")] if leg.get("from") else None
            to_coords = [leg["to"].get("lat"), leg["to"].get("lon")] if leg.get("to") else None

            geometry = ""
            if leg.get("legGeometry"):
                geometry = leg["legGeometry"].get("points") or ""

            stops = []
            for s in (leg.get("intermediateStops") or []):
                if s and s.get("lat") is not None and s.get("lon") is not None:
                    stops.append({"name": s.get("name", ""), "lat": s["lat"], "lon": s["lon"]})

            frontend_data["legs"].append({
                "mode": mode,
                "from": from_name,
                "to": to_name,
                "from_coords": from_coords,
                "to_coords": to_coords,
                "stops": stops,
                "start_time": start_t,
                "end_time": end_t,
                "line": line_name,
                "duration": int(leg['duration'] / 60),
                "geometry": geometry,
            })

        return json.dumps(frontend_data, ensure_ascii=False)
    else:
        return json.dumps({"error": "No connection found"}, ensure_ascii=False)


def plan_activities_logic(location: str, interest: str = "") -> str:
    """Searches activities via LlamaIndex, then post-filters by distance around the location.
    Also encodes hiking/trail geometries (geo_line -> Google polyline) for map rendering.
    """
    global activity_engine
    if not activity_engine:
        init_activity_engine()
        if not activity_engine:
            return json.dumps({"error": "Database not connected."})

    # 1) Geocode center (best-effort)
    center = geocode_location_nominatim(location)
    if not center:
        # still return something rather than hard-fail
        center_lat, center_lon = None, None
    else:
        center_lat, center_lon = center

    # 2) Build query + dynamic radius
    max_radius_km = 15.0
    q_interest = (interest or "").lower()

    if "museum" in q_interest:
        query = f"Museum Ausstellung Geschichte Kultur in {location}"
        max_radius_km = 3.0
    elif any(k in q_interest for k in ["food", "essen", "restaurant", "gaststätte", "gastro"]):
        query = f"Restaurant Gasthof Essen Traditionelle Küche in {location}"
        max_radius_km = 3.0
    else:
        query = f"{interest} in {location}" if interest else f"Highlights in {location}"

    print(f"[LOGIC] Searching Activities: {query} (radius {max_radius_km}km)")

    try:
        response = activity_engine.query(query)

        activities_list: List[Dict[str, Any]] = []
        seen_names = set()

        for node_with_score in response.source_nodes:
            node = node_with_score.node
            meta = node.metadata or {}
            name = meta.get("name", "Unbekannter Ort")

            if name in seen_names:
                continue

            # Coordinates
            latlon = _extract_lat_lon(meta)
            if not latlon:
                continue
            lat, lon = latlon[0], latlon[1]

            # Radius filter if we have a center
            if center_lat is not None and center_lon is not None:
                dist = calculate_distance_km(center_lat, center_lon, lat, lon)
                if dist > max_radius_km:
                    continue

            # Optional trail geometry
            encoded_geom = _extract_encoded_geometry(meta)

            cat_display = meta.get("type") or meta.get("category") or "Attraction"
            lower_name = name.lower()
            if "museum" in lower_name or "heimathaus" in lower_name:
                cat_display = "Museum"
            elif "gasthof" in lower_name or "restaurant" in lower_name:
                cat_display = "Restaurant"

            activity_item = {
                "name": name,
                "category": cat_display,
                "city": meta.get("city", location),
                "description": (node.get_text() or "")[:150] + "...",
                "lat": lat,
                "lon": lon,
                "source": meta.get("source", "unknown"),
                "geometry": encoded_geom,
            }

            activities_list.append(activity_item)
            seen_names.add(name)

            if len(activities_list) >= 5:
                break

        return json.dumps({"type": "activity_list", "location": location, "items": activities_list}, ensure_ascii=False)

    except Exception as e:
        print(f"[ERROR] plan_activities_logic: {e}")
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def plan_complete_trip_logic(start: str, end: str, interest: str = "") -> str:
    """
    Simple plan for: route + activities.
    """
    trip = json.loads(plan_journey_logic(start, end))
    acts = json.loads(plan_activities_logic(end, interest))
    return json.dumps({
        "type": "complete_trip",
        "trip": trip,
        "activities": acts
    }, ensure_ascii=False)


def plan_multiday_trip_logic(start: str, end: str, days: int = 4) -> str:
    """
    Plans a multi-day trip with routes between activities (Chaining).
    """
    if days < 1: days = 1

    print(f"[LOGIC] Planning {days}-day trip: {start} -> {end}")

    # 1. Fill Pools
    museums = json.loads(plan_activities_logic(end, "Museum"))
    food = json.loads(plan_activities_logic(end, "Restaurant Gaststätte"))
    leisure = json.loads(plan_activities_logic(end, "Wandern Natur Freizeit"))

    pool_museums = museums.get("items", [])
    pool_food = food.get("items", [])
    pool_leisure = leisure.get("items", [])

    steps = []

    def get_item(pool):
        return pool.pop(0) if pool else None

    def add_route(origin, destination, time_str, label="Fahrt"):
        if not origin or not destination: return
        trip_json = plan_journey_logic(origin, destination, time_str)
        trip_data = json.loads(trip_json)

        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data, "label": label })
        else:
            steps.append({
                "type": "error",
                "message": f"Kein Weg gefunden von {origin} nach {destination}"
            })

    base_location = end
    current_loc = start

    # --- Day 1 ---
    steps.append({ "type": "header", "title": "📅 Tag 1: Anreise & Erstes Erkunden" })

    add_route(current_loc, base_location, "tomorrow 10:00", "Anreise")
    current_loc = base_location

    act1 = get_item(pool_museums) or get_item(pool_leisure)
    if act1:
        add_route(current_loc, act1["name"], "tomorrow 14:00")
        steps.append({ "type": "activity", "data": act1 })
        add_visual_tracking_step(steps, act1)
        current_loc = act1["name"]

    dinner = get_item(pool_food)
    if dinner:
        add_route(current_loc, dinner["name"], "tomorrow 18:00")
        steps.append({ "type": "activity", "data": dinner })

    # --- Days 2...N-1 ---
    for i in range(2, days):
        steps.append({ "type": "header", "title": f"📅 Tag {i}: Entdeckungstour" })
        current_loc = base_location

        act_am = get_item(pool_leisure)
        if act_am:
            add_route(current_loc, act_am["name"], "tomorrow 10:00")
            steps.append({ "type": "activity", "data": act_am })
            add_visual_tracking_step(steps, act_am)
            current_loc = act_am["name"]

        act_pm = get_item(pool_museums)
        if act_pm:
            add_route(current_loc, act_pm["name"], "tomorrow 14:00")
            steps.append({ "type": "activity", "data": act_pm })
            current_loc = act_pm["name"]

        act_eve = get_item(pool_food)
        if act_eve:
            add_route(current_loc, act_eve["name"], "tomorrow 19:00")
            steps.append({ "type": "activity", "data": act_eve })

    # --- Last Day ---
    steps.append({ "type": "header", "title": f"📅 Tag {days}: Abschied & Heimreise" })
    current_loc = base_location

    last_act = get_item(pool_leisure)
    if last_act:
        add_route(current_loc, last_act["name"], "tomorrow 10:00")
        steps.append({ "type": "activity", "data": last_act })
        add_visual_tracking_step(steps, last_act)

    add_route(base_location, start, "tomorrow 16:00", "Rückreise")

    result = {
        "type": "multi_step_plan",
        "intro": f"Ich habe die komplette Route für {days} Tage inkl. aller Wege berechnet:",
        "steps": steps
    }

    return json.dumps(result, ensure_ascii=False)


def find_best_city_logic(preferences: str = "") -> str:
    """
    A simple heuristic that returns a city suggestion based on user preferences.
    """
    prefs = (preferences or "").lower()

    # Extremely simple heuristics
    if "berge" in prefs or "wandern" in prefs or "alpen" in prefs:
        return "Garmisch-Partenkirchen"
    if "meer" in prefs or "strand" in prefs:
        return "Hamburg"
    if "kunst" in prefs or "museum" in prefs:
        return "Berlin"

    return "München"


# ============================================================================
# 3. TOOL WRAPPERS (called by model)
# ============================================================================

def plan_journey(start: str, end: str, time: str = "tomorrow 07:30") -> str:
    return plan_journey_logic(start, end, time)

def plan_activities(location: str, interest: str = "") -> str:
    return plan_activities_logic(location, interest)

def plan_complete_trip(start: str, end: str, interest: str = "") -> str:
    return plan_complete_trip_logic(start, end, interest)

def plan_multiday_trip(start: str, end: str, days: int = 4) -> str:
    return plan_multiday_trip_logic(start, end, days)

def find_best_city(preferences: str = "") -> str:
    return find_best_city_logic(preferences)
