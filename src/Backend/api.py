import copy
import json
import os
import re
import sys
import uuid
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple, List

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from opensearchpy import OpenSearch, RequestsHttpConnection

current_dir = os.path.dirname(os.path.abspath(__file__))
mcp_path = os.path.abspath(os.path.join(current_dir, "..", "MCP"))
if mcp_path not in sys.path:
    sys.path.append(mcp_path)

from agent_server import (  # noqa: E402
    find_best_city_logic,
    plan_activities_logic,
    plan_complete_trip_logic,
    plan_journey_logic,
    plan_multiday_trip_logic,
)
from openai import AzureOpenAI

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
)
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
os_client = OpenSearch(
    hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
    use_ssl=False,
    verify_certs=False,
    connection_class=RequestsHttpConnection,
)

SESSION_STATE: Dict[str, Dict[str, Any]] = {}



POI_INDEX = os.getenv("POI_INDEX", "tourism-data-v7")
POI_MAP_INDEX = os.getenv("POI_MAP_INDEX", "poi-data")


class PoiSearchRequest(BaseModel):
    north: float
    south: float
    east: float
    west: float
    limit: int = Field(default=300, ge=1, le=500)
    category: Optional[str] = None
    exclude_names: List[str] = Field(default_factory=list)
    include_names: List[str] = Field(default_factory=list)
    trip_mode: str = Field(default="all")


class AddPoiRequest(BaseModel):
    session_id: Optional[str] = None
    poi: Dict[str, Any]
    day_index: Optional[int] = None
    after_step_index: Optional[int] = None
    selection: Optional[Dict[str, Any]] = None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _parse_lat_lon_string(value: Any) -> Tuple[Optional[float], Optional[float]]:
    if not isinstance(value, str) or "," not in value:
        return None, None
    first, second = value.split(",", 1)
    lat = _safe_float(first.strip())
    lon = _safe_float(second.strip())
    if lat is None or lon is None:
        return None, None
    return lat, lon


def _get_hit_source(hit: Dict[str, Any]) -> Dict[str, Any]:
    return hit.get("_source") or {}


def _get_metadata_dict(source: Dict[str, Any]) -> Dict[str, Any]:
    metadata = source.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    metadata_dict = source.get("metadata_dict")
    if isinstance(metadata_dict, dict):
        return metadata_dict
    return {}


def _extract_hit_coords(source: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    location = source.get("location")
    if isinstance(location, dict):
        lat = _safe_float(location.get("lat") or location.get("latitude"))
        lon = _safe_float(location.get("lon") or location.get("longitude"))
        if lat is not None and lon is not None:
            return lat, lon
    if isinstance(location, list) and len(location) >= 2:
        lon = _safe_float(location[0])
        lat = _safe_float(location[1])
        if lat is not None and lon is not None:
            return lat, lon
    lat, lon = _parse_lat_lon_string(location)
    if lat is not None and lon is not None:
        return lat, lon

    metadata = _get_metadata_dict(source)
    metadata_location = metadata.get("location")
    lat, lon = _parse_lat_lon_string(metadata_location)
    if lat is not None and lon is not None:
        return lat, lon
    if isinstance(metadata_location, dict):
        lat = _safe_float(metadata_location.get("lat") or metadata_location.get("latitude"))
        lon = _safe_float(metadata_location.get("lon") or metadata_location.get("longitude"))
        if lat is not None and lon is not None:
            return lat, lon

    geo = source.get("geo")
    if isinstance(geo, dict):
        lat = _safe_float(geo.get("latitude") or geo.get("lat"))
        lon = _safe_float(geo.get("longitude") or geo.get("lon"))
        if lat is not None and lon is not None:
            return lat, lon

    lat = _safe_float(source.get("lat") or source.get("latitude"))
    lon = _safe_float(source.get("lon") or source.get("longitude"))
    if lat is not None and lon is not None:
        return lat, lon

    return None, None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _normalize_poi_hit(hit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    source = _get_hit_source(hit)
    metadata = _get_metadata_dict(source)
    lat, lon = _extract_hit_coords(source)
    if lat is None or lon is None:
        return None

    name = _coalesce(source.get("name"), metadata.get("name"), source.get("title"), metadata.get("title"), "Unbekannt")
    category = _coalesce(
        source.get("category"),
        source.get("type"),
        metadata.get("type"),
        source.get("subcategory"),
        "Ort",
    )
    description = _coalesce(source.get("description"), source.get("text"), metadata.get("description"))
    city = _coalesce(source.get("city"), metadata.get("city"))
    street = _coalesce(source.get("street"), metadata.get("street"))
    postal_code = _coalesce(source.get("postal_code"), metadata.get("postal_code"))
    country = _coalesce(source.get("country"), metadata.get("country"))
    address = _coalesce(source.get("address"))
    if not address:
        address_parts = [street, postal_code, city, country]
        address = ", ".join([str(part).strip() for part in address_parts if part and str(part).strip()]) or None

    poi_id = _coalesce(
        hit.get("_id"),
        source.get("source_id"),
        metadata.get("source_id"),
        source.get("@id"),
        metadata.get("@id"),
        name,
    )

    return {
        "id": poi_id,
        "name": str(name),
        "category": str(category),
        "description": str(description).strip() if description else None,
        "lat": lat,
        "lon": lon,
        "city": city,
        "address": address,
        "website": _coalesce(source.get("website"), source.get("url"), metadata.get("website")),
        "telephone": _coalesce(source.get("telephone"), metadata.get("telephone")),
        "opening_hours": _coalesce(
            source.get("openingHoursSpecification"),
            source.get("opening_hours"),
            metadata.get("openingHoursSpecification"),
        ),
        "start_date": _coalesce(source.get("startDate"), source.get("start_date"), metadata.get("startDate")),
        "end_date": _coalesce(source.get("endDate"), source.get("end_date"), metadata.get("endDate")),
        "source": _coalesce(source.get("source"), metadata.get("source")),
    }


def _index_exists(index_name: str) -> bool:
    try:
        return bool(index_name) and bool(os_client.indices.exists(index=index_name))
    except Exception:
        return False


def _candidate_poi_indices() -> List[str]:
    candidates = [
        POI_MAP_INDEX,
        POI_INDEX,
        "poi-data",
        "tourism-data-v7",
    ]
    ordered: List[str] = []
    seen = set()
    for candidate in candidates:
        name = str(candidate or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        if _index_exists(name):
            ordered.append(name)
    return ordered


def _build_poi_query(req: PoiSearchRequest, geo_field: str = "location") -> Dict[str, Any]:
    center_lat = (req.north + req.south) / 2.0
    center_lon = (req.east + req.west) / 2.0
    filter_clauses: List[Dict[str, Any]] = [
        {
            "geo_bounding_box": {
                geo_field: {
                    "top_left": {"lat": req.north, "lon": req.west},
                    "bottom_right": {"lat": req.south, "lon": req.east},
                }
            }
        }
    ]

    if req.category and req.category != "Alle":
        filter_clauses.append({
            "bool": {
                "should": [
                    {"term": {"type": req.category}},
                    {"term": {"category": req.category}},
                    {"term": {"metadata.type.keyword": req.category}},
                    {"match_phrase": {"type": req.category}},
                    {"match_phrase": {"category": req.category}},
                    {"match_phrase": {"metadata.type": req.category}},
                    {"match": {"description": req.category}},
                ],
                "minimum_should_match": 1,
            }
        })

    return {
        "size": req.limit,
        "_source": True,
        "sort": [
            {
                "_geo_distance": {
                    geo_field: {"lat": center_lat, "lon": center_lon},
                    "order": "asc",
                    "unit": "km",
                    "ignore_unmapped": True,
                }
            }
        ],
        "query": {"bool": {"filter": filter_clauses}},
    }


def _apply_trip_filters(req: PoiSearchRequest, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    exclude = {str(x).strip().lower() for x in (req.exclude_names or []) if str(x).strip()}
    include = {str(x).strip().lower() for x in (req.include_names or []) if str(x).strip()}
    trip_mode = str(req.trip_mode or "all").strip().lower()

    seen = set()
    pois: List[Dict[str, Any]] = []
    for hit in hits:
        poi = _normalize_poi_hit(hit)
        if not poi:
            continue

        poi_name = str(poi.get("name") or "").strip().lower()
        is_trip_poi = bool(poi_name and poi_name in include)

        if poi_name and poi_name in exclude:
            continue
        if trip_mode == "trip_only" and not is_trip_poi:
            continue
        if trip_mode == "non_trip" and is_trip_poi:
            continue

        key = (poi_name, round(float(poi.get("lat")), 6), round(float(poi.get("lon")), 6))
        if key in seen:
            continue
        seen.add(key)

        poi["is_trip_poi"] = is_trip_poi
        pois.append(poi)

    return pois


def _search_pois_in_bbox(req: PoiSearchRequest) -> Tuple[List[Dict[str, Any]], List[str]]:
    last_error: Optional[Exception] = None
    used_indices: List[str] = []
    candidate_indices = _candidate_poi_indices()
    if not candidate_indices:
        return [], used_indices

    for index_name in candidate_indices:
        try:
            res = os_client.search(index=index_name, body=_build_poi_query(req, "location"))
            hits = (res.get("hits") or {}).get("hits", [])
            used_indices.append(index_name)
            pois = _apply_trip_filters(req, hits)
            if pois or index_name == candidate_indices[-1]:
                return pois, used_indices
        except Exception as exc:
            last_error = exc
            continue

    if last_error:
        raise last_error
    return [], used_indices




@app.post("/api/pois/search")
async def search_pois(req: PoiSearchRequest):
    try:
        pois, used_indices = _search_pois_in_bbox(req)
        return {
            "pois": pois,
            "index": used_indices[0] if used_indices else POI_MAP_INDEX,
            "used_indices": used_indices,
            "configured_candidates": _candidate_poi_indices(),
        }
    except Exception as exc:
        return {
            "pois": [],
            "error": str(exc),
            "index": POI_MAP_INDEX,
            "used_indices": [],
            "configured_candidates": _candidate_poi_indices(),
        }


def _build_activity_data_from_poi(poi: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": poi.get("name"),
        "category": poi.get("category") or poi.get("type") or "POI",
        "description": poi.get("description") or poi.get("snippet") or "",
        "lat": _safe_float(poi.get("lat")),
        "lon": _safe_float(poi.get("lon")),
        "location": poi.get("city") or poi.get("source_location") or poi.get("address") or poi.get("location"),
        "city": poi.get("city") or poi.get("source_location"),
        "address": poi.get("address"),
        "website": poi.get("website"),
        "telephone": poi.get("telephone"),
        "opening_hours": poi.get("opening_hours") or poi.get("openingHoursSpecification"),
        "openingHoursSpecification": poi.get("openingHoursSpecification") or poi.get("opening_hours"),
        "duration_minutes": estimate_activity_duration_minutes(poi),
        "added_from_map": True,
        "source_id": poi.get("source_id"),
    }


def _extract_trip_endpoints(trip_obj: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    legs = list((trip_obj or {}).get("legs") or [])
    if not legs:
        return None, None, None, None
    first_leg = legs[0] or {}
    last_leg = legs[-1] or {}
    start_name = trip_obj.get("start") or first_leg.get("from")
    end_name = trip_obj.get("end") or last_leg.get("to")
    start_coords = tuple(first_leg.get("from_coords")[:2]) if _valid_coords(first_leg.get("from_coords")) else None
    end_coords = tuple(last_leg.get("to_coords")[:2]) if _valid_coords(last_leg.get("to_coords")) else None
    return start_name, end_name, start_coords, end_coords


def _reroute_between_points(
    *,
    start_name: Optional[str],
    end_name: Optional[str],
    start_coords: Optional[Tuple[float, float]],
    end_coords: Optional[Tuple[float, float]],
    time_str: str,
    route_preferences: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    routed = parse_json_result(
        plan_journey_logic(
            start=start_name,
            end=end_name,
            time_str=time_str,
            start_coords_override=start_coords,
            end_coords_override=end_coords,
            route_preferences=route_preferences,
            selection=selection,
        )
    )
    if isinstance(routed, dict) and routed.get("legs"):
        apply_trip_endpoint_labels(routed, start_name=start_name, end_name=end_name)
        recalc_trip_total_duration(routed)
        apply_query_preferences(routed, route_preferences)
    return routed


def _find_previous_activity_index(steps: List[Dict[str, Any]], day_indices: List[int], ref_idx: int) -> Optional[int]:
    for idx in range(ref_idx - 1, -1, -1):
        if idx not in day_indices:
            continue
        if steps[idx].get("type") == "activity":
            return idx
    return None


def _find_next_trip_index(steps: List[Dict[str, Any]], day_indices: List[int], ref_idx: int) -> Optional[int]:
    for idx in range(ref_idx + 1, len(steps)):
        if idx not in day_indices:
            continue
        if steps[idx].get("type") == "trip":
            return idx
    return None


def _find_first_trip_index(steps: List[Dict[str, Any]], day_indices: List[int]) -> Optional[int]:
    for idx in day_indices:
        if steps[idx].get("type") == "trip":
            return idx
    return None


def _find_last_trip_index(steps: List[Dict[str, Any]], day_indices: List[int]) -> Optional[int]:
    for idx in reversed(day_indices):
        if steps[idx].get("type") == "trip":
            return idx
    return None


def _detect_return_like_trip(trip_obj: Dict[str, Any]) -> bool:
    text_parts: List[str] = []
    for key in ("title", "description", "start", "end", "location", "label"):
        value = (trip_obj or {}).get(key)
        if isinstance(value, str) and value.strip():
            text_parts.append(value.strip().lower())
    for leg in (trip_obj or {}).get("legs") or []:
        for key in ("from", "to"):
            value = (leg or {}).get(key)
            if isinstance(value, str) and value.strip():
                text_parts.append(value.strip().lower())
    joined = " | ".join(text_parts)
    markers = [
        "unterkunft", "hotel", "hostel", "ferienwohnung", "zurück", "rückfahrt", "heim", "home", "check-in", "check out"
    ]
    return any(marker in joined for marker in markers)


def _determine_day_insert_context(
    current_trip: Dict[str, Any],
    selection: Optional[Dict[str, Any]],
    explicit_day_index: Optional[int],
    explicit_after_step_index: Optional[int],
) -> Dict[str, Any]:
    if current_trip.get("type") != "multi_step_plan":
        return {"error": "Gezieltes POI-Einfügen wird nur für Mehrtagespläne unterstützt."}

    steps = current_trip.get("steps", []) or []
    day_index = explicit_day_index
    selection_type = selection.get("selection_type") if isinstance(selection, dict) else None
    selection_step_index = selection.get("step_index") if isinstance(selection, dict) else None

    if not isinstance(day_index, int) and isinstance(selection, dict) and isinstance(selection.get("day_index"), int):
        day_index = selection.get("day_index")
    if not isinstance(day_index, int):
        day_index = 1

    day_indices = get_day_step_indices(current_trip, day_index)
    if not day_indices:
        return {"error": f"Tag {day_index} konnte im aktuellen Trip nicht gefunden werden."}

    # Highest priority: explicit anchor or explicit step selection.
    if isinstance(explicit_after_step_index, int) and explicit_after_step_index in day_indices:
        target_step = steps[explicit_after_step_index]
        if target_step.get("type") == "trip":
            return {
                "day_index": day_index,
                "trip_index": explicit_after_step_index,
                "anchor_activity_index": _find_previous_activity_index(steps, day_indices, explicit_after_step_index),
                "insert_mode": "split_selected_trip",
            }
        if target_step.get("type") == "activity":
            next_trip_idx = _find_next_trip_index(steps, day_indices, explicit_after_step_index)
            return {
                "day_index": day_index,
                "trip_index": next_trip_idx,
                "anchor_activity_index": explicit_after_step_index,
                "insert_mode": "after_selected_activity",
            }

    if isinstance(selection_step_index, int) and selection_step_index in day_indices:
        selected_step = steps[selection_step_index]
        if selection_type in {"trip", "leg", "step"} and selected_step.get("type") == "trip":
            return {
                "day_index": day_index,
                "trip_index": selection_step_index,
                "anchor_activity_index": _find_previous_activity_index(steps, day_indices, selection_step_index),
                "insert_mode": "split_selected_trip",
            }
        if selection_type == "activity" and selected_step.get("type") == "activity":
            next_trip_idx = _find_next_trip_index(steps, day_indices, selection_step_index)
            return {
                "day_index": day_index,
                "trip_index": next_trip_idx,
                "anchor_activity_index": selection_step_index,
                "insert_mode": "after_selected_activity",
            }

    activity_indices = [idx for idx in day_indices if steps[idx].get("type") == "activity"]
    trip_indices = [idx for idx in day_indices if steps[idx].get("type") == "trip"]

    if activity_indices:
        trailing_trip_idx = _find_next_trip_index(steps, day_indices, activity_indices[-1])
        if trailing_trip_idx is not None:
            trailing_trip = steps[trailing_trip_idx].get("data", {}) or {}
            insert_mode = "before_return_trip" if _detect_return_like_trip(trailing_trip) else "append_after_last_activity"
            return {
                "day_index": day_index,
                "trip_index": trailing_trip_idx,
                "anchor_activity_index": activity_indices[-1],
                "insert_mode": insert_mode,
            }
        return {
            "day_index": day_index,
            "trip_index": None,
            "anchor_activity_index": activity_indices[-1],
            "insert_mode": "append_end_of_day",
        }

    if trip_indices:
        selected_trip_idx = _find_last_trip_index(steps, day_indices) or trip_indices[0]
        return {
            "day_index": day_index,
            "trip_index": selected_trip_idx,
            "anchor_activity_index": None,
            "insert_mode": "split_day_trip_without_anchor",
        }

    return {"error": f"Für Tag {day_index} wurde keine passende Einfügeposition gefunden."}


def _get_activity_identity(activity: Dict[str, Any]) -> Tuple[Optional[str], Optional[Tuple[float, float]], int]:
    coords = _resolve_activity_coords(activity)
    return activity.get("name"), coords, estimate_activity_duration_minutes(activity)


def _resolve_selected_day_index(plan_data: Dict[str, Any], selection: Optional[Dict[str, Any]] = None) -> int:
    selected_day = (selection or {}).get("day_index") if isinstance(selection, dict) else None
    if isinstance(selected_day, int) and selected_day > 0:
        return selected_day
    steps = (plan_data or {}).get("steps", []) or []
    has_headers = any((step or {}).get("type") == "header" for step in steps)
    return 1 if not has_headers else 1


def _rebuild_day_schedule_from_index(
    plan_data: Dict[str, Any],
    day_index: int,
    start_step_index: int,
    route_preferences: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rebuilt_plan = copy.deepcopy(plan_data)
    day_indices = get_day_step_indices(rebuilt_plan, day_index)
    if not day_indices:
        return rebuilt_plan
    rebuilt_plan["steps"] = _rebuild_remaining_day_trips(
        rebuilt_plan.get("steps", []) or [],
        day_indices,
        start_step_index,
        route_preferences,
        selection=selection,
    )
    rebuilt_plan["query_preferences"] = dict(rebuilt_plan.get("query_preferences") or {}) | route_preferences
    return rebuilt_plan


def _rebuild_remaining_day_trips(
    steps: List[Dict[str, Any]],
    day_indices: List[int],
    start_step_index: int,
    route_preferences: Dict[str, Any],
    selection: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if not day_indices:
        return steps

    rebuilt = copy.deepcopy(steps)
    current_time: Optional[str] = None
    prev_name: Optional[str] = None
    prev_coords: Optional[Tuple[float, float]] = None

    for idx in day_indices:
        step = rebuilt[idx]
        step_type = step.get("type")

        if idx < start_step_index:
            if step_type == "trip":
                current_time = extract_trip_end_time(step.get("data", {})) or current_time
                _start_name, end_name, _start_coords, end_coords = _extract_trip_endpoints(step.get("data", {}))
                prev_name = end_name or prev_name
                prev_coords = end_coords or prev_coords
            elif step_type == "activity":
                activity = step.get("data", {}) or {}
                activity_name, activity_coords, activity_duration = _get_activity_identity(activity)
                prev_name = activity_name or prev_name
                prev_coords = activity_coords or prev_coords
                current_time = shift_clock_time(current_time, activity_duration) or current_time
            continue

        if step_type == "activity":
            activity = step.get("data", {}) or {}
            activity_name, activity_coords, activity_duration = _get_activity_identity(activity)
            prev_name = activity_name or prev_name
            prev_coords = activity_coords or prev_coords
            current_time = shift_clock_time(current_time, activity_duration) or current_time
            continue

        if step_type != "trip":
            continue

        original_trip = step.get("data", {}) or {}
        _orig_start_name, orig_end_name, _orig_start_coords, orig_end_coords = _extract_trip_endpoints(original_trip)
        departure_time = current_time or extract_trip_start_time(original_trip, "07:30")

        next_activity_idx = next((j for j in day_indices if j > idx and rebuilt[j].get("type") == "activity"), None)
        if next_activity_idx is not None:
            next_activity = rebuilt[next_activity_idx].get("data", {}) or {}
            next_name, next_coords, _dur = _get_activity_identity(next_activity)
            end_name = next_name or orig_end_name
            end_coords = next_coords or orig_end_coords
        else:
            end_name = orig_end_name
            end_coords = orig_end_coords

        if (prev_name or prev_coords) and (end_name or end_coords):
            rerouted = _reroute_between_points(
                start_name=prev_name,
                end_name=end_name,
                start_coords=prev_coords,
                end_coords=end_coords,
                time_str=build_tomorrow_time_str(departure_time, departure_time or "07:30"),
                route_preferences=route_preferences,
                selection=selection,
            )
            if isinstance(rerouted, dict) and rerouted.get("legs"):
                rebuilt[idx] = {"type": "trip", "data": rerouted}
                current_time = extract_trip_end_time(rerouted) or departure_time
                _rstart_name, rend_name, _rstart_coords, rend_coords = _extract_trip_endpoints(rerouted)
                prev_name = rend_name or end_name or prev_name
                prev_coords = rend_coords or end_coords or prev_coords
                continue

        current_time = extract_trip_end_time(original_trip) or departure_time
        prev_name = end_name or prev_name
        prev_coords = end_coords or prev_coords

    return rebuilt


def insert_poi_into_multiday_plan(
    current_trip: Dict[str, Any],
    poi: Dict[str, Any],
    *,
    selection: Optional[Dict[str, Any]],
    day_index: Optional[int],
    after_step_index: Optional[int],
    route_preferences: Dict[str, Any],
) -> Dict[str, Any]:
    if current_trip.get("type") != "multi_step_plan":
        return {"type": "error", "message": "Gezieltes POI-Einfügen wird nur für Mehrtagespläne unterstützt."}

    updated = copy.deepcopy(current_trip)
    steps = updated.get("steps", []) or []
    context = _determine_day_insert_context(updated, selection, day_index, after_step_index)
    if context.get("error"):
        return {"type": "error", "message": context.get("error")}

    target_day = context.get("day_index")
    target_trip_idx = context.get("trip_index")
    anchor_idx = context.get("anchor_activity_index")

    activity_data = _build_activity_data_from_poi(poi)
    if activity_data.get("lat") is None or activity_data.get("lon") is None:
        return {"type": "error", "message": "Der ausgewählte POI hat keine gültigen Koordinaten."}

    day_indices = get_day_step_indices(updated, target_day)
    if not day_indices:
        return {"type": "error", "message": f"Tag {target_day} konnte im aktuellen Trip nicht gefunden werden."}

    # Determine insertion baseline. Prefer splitting a concrete selected/day trip. Fallback to appending after anchor activity.
    target_trip = steps[target_trip_idx].get("data", {}) if isinstance(target_trip_idx, int) and 0 <= target_trip_idx < len(steps) and steps[target_trip_idx].get("type") == "trip" else None

    if target_trip is None and anchor_idx is not None:
        next_trip_idx = _find_next_trip_index(steps, day_indices, anchor_idx)
        if isinstance(next_trip_idx, int):
            target_trip_idx = next_trip_idx
            target_trip = steps[next_trip_idx].get("data", {}) or {}

    if anchor_idx is not None:
        anchor_activity = steps[anchor_idx].get("data", {}) or {}
        anchor_coords = _resolve_activity_coords(anchor_activity, selection)
        anchor_name = anchor_activity.get("name")
    else:
        anchor_activity = {}
        anchor_coords = None
        anchor_name = None

    if target_trip is not None:
        old_departure = extract_trip_start_time(target_trip, "07:30")
        start_name, end_name, start_coords, end_coords = _extract_trip_endpoints(target_trip)

        outbound_start_name = anchor_name or start_name
        outbound_start_coords = anchor_coords or start_coords
        if not outbound_start_name and not outbound_start_coords:
            return {"type": "error", "message": "Die Einfügeposition hat keine gültigen Startkoordinaten für das Routing."}

        outbound_trip = _reroute_between_points(
            start_name=outbound_start_name,
            end_name=activity_data.get("name"),
            start_coords=outbound_start_coords,
            end_coords=(activity_data["lat"], activity_data["lon"]),
            time_str=build_tomorrow_time_str(old_departure, old_departure),
            route_preferences=route_preferences,
            selection=selection,
        )
        if "legs" not in outbound_trip:
            return outbound_trip

        arrival_time = extract_trip_end_time(outbound_trip) or old_departure
        next_departure = shift_clock_time(arrival_time, estimate_activity_duration_minutes(activity_data)) or arrival_time
        onward_trip = _reroute_between_points(
            start_name=activity_data.get("name"),
            end_name=end_name,
            start_coords=(activity_data["lat"], activity_data["lon"]),
            end_coords=end_coords,
            time_str=build_tomorrow_time_str(next_departure, next_departure),
            route_preferences=route_preferences,
            selection=selection,
        )
        if "legs" not in onward_trip:
            return onward_trip

        replacement = [{"type": "trip", "data": outbound_trip}, {"type": "activity", "data": activity_data}, {"type": "trip", "data": onward_trip}]
        updated_steps = list(steps[:target_trip_idx]) + replacement + list(steps[target_trip_idx + 1:])
        inserted_step_index = target_trip_idx + 1
    elif anchor_idx is not None:
        # End-of-day append without an existing following trip.
        anchor_departure = extract_trip_end_time(steps[_find_next_trip_index(steps, day_indices, anchor_idx)].get("data", {})) if _find_next_trip_index(steps, day_indices, anchor_idx) is not None else None
        if not anchor_departure:
            anchor_departure = "17:00"
        if anchor_coords is None:
            return {"type": "error", "message": "Die Anker-Aktivität hat keine Koordinaten für das Routing."}
        outbound_trip = _reroute_between_points(
            start_name=anchor_name,
            end_name=activity_data.get("name"),
            start_coords=anchor_coords,
            end_coords=(activity_data["lat"], activity_data["lon"]),
            time_str=build_tomorrow_time_str(anchor_departure, anchor_departure),
            route_preferences=route_preferences,
            selection=selection,
        )
        if "legs" not in outbound_trip:
            return outbound_trip
        replacement = [{"type": "trip", "data": outbound_trip}, {"type": "activity", "data": activity_data}]
        updated_steps = list(steps[:anchor_idx + 1]) + replacement + list(steps[anchor_idx + 1:])
        inserted_step_index = anchor_idx + 2
    else:
        return {"type": "error", "message": "Für den ausgewählten Tag konnte keine gültige Einfügeposition mit Routing-Basis bestimmt werden."}

    refreshed_day_indices = get_day_step_indices({**updated, "steps": updated_steps}, target_day)
    if target_trip is not None and isinstance(target_trip_idx, int):
        rebuild_start_index = target_trip_idx
    elif anchor_idx is not None:
        rebuild_start_index = anchor_idx + 1
    else:
        rebuild_start_index = inserted_step_index + 1
    updated_steps = _rebuild_remaining_day_trips(
        updated_steps,
        refreshed_day_indices,
        rebuild_start_index,
        route_preferences,
        selection=selection,
    )

    updated["steps"] = updated_steps
    updated["query_preferences"] = dict(updated.get("query_preferences") or {}) | route_preferences
    updated["selection"] = {
        "selection_type": "activity",
        "day_index": target_day,
        "step_index": inserted_step_index,
        "label": activity_data.get("name"),
        "name": activity_data.get("name"),
        "coords": [activity_data.get("lat"), activity_data.get("lon")],
        "insert_mode": context.get("insert_mode"),
    }
    return updated


@app.post("/api/trip/add_poi")
async def add_poi_to_trip(req: AddPoiRequest):
    session_state = get_session_state(req.session_id)
    request_state = ensure_request_state(session_state)
    poi = dict(req.poi or {})
    name = _clean_value(poi.get("name"))
    lat = _safe_float(poi.get("lat"))
    lon = _safe_float(poi.get("lon"))
    if not name or lat is None or lon is None:
        return {"status": "error", "message": "POI braucht mindestens name, lat und lon."}

    poi["name"] = name
    poi["lat"] = lat
    poi["lon"] = lon

    existing = list(request_state.get("selected_pois") or [])
    if not any(isinstance(item, dict) and item.get("name") == name and _safe_float(item.get("lat")) == lat and _safe_float(item.get("lon")) == lon for item in existing):
        existing.append(poi)
    request_state["selected_pois"] = existing
    session_state["request_state"] = request_state

    effective_selection = req.selection or session_state.get("selection")
    current_trip = session_state.get("current_trip")
    route_preferences = request_state.get("route_preferences") or session_state.get("route_preferences") or {}

    trip = None
    if isinstance(current_trip, dict) and current_trip.get("type") == "multi_step_plan":
        inserted = insert_poi_into_multiday_plan(
            current_trip,
            poi,
            selection=effective_selection,
            day_index=req.day_index,
            after_step_index=req.after_step_index,
            route_preferences=route_preferences,
        )
        if inserted.get("type") == "error" or inserted.get("error"):
            return {
                "status": "partial_success",
                "message": f"POI gespeichert, aber gezieltes Einfügen fehlgeschlagen: {inserted.get('message') or inserted.get('error')}",
                "selected_pois": existing,
                "trip": None,
            }
        trip = inserted
        session_state["current_trip"] = trip
        session_state["selection"] = trip.get("selection") or effective_selection
        request_state["fulfilled"] = True
        session_state["request_state"] = request_state
    elif not get_missing_request_fields(request_state):
        try:
            result_str = execute_request_state(request_state, {
                "session_id": req.session_id,
                "selected_pois": existing,
                "current_trip": current_trip,
                "route_preferences": route_preferences,
                "selection": effective_selection,
            })
            trip = parse_json_result(result_str)
            update_session_from_result(session_state, result_str, effective_selection)
            request_state["fulfilled"] = True
            session_state["request_state"] = request_state
        except Exception as exc:
            return {"status": "partial_success", "message": f"POI übernommen, aber Trip-Replanning fehlgeschlagen: {exc}", "selected_pois": existing}

    return {
        "status": "success",
        "selected_pois": existing,
        "trip": trip,
        "selection": session_state.get("selection"),
        "request_state": {
            "trip_type": request_state.get("trip_type"),
            "start": request_state.get("start"),
            "end": request_state.get("end"),
            "base_location": request_state.get("base_location"),
            "selected_pois": [item.get("name") for item in existing if isinstance(item, dict) and item.get("name")],
        },
    }


def get_session_state(session_id: Optional[str]) -> Dict[str, Any]:
    key = session_id or 'anonymous'
    if key not in SESSION_STATE:
        SESSION_STATE[key] = {
            'current_trip': None,
            'selection': None,
            'route_preferences': {},
            'last_error': None,
            'request_state': None,
        }
    return SESSION_STATE[key]


@app.post("/api/save_trip")
async def save_trip(request: Request):
    try:
        trip_data = await request.json()
        trip_id = str(uuid.uuid4())
        os_client.index(index="saved-trips", id=trip_id, body=trip_data)
        print(f"💾 Trip {trip_id} erfolgreich in DB gespeichert!")
        return {"status": "success", "id": trip_id}
    except Exception as e:
        print(f"❌ Fehler beim Speichern: {e}")
        return {"status": "error", "message": str(e)}


ROUTE_PREFERENCE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "primary_mode": {
            "type": "string",
            "enum": ["TRANSIT", "CAR", "BICYCLE", "WALK"],
            "description": "Bevorzugter Hauptmodus.",
        },
        "allowed_modes": {
            "type": "array",
            "items": {"type": "string", "enum": ["TRANSIT", "CAR", "BICYCLE", "WALK"]},
            "description": "Erlaubte Modi insgesamt. Bei Auto mindestens CAR setzen.",
        },
        "arrive_by": {"type": "boolean"},
        "wheelchair_accessible": {"type": "boolean"},
        "avoid_transfers": {"type": "boolean"},
        "max_walk_distance": {"type": "number"},
        "walk_reluctance": {"type": "number"},
        "wait_reluctance": {"type": "number"},
        "transfer_penalty": {"type": "integer"},
        "min_transfer_time": {"type": "integer"},
        "max_transfers": {"type": "integer"},
        "num_itineraries": {"type": "integer"},
    },
}

SELECTION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "selection_type": {
            "type": "string",
            "enum": ["trip", "day", "step", "leg", "activity", "stop", "none"],
        },
        "message_id": {"type": "integer"},
        "day_index": {"type": "integer"},
        "step_index": {"type": "integer"},
        "leg_index": {"type": "integer"},
        "label": {"type": "string"},
        "name": {"type": "string"},
        "from_name": {"type": "string"},
        "to_name": {"type": "string"},
        "coords": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
        "replacement_coords": {
            "type": "array",
            "items": {"type": "number"},
            "minItems": 2,
            "maxItems": 2,
        },
    },
}

EDIT_OPERATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": [
                "regenerate_trip",
                "regenerate_step",
                "regenerate_leg",
                "reroute_day",
                "move_activity",
                "replace_activity",
                "delete_activity",
                "apply_route_preferences",
            ],
        },
        "scope": {"type": "string", "enum": ["trip", "day", "step", "leg", "activity", "stop"]},
    },
}


def add_optional_properties(properties: Dict[str, Any]) -> Dict[str, Any]:
    properties["route_preferences"] = ROUTE_PREFERENCE_SCHEMA
    properties["selection"] = SELECTION_SCHEMA
    properties["edit_operation"] = EDIT_OPERATION_SCHEMA
    return properties


tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "get_simple_route",
            "description": (
                "Berechnet eine reine Verbindung von A nach B. Übertrage Transportwünsche des Users konsequent "
                "in route_preferences. Wenn eine bestehende Auswahl geändert werden soll, selection und edit_operation setzen."
            ),
            "parameters": {
                "type": "object",
                "properties": add_optional_properties(
                    {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "time_str": {"type": "string"},
                    }
                ),
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_local_places",
            "description": "Sucht eine Liste von Orten/Aktivitäten.",
            "parameters": {
                "type": "object",
                "properties": add_optional_properties(
                    {
                        "location": {"type": "string"},
                        "interest": {"type": "string"},
                    }
                ),
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_single_day_trip",
            "description": (
                "Plant einen Tagesausflug. Nutze selection/edit_operation nur dann, wenn tatsächlich ein "
                "bestehender Teilplan gezielt geändert werden soll."
            ),
            "parameters": {
                "type": "object",
                "properties": add_optional_properties(
                    {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "interest": {"type": "string"},
                        "num_stops": {"type": "integer"},
                        "avoid_places": {"type": "array", "items": {"type": "string"}},
                        "time_str": {"type": "string"},
                        "selected_pois": {"type": "array", "items": {"type": "object"}},
                    }
                ),
                "required": ["start", "end", "interest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_multiday_trip",
            "description": "Plant eine Mehrtagesreise. Übertrage Transport- und Routingwünsche in route_preferences.",
            "parameters": {
                "type": "object",
                "properties": add_optional_properties(
                    {
                        "start": {"type": "string"},
                        "end": {"type": "string"},
                        "days": {"type": "integer"},
                        "hotel_pref": {"type": "string"},
                        "activity_pref": {"type": "string"},
                        "food_pref": {"type": "string"},
                        "culture_pref": {"type": "string"},
                        "avoid_places": {"type": "array", "items": {"type": "string"}},
                        "time_str": {"type": "string"},
                        "selected_pois": {"type": "array", "items": {"type": "object"}},
                    }
                ),
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_best_city",
            "description": "Internal Tool: Findet eine passende Stadt, falls der User kein klares Ziel angegeben hat.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


def normalize_ws_payload(raw_text: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw_text)
        if isinstance(payload, dict) and payload.get("type") == "chat_request":
            payload.setdefault("session_id", None)
            return payload
    except Exception:
        pass
    return {"type": "chat_request", "text": raw_text, "session_id": None}


# ----------------------
# Structured request engine
# ----------------------

REQUEST_FIELD_LABELS: Dict[str, str] = {
    "trip_type": "Anfragetyp",
    "start": "Startort",
    "end": "Zielort",
    "base_location": "Basisort",
    "origin": "Abfahrtsort",
    "travel_window": "Zeitfenster",
    "transport_mode": "Verkehrsmittel",
    "days": "Anzahl der Tage",
    "date": "Datum",
    "interest": "Interessen",
    "pace": "Belastung",
    "activities_per_day": "Aktivitäten pro Tag",
}

SOCIAL_CHAT_PHRASES = {
    "hey", "hi", "hallo", "moin", "servus", "yo", "tag", "guten tag", "guten morgen",
    "guten abend", "wie geht es dir", "wie geht's dir", "wie gehts dir", "danke", "dankeschön",
    "dankeschoen", "danke dir", "vielen dank", "thx", "thanks", "ok", "okay", "oki",
    "alles klar", "super", "perfekt", "cool", "nice", "top", "gut", "passt", "wunderbar",
}

TRIP_TYPE_HINT_PATTERNS = {
    "point_to_point": [r"verbindung", r"route", r"von.*nach", r"from.*to"],
    "day_trip": [r"tagesausflug", r"day\s*trip", r"ausflug"],
    "local_search": [r"aktivitäten", r"aktivitaeten", r"things to do", r"vor ort"],
    "multiday": [r"mehrtag\w*", r"mehrtages\w*", r"multi\s*day", r"road trip"],
    "base_explore": [r"rund\s+um", r"around"],
}

PACE_ALIASES = {
    "easy": "EASY",
    "leicht": "EASY",
    "entspannt": "EASY",
    "relaxed": "EASY",
    "medium": "MEDIUM",
    "mittel": "MEDIUM",
    "normal": "MEDIUM",
    "balanced": "MEDIUM",
    "heavy": "HEAVY",
    "voll": "HEAVY",
    "intensiv": "HEAVY",
    "packed": "HEAVY",
    "ambitious": "HEAVY",
}


def build_empty_request_state() -> Dict[str, Any]:
    return {
        "trip_type": None,
        "start": None,
        "end": None,
        "base_location": None,
        "origin": None,
        "travel_window": None,
        "transport_mode": None,
        "roundtrip_base": False,
        "days": None,
        "date": None,
        "time_str": None,
        "interest": None,
        "pace": None,
        "activities_per_day": None,
        "hotel_pref": None,
        "activity_pref": None,
        "food_pref": None,
        "culture_pref": None,
        "pending_question_field": None,
        "pending_question_optional": False,
        "missing_fields": [],
        "optional_fields_remaining": [],
        "skipped_optional_fields": [],
        "raw_user_requests": [],
        "route_preferences": {},
        "selected_pois": [],
        "fulfilled": False,
    }



OPTIONAL_DECLINE_PATTERNS = [
    r"^no$", r"^nein$", r"^none$", r"^skip$", r"^überspringen$", r"^ueberspringen$",
    r"^egal$", r"^ist mir egal$", r"^keine$", r"^nichts$", r"^brauche ich nicht$", r"^default$",
]


def _is_decline_answer(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    return any(re.search(pattern, cleaned) for pattern in OPTIONAL_DECLINE_PATTERNS)


def _normalize_trip_type(value: Optional[str]) -> Optional[str]:
    lower = (value or "").strip().lower()
    mapping = {
        "route": "point_to_point", "point_to_point": "point_to_point", "verbindung": "point_to_point",
        "day_trip": "day_trip", "tagesausflug": "day_trip", "ausflug": "day_trip",
        "base_explore": "base_explore", "local_search": "local_search", "aktivitäten": "local_search", "activities": "local_search",
        "multiday": "multiday", "mehrtag": "multiday", "mehrtagesreise": "multiday", "rundreise": "multiday",
    }
    if lower in mapping:
        return mapping[lower]
    if re.search(r"route|verbindung|von .* nach|from .* to", lower):
        return "point_to_point"
    if re.search(r"mehrtag|multi|rundreise|road trip", lower):
        return "multiday"
    if re.search(r"aktivit|things to do|sehensw", lower):
        return "local_search"
    if re.search(r"ausflug|day trip|trip around|rund um", lower):
        return "day_trip"
    return None


def ensure_request_state(session_state: Dict[str, Any]) -> Dict[str, Any]:
    state = session_state.get("request_state")
    if not isinstance(state, dict):
        state = build_empty_request_state()
        session_state["request_state"] = state
    return state


def _clean_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = str(value).strip().strip("\"'` ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.!?")
    return cleaned or None


def _extract_fragment(text: str, patterns: List[str]) -> Optional[str]:
    text = text or ""
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = match.groupdict().get("value")
        if value is None and match.groups():
            value = match.group(1)
        value = _clean_value(value)
        if value:
            return value
    return None


def _extract_start_location(text: str) -> Optional[str]:
    return _extract_fragment(
        text,
        [
            r"\bfrom\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:to|with|for|by|tomorrow|today|around|in)\b|[,.!?]|$))",
            r"\bstarting\s+from\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:to|with|for|by|tomorrow|today|around|in)\b|[,.!?]|$))",
            r"\bvon\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:nach|mit|für|morgen|heute|rund\s+um|im)\b|[,.!?]|$))",
            r"\bab\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:nach|mit|für|morgen|heute|rund\s+um|im)\b|[,.!?]|$))",
        ],
    )


def _extract_end_location(text: str) -> Optional[str]:
    return _extract_fragment(
        text,
        [
            r"\bto\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:with|for|by|tomorrow|today)\b|[,.!?]|$))",
            r"\bgo\s+to\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:with|for|by|tomorrow|today)\b|[,.!?]|$))",
            r"\bnach\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:mit|für|morgen|heute)\b|[,.!?]|$))",
        ],
    )


def _extract_in_location(text: str) -> Optional[str]:
    return _extract_fragment(
        text,
        [
            r"\baround\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:with|for|by|tomorrow|today)\b|[,.!?]|$))",
            r"\bnear\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:with|for|by|tomorrow|today)\b|[,.!?]|$))",
            r"\bin\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:with|for|by|tomorrow|today)\b|[,.!?]|$))",
            r"\brund\s+um\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:mit|für|morgen|heute)\b|[,.!?]|$))",
            r"\bim\s+raum\s+(?P<value>[^,.!?]+?)(?=(?:\s+(?:mit|für|morgen|heute)\b|[,.!?]|$))",
        ],
    )


def _detect_roundtrip_base(text: str) -> Optional[str]:
    return _extract_fragment(
        text,
        [
            r"\baround\s+(?P<value>[^,.!?]+?)($|[,.!?]|\s+(?:with|for|by|tomorrow|today))",
            r"\brund\s+um\s+(?P<value>[^,.!?]+?)($|[,.!?]|\s+(?:mit|für|morgen|heute))",
            r"\bnear\s+(?P<value>[^,.!?]+?)($|[,.!?]|\s+(?:with|for|by|tomorrow|today))",
        ],
    )


def _extract_days(text: str) -> Optional[int]:
    text = text or ""
    match = re.search(r"\b(\d+)\s*(?:day|days|tage|tagen)\b", text, re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))
    word_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ein": 1, "eine": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "funf": 5}
    for word, value in word_map.items():
        if re.search(rf"\b{re.escape(word)}\s*(?:day|days|tage|tagen)\b", text, re.IGNORECASE):
            return value
    return None


def _extract_date_phrase(text: str) -> Optional[str]:
    text = text or ""
    keywords = [
        "today", "tomorrow", "tonight", "this weekend", "next weekend", "next week",
        "heute", "morgen", "übermorgen", "uebermorgen", "dieses wochenende", "nächstes wochenende", "naechstes wochenende", "nächste woche", "naechste woche",
        "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    ]
    lower = text.lower()
    for keyword in keywords:
        if keyword in lower:
            return keyword
    explicit = re.search(r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\b", text)
    if explicit:
        return explicit.group(1)
    return None


def _extract_interest_phrase(text: str) -> Optional[str]:
    text = text or ""
    direct = _extract_fragment(
        text,
        [
            r"\bwith\s+(?P<value>[^,.!?]+?)$",
            r"\bfor\s+(?P<value>[^,.!?]+?)$",
            r"\bmit\s+(?P<value>[^,.!?]+?)$",
            r"\binterest(?:s)?\s*[:=-]?\s*(?P<value>[^,.!?]+?)$",
        ],
    )
    if direct and not _match_mode_in_fragment(direct.lower()):
        return direct

    buckets = []
    lower = text.lower()
    if re.search(r"museum|culture|kultur|gallery|ausstellung", lower):
        buckets.append("Kultur")
    if re.search(r"hike|wandern|nature|natur|park|lake|see", lower):
        buckets.append("Natur")
    if re.search(r"food|restaurant|essen|cafe|café|kulinar", lower):
        buckets.append("Gastronomie")
    if re.search(r"shopping|einkauf|markt", lower):
        buckets.append("Shopping")
    if re.search(r"family|kinder|famil", lower):
        buckets.append("Familie")
    return ", ".join(dict.fromkeys(buckets)) if buckets else None


def _extract_pace(text: str) -> Optional[str]:
    lower = (text or "").lower()
    for alias, normalized in PACE_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lower):
            return normalized
    if re.search(r"more relaxed|less packed|weniger voll|weniger stress", lower):
        return "EASY"
    if re.search(r"more packed|voller|mehr programm|mehr aktivitäten", lower):
        return "HEAVY"
    return None


def _extract_activities_per_day(text: str) -> Optional[int]:
    text = text or ""
    patterns = [
        r"\b(\d+)\s+activities?\s+per\s+day\b",
        r"\b(\d+)\s+stops?\s+per\s+day\b",
        r"\b(\d+)\s+(?:aktivitäten|stopps?)\s+pro\s+tag\b",
        r"\b(?:activities?|stops?|aktivitäten|stopps?)\s+per\s+day\s+(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return max(1, min(8, int(match.group(1))))
    return None


def infer_trip_type(text: str, updates: Dict[str, Any], current_state: Dict[str, Any]) -> Optional[str]:
    lower = (text or "").lower()
    existing = current_state.get("trip_type")

    if current_state.get("pending_question_field") == "trip_type":
        normalized = _normalize_trip_type(text)
        if normalized:
            return normalized

    if any(word in lower for word in ["things to do", "what to do", "activities", "aktivitäten", "aktivitaeten", "sehenswürdigkeiten", "sehenswuerdigkeiten"]):
        return "local_search"
    if updates.get("days") or any(word in lower for word in ["multiday", "mehrtag", "road trip", "round trip", "rundreise"]):
        return "multiday"
    if updates.get("base_location") or re.search(r"around|rund\s+um|near", lower):
        return "base_explore"
    if updates.get("start") and updates.get("end"):
        return "point_to_point"
    if any(word in lower for word in ["route", "connection", "verbindung", "from", "to", "von", "nach"]):
        return "point_to_point"
    normalized = _normalize_trip_type(text)
    if normalized:
        return normalized
    return existing


def merge_request_state(existing: Dict[str, Any], updates: Dict[str, Any], raw_text: str = "") -> Dict[str, Any]:
    merged = copy.deepcopy(existing or build_empty_request_state())
    for key, value in updates.items():
        if value is None:
            continue
        if key == "route_preferences":
            merged[key] = dict(merged.get(key) or {}) | dict(value or {})
        elif key == "skipped_optional_fields":
            prev = list(merged.get(key) or [])
            for item in value or []:
                if item not in prev:
                    prev.append(item)
            merged[key] = prev
        elif key == "selected_pois":
            existing_items = list(merged.get("selected_pois") or [])
            seen = {str(item.get("name")) for item in existing_items if isinstance(item, dict) and item.get("name")}
            for item in value or []:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "").strip()
                if not name or name in seen:
                    continue
                existing_items.append(item)
                seen.add(name)
            merged[key] = existing_items
        else:
            merged[key] = value

    if raw_text:
        merged["raw_user_requests"] = (merged.get("raw_user_requests") or []) + [raw_text]
        merged["raw_user_requests"] = merged["raw_user_requests"][-12:]

    if merged.get("base_location") and merged.get("roundtrip_base"):
        if not merged.get("start"):
            merged["start"] = merged["base_location"]
        if not merged.get("end"):
            merged["end"] = merged["base_location"]

    return merged


PARSER_TOOL = {
    "type": "function",
    "function": {
        "name": "parse_travel_request",
        "description": "Extrahiert strukturierte Reisewünsche oder die Antwort auf eine offene Rückfrage.",
        "parameters": {
            "type": "object",
            "properties": {
                "answer_field": {"type": "string"},
                "trip_type": {"type": "string"},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "base_location": {"type": "string"},
                "origin": {"type": "string"},
                "travel_window": {"type": "string"},
                "days": {"type": "integer"},
                "date": {"type": "string"},
                "time_str": {"type": "string"},
                "interest": {"type": "string"},
                "pace": {"type": "string"},
                "activities_per_day": {"type": "integer"},
                "transport_mode": {"type": "string"}
            }
        }
    }
}


def _normalize_transport_mode(value: Optional[str]) -> Optional[str]:
    lower = (value or "").strip().lower()
    if not lower:
        return None
    if any(token in lower for token in ["zug", "train", "bahn", "bus", "öpnv", "oepnv", "transit", "public"]):
        return "TRANSIT"
    if any(token in lower for token in ["auto", "car", "pkw"]):
        return "CAR"
    if any(token in lower for token in ["bike", "fahrrad", "rad"]):
        return "BICYCLE"
    if any(token in lower for token in ["walk", "zu fuß", "zu fuss", "laufen", "fuß", "fuss"]):
        return "WALK"
    return None


def _apply_transport_mode_to_route_preferences(mode: Optional[str], current: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    prefs = dict(current or {})
    normalized = _normalize_transport_mode(mode)
    if normalized == "TRANSIT":
        prefs.update({"primary_mode": "TRANSIT", "allowed_modes": ["TRANSIT"]})
    elif normalized == "CAR":
        prefs.update({"primary_mode": "CAR", "allowed_modes": ["CAR"]})
    elif normalized == "BICYCLE":
        prefs.update({"primary_mode": "BICYCLE", "allowed_modes": ["BICYCLE"]})
    elif normalized == "WALK":
        prefs.update({"primary_mode": "WALK", "allowed_modes": ["WALK"]})
    return prefs


def _resolve_relative_date_phrase(text: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    value = _clean_value(text)
    if not value:
        return None, None
    lower = value.lower()
    today = date.today()
    weekdays = {
        "montag": 0, "monday": 0, "dienstag": 1, "tuesday": 1, "mittwoch": 2, "wednesday": 2,
        "donnerstag": 3, "thursday": 3, "freitag": 4, "friday": 4, "samstag": 5, "saturday": 5,
        "sonntag": 6, "sunday": 6,
    }
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value, None
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", value)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), m.group(3)
        year_val = today.year if year is None else int(year)
        if year_val < 100:
            year_val += 2000
        try:
            return date(year_val, month, day).isoformat(), None
        except Exception:
            return value, None
    if lower in {"heute", "today"}:
        return today.isoformat(), None
    if lower in {"morgen", "tomorrow"}:
        return (today + timedelta(days=1)).isoformat(), None
    if lower in {"übermorgen", "uebermorgen"}:
        return (today + timedelta(days=2)).isoformat(), None
    if lower in {"dieses wochenende", "this weekend"}:
        saturday = today + timedelta((5 - today.weekday()) % 7)
        return None, f"{saturday.isoformat()} bis {(saturday + timedelta(days=1)).isoformat()}"
    if lower in {"nächstes wochenende", "naechstes wochenende", "next weekend"}:
        saturday = today + timedelta(((5 - today.weekday()) % 7) + 7)
        return None, f"{saturday.isoformat()} bis {(saturday + timedelta(days=1)).isoformat()}"
    if lower in {"nächste woche", "naechste woche", "next week"}:
        monday = today + timedelta((7 - today.weekday()) % 7 or 7)
        return None, f"{monday.isoformat()} bis {(monday + timedelta(days=6)).isoformat()}"
    for name, weekday in weekdays.items():
        if lower == name:
            delta = (weekday - today.weekday()) % 7 or 7
            return (today + timedelta(days=delta)).isoformat(), None
    return None, value


def _sanitize_parser_updates(raw: Dict[str, Any], current_state: Dict[str, Any]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    answer_field = _clean_value(raw.get("answer_field"))
    if answer_field in REQUEST_FIELD_LABELS:
        updates["answer_field"] = answer_field
    trip_type = _normalize_trip_type(raw.get("trip_type"))
    if trip_type:
        updates["trip_type"] = trip_type
    for key in ["start", "end", "base_location", "origin", "travel_window", "interest"]:
        value = _clean_value(raw.get(key))
        if value:
            updates[key] = value
    if isinstance(raw.get("days"), int) and raw.get("days") > 0:
        updates["days"] = int(raw.get("days"))
    if isinstance(raw.get("activities_per_day"), int) and raw.get("activities_per_day") > 0:
        updates["activities_per_day"] = max(1, min(8, int(raw.get("activities_per_day"))))
    pace = _extract_pace(str(raw.get("pace") or ""))
    if pace:
        updates["pace"] = pace
    transport_mode = _normalize_transport_mode(raw.get("transport_mode"))
    if transport_mode:
        updates["transport_mode"] = transport_mode
        updates["route_preferences"] = _apply_transport_mode_to_route_preferences(transport_mode, current_state.get("route_preferences"))
    date_value = _clean_value(raw.get("date"))
    if date_value:
        normalized, travel_window = _resolve_relative_date_phrase(date_value)
        if normalized:
            updates["date"] = normalized
            updates["time_str"] = f"{normalized} 09:00"
        elif travel_window:
            updates["travel_window"] = travel_window
    time_str = _clean_value(raw.get("time_str"))
    if time_str:
        updates["time_str"] = time_str
    if updates.get("origin") and not updates.get("start") and not current_state.get("start"):
        updates["start"] = updates["origin"]
    if updates.get("base_location") and updates.get("trip_type") in {"base_explore", "local_search"}:
        updates["roundtrip_base"] = True
        updates.setdefault("start", updates["base_location"])
        updates.setdefault("end", updates["base_location"])
    return updates


def llm_extract_request_updates(text: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = {k: current_state.get(k) for k in ["trip_type", "start", "end", "base_location", "origin", "travel_window", "days", "date", "interest", "pace", "activities_per_day", "transport_mode", "pending_question_field"]}
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=[
            {"role": "system", "content": "Du extrahierst strukturierte Reisewünsche aus Freitext. Wenn der Nutzer auf eine Rückfrage antwortet, gib das passende Zielfeld in answer_field an. Trip-Typ nur setzen, wenn die neue Nachricht ihn wirklich festlegt. Relative Zeitangaben wenn möglich als date, sonst als travel_window."},
            {"role": "user", "content": json.dumps({"user_text": text, "current_state": snapshot}, ensure_ascii=False)},
        ],
        tools=[PARSER_TOOL],
        tool_choice={"type": "function", "function": {"name": "parse_travel_request"}},
    )
    tool_calls = getattr(response.choices[0].message, "tool_calls", None) or []
    if not tool_calls:
        return {}
    args = json.loads(tool_calls[0].function.arguments or "{}")
    if not isinstance(args, dict):
        return {}
    return _sanitize_parser_updates(args, current_state)


def regex_extract_request_updates(text: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = _clean_value(text) or ""
    updates: Dict[str, Any] = {}
    pending_field = current_state.get("pending_question_field")
    pending_optional = bool(current_state.get("pending_question_optional"))

    if pending_field:
        if pending_optional and _is_decline_answer(cleaned):
            updates["skipped_optional_fields"] = [pending_field]
            return updates
        if pending_field == "trip_type":
            updates["trip_type"] = _normalize_trip_type(cleaned)
            return updates
        if pending_field == "days":
            updates["days"] = _extract_days(cleaned) or _extract_activities_per_day(cleaned) or (int(cleaned) if cleaned.isdigit() else None)
            return updates
        if pending_field == "activities_per_day":
            updates["activities_per_day"] = _extract_activities_per_day(cleaned) or (int(cleaned) if cleaned.isdigit() else None)
            return updates
        if pending_field == "pace":
            updates["pace"] = _extract_pace(cleaned) or (cleaned.upper() if cleaned.upper() in {"EASY", "MEDIUM", "HEAVY"} else None)
            return updates
        if pending_field in {"start", "end", "base_location", "date", "interest", "transport_mode"} and cleaned:
            updates[pending_field] = cleaned
            if pending_field == "date":
                updates["time_str"] = f"{cleaned} 09:00"
            return updates

    roundtrip_base = _detect_roundtrip_base(cleaned)
    if roundtrip_base:
        updates["base_location"] = roundtrip_base
        updates["roundtrip_base"] = True

    start = _extract_start_location(cleaned)
    end = _extract_end_location(cleaned)
    if start:
        updates["start"] = start
    if end:
        updates["end"] = end

    date_phrase = _extract_date_phrase(cleaned)
    if date_phrase:
        normalized_date, travel_window = _resolve_relative_date_phrase(date_phrase)
        if normalized_date:
            updates["date"] = normalized_date
            updates["time_str"] = f"{normalized_date} 09:00"
        elif travel_window:
            updates["travel_window"] = travel_window

    days = _extract_days(cleaned)
    if days is not None:
        updates["days"] = days

    interest = _extract_interest_phrase(cleaned)
    if interest:
        updates["interest"] = interest

    pace = _extract_pace(cleaned)
    if pace:
        updates["pace"] = pace

    activities_per_day = _extract_activities_per_day(cleaned)
    if activities_per_day is not None:
        updates["activities_per_day"] = activities_per_day

    transport_mode = _normalize_transport_mode(cleaned)
    if transport_mode:
        updates["transport_mode"] = transport_mode
        updates["route_preferences"] = _apply_transport_mode_to_route_preferences(transport_mode, current_state.get("route_preferences"))

    request_type = infer_trip_type(cleaned, updates, current_state)
    if request_type:
        updates["trip_type"] = request_type

    if not updates.get("base_location") and not updates.get("start") and not updates.get("end"):
        inferred_location = _extract_in_location(cleaned)
        if inferred_location and request_type in {"base_explore", "multiday", "local_search"}:
            updates["base_location"] = inferred_location
            if request_type in {"base_explore", "local_search"}:
                updates["roundtrip_base"] = True

    return updates


def extract_request_updates(text: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = _clean_value(text) or ""
    if not cleaned:
        return {}
    pending_field = current_state.get("pending_question_field")
    pending_optional = bool(current_state.get("pending_question_optional"))
    if pending_field and pending_optional and _is_decline_answer(cleaned):
        return {"skipped_optional_fields": [pending_field]}

    try:
        llm_updates = llm_extract_request_updates(cleaned, current_state)
    except Exception:
        llm_updates = {}
    regex_updates = regex_extract_request_updates(cleaned, current_state)
    merged = dict(regex_updates)
    merged.update({k: v for k, v in llm_updates.items() if v is not None})
    merged.pop("answer_field", None)
    if pending_field and pending_field != "trip_type" and current_state.get("trip_type") and not merged.get("trip_type"):
        merged["trip_type"] = current_state.get("trip_type")
    return merged


def _required_fields_for_trip_type(trip_type: Optional[str], state: Dict[str, Any]) -> List[str]:
    if not trip_type:
        return ["trip_type"]
    if trip_type == "point_to_point":
        return ["start", "end"]
    if trip_type == "multiday":
        required = ["start", "days"]
        if not (state.get("roundtrip_base") and state.get("base_location")):
            required.append("end")
        return required
    if trip_type in {"day_trip", "base_explore"}:
        return ["start", "interest"]
    if trip_type == "local_search":
        return ["base_location", "interest"]
    return ["trip_type"]


def _optional_fields_for_trip_type(trip_type: Optional[str], state: Dict[str, Any]) -> List[str]:
    if not trip_type:
        return []
    if trip_type == "point_to_point":
        return ["date"]
    if trip_type == "multiday":
        return ["interest", "pace", "activities_per_day", "date", "transport_mode"]
    if trip_type in {"day_trip", "base_explore"}:
        return ["pace", "activities_per_day", "date", "transport_mode"]
    if trip_type == "local_search":
        return ["pace", "activities_per_day", "date", "transport_mode"]
    return []


def get_missing_request_fields(state: Dict[str, Any]) -> List[str]:
    required = []
    for field in _required_fields_for_trip_type(state.get("trip_type"), state):
        if not state.get(field):
            required.append(field)
    return required


def get_optional_request_fields(state: Dict[str, Any]) -> List[str]:
    skipped = set(state.get("skipped_optional_fields") or [])
    remaining = []
    for field in _optional_fields_for_trip_type(state.get("trip_type"), state):
        if field in skipped:
            continue
        if not state.get(field):
            remaining.append(field)
    return remaining


def build_clarification_question(state: Dict[str, Any], missing_fields: List[str]) -> Optional[Tuple[str, str, bool]]:
    if missing_fields:
        field = missing_fields[0]
        if field == "trip_type":
            return field, "Welche Art von Anfrage ist es: reine Verbindung, Tagesausflug, Aktivitäten vor Ort oder Mehrtagesreise?", False
        if field == "start":
            return field, "Von wo möchtest du starten?", False
        if field == "end":
            return field, "Wohin möchtest du fahren?", False
        if field == "days":
            return field, "Wie viele Tage soll die Reise dauern?", False
        if field == "date":
            return field, "Für welches Datum soll ich planen?", False
        if field == "interest":
            return field, "Welche Interessen oder Aktivitäten soll ich berücksichtigen?", False
        return field, f"Bitte ergänze noch: {REQUEST_FIELD_LABELS.get(field, field)}", False

    optional_fields = get_optional_request_fields(state)
    if optional_fields:
        field = optional_fields[0]
        if field == "date":
            return field, "Möchtest du ein konkretes Datum angeben? Du kannst auch mit 'nein' ablehnen.", True
        if field == "pace":
            return field, "Wie intensiv soll der Plan sein: EASY, MEDIUM oder HEAVY? Du kannst auch mit 'nein' ablehnen.", True
        if field == "activities_per_day":
            return field, "Wie viele Aktivitäten pro Tag möchtest du ungefähr? Du kannst auch mit 'nein' ablehnen.", True
        if field == "transport_mode":
            return field, "Mit welchem Verkehrsmittel möchtest du reisen: Auto, ÖPNV/Zug, Fahrrad oder zu Fuß? Du kannst auch mit 'nein' ablehnen.", True
        if field == "interest":
            return field, "Möchtest du bestimmte Interessen angeben? Du kannst auch mit 'nein' ablehnen.", True
        return field, f"Optional: {REQUEST_FIELD_LABELS.get(field, field)}. Mit 'nein' überspringen.", True
    return None


def request_state_to_response(state: Dict[str, Any], question: str) -> str:
    summary_keys = [
        "trip_type", "start", "end", "base_location", "origin", "travel_window", "transport_mode", "roundtrip_base", "days", "date", "interest", "pace", "activities_per_day", "missing_fields", "optional_fields_remaining", "selected_pois"
    ]
    return json.dumps(
        {
            "type": "clarification_question",
            "question": question,
            "request_state": {key: ([item.get("name") for item in state.get(key, []) if isinstance(item, dict) and item.get("name")] if key == "selected_pois" else state.get(key)) for key in summary_keys},
            "missing_fields": state.get("missing_fields") or [],
            "optional_fields_remaining": state.get("optional_fields_remaining") or [],
        },
        ensure_ascii=False,
    )


def _derive_num_stops(state: Dict[str, Any]) -> int:
    explicit = state.get("activities_per_day")
    if explicit is not None:
        try:
            return max(1, min(8, int(explicit)))
        except Exception:
            pass
    pace = state.get("pace") or "MEDIUM"
    return {"EASY": 2, "MEDIUM": 3, "HEAVY": 5}.get(pace, 3)


def _derive_multiday_preferences(state: Dict[str, Any]) -> Dict[str, str]:
    interest = state.get("interest") or "Highlights"
    pace = state.get("pace") or "MEDIUM"
    activities = _derive_num_stops(state)
    activity_pref = state.get("activity_pref") or interest
    food_pref = state.get("food_pref") or "Restaurant Gaststätte"
    culture_pref = state.get("culture_pref") or ("Museum Kultur" if "Kultur" in interest else "Museum")
    hotel_pref = state.get("hotel_pref") or ("Ruhiges Hotel" if pace == "EASY" else "Hotel Unterkunft Central")
    return {
        "activity_pref": activity_pref,
        "food_pref": food_pref,
        "culture_pref": culture_pref,
        "hotel_pref": hotel_pref,
        "pace": pace,
        "activities_per_day": str(activities),
    }


def execute_request_state(state: Dict[str, Any], payload: Dict[str, Any]) -> str:
    route_preferences = dict(state.get("route_preferences") or {}) | dict(payload.get("route_preferences") or {})
    selection = payload.get("selection")
    trip_type = state.get("trip_type") or "point_to_point"
    default_time = state.get("time_str") or (f"{state.get('date')} 09:00" if state.get("date") else "tomorrow 07:30")
    selected_pois = list(state.get("selected_pois") or payload.get("selected_pois") or [])
    if state.get("pace") == "EASY":
        route_preferences.setdefault("max_transfers", 1)
        route_preferences.setdefault("transfer_penalty", 900)
        route_preferences.setdefault("num_itineraries", 1)
    elif state.get("pace") == "HEAVY":
        route_preferences.setdefault("max_transfers", 3)
        route_preferences.setdefault("num_itineraries", 5)

    if trip_type == "point_to_point":
        return plan_journey_logic(
            start=state.get("start") or state.get("origin"),
            end=state.get("end"),
            time_str=default_time,
            route_preferences=route_preferences,
            selection=selection,
        )

    if trip_type == "local_search":
        return plan_activities_logic(
            location=state.get("base_location") or state.get("start") or state.get("end"),
            interest=state.get("interest") or "Highlights",
        )

    if trip_type == "multiday":
        prefs = _derive_multiday_preferences(state)
        base = state.get("base_location")
        return plan_multiday_trip_logic(
            start=state.get("start") or state.get("origin") or base,
            end=state.get("end") or base or state.get("start"),
            days=int(state.get("days") or 3),
            hotel_pref=prefs["hotel_pref"],
            activity_pref=prefs["activity_pref"],
            food_pref=prefs["food_pref"],
            culture_pref=prefs["culture_pref"],
            pace=prefs["pace"],
            activities_per_day=int(prefs["activities_per_day"]),
            route_preferences=route_preferences,
            selection=selection,
            time_str=default_time,
            selected_pois=selected_pois,
        )

    base = state.get("base_location")
    return plan_complete_trip_logic(
        start=state.get("start") or state.get("origin") or base,
        end=state.get("end") or base or state.get("start"),
        interest=state.get("interest") or "Highlights",
        num_stops=_derive_num_stops(state),
        pace=state.get("pace") or "MEDIUM",
        activities_per_day=state.get("activities_per_day"),
        route_preferences=route_preferences,
        selection=selection,
        time_str=default_time,
        selected_pois=selected_pois,
    )


def is_social_chat_message(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not normalized:
        return False
    return normalized in SOCIAL_CHAT_PHRASES


def message_answers_pending_field(text: str, pending_field: Optional[str], is_optional: bool = False) -> bool:
    cleaned = (text or "").strip()
    if not cleaned or not pending_field:
        return False

    lower = cleaned.lower()
    if is_social_chat_message(cleaned):
        return False
    if is_optional and lower in {"nein", "nee", "no", "skip", "überspringen", "ueberspringen", "egal"}:
        return True

    if pending_field == "trip_type":
        for trip_type, patterns in TRIP_TYPE_HINT_PATTERNS.items():
            if any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns):
                return True
        return False
    if pending_field in {"pace"}:
        return any(token in lower for token in ["easy", "medium", "heavy", "leicht", "entspannt", "mittel", "normal", "intensiv"])
    if pending_field in {"activities_per_day", "days"}:
        return bool(re.search(r"\d+", lower))
    if pending_field == "date":
        return any(token in lower for token in ["heute", "morgen", "übermorgen", "uebermorgen", "today", "tomorrow", "montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]) or bool(re.search(r"\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?", lower))
    if pending_field == "interest":
        return len(cleaned.split()) >= 1 and not is_social_chat_message(cleaned)
    if pending_field in {"start", "end", "base_location"}:
        return len(cleaned.split()) <= 8 and not is_social_chat_message(cleaned)
    return True


def classify_message_mode(text: str, state: Dict[str, Any], payload: Dict[str, Any]) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        return "chat"
    if is_social_chat_message(cleaned):
        return "chat"
    pending_field = state.get("pending_question_field")
    if pending_field and message_answers_pending_field(cleaned, pending_field, bool(state.get("pending_question_optional"))):
        return "request"
    if payload.get("selected_pois"):
        return "request"
    if looks_like_request_engine_message(cleaned, state, payload):
        return "request"
    if should_force_guided_request_flow(cleaned, state, payload):
        return "request"
    return "chat"


def build_normal_chat_messages(session_state: Dict[str, Any], user_text: str) -> List[Dict[str, str]]:
    system_prompt = (
        "Du bist KIRA, ein freundlicher KI-Assistent für Reiseplanung. "
        "Wenn der Nutzer Smalltalk macht, sich bedankt oder allgemeine Fragen stellt, antworte natürlich, kurz und hilfreich. "
        "Starte dabei keinen Request-Flow, erfinde keine Reisen und gib kein JSON aus. "
        "Wenn bereits ein Reiseplan existiert, darfst du darauf allgemein Bezug nehmen, aber führe ohne ausdrückliche Request-Angabe keine Planung aus."
    )
    messages = [{"role": "system", "content": system_prompt}]
    current_trip = session_state.get("current_trip")
    if current_trip:
        messages.append({
            "role": "system",
            "content": "Aktueller Kontext (nur falls hilfreich für eine natürliche Antwort):\n" + json.dumps(current_trip, ensure_ascii=False)[:4000],
        })
    messages.append({"role": "user", "content": user_text})
    return messages


def generate_normal_chat_response(session_state: Dict[str, Any], user_text: str) -> str:
    response = client.chat.completions.create(
        model=DEPLOYMENT_NAME,
        messages=build_normal_chat_messages(session_state, user_text),
    )
    content = (response.choices[0].message.content or "").strip()
    if content:
        return content
    lowered = (user_text or "").strip().lower()
    if any(token in lowered for token in ["danke", "thanks", "thx"]):
        return "Gerne!"
    if any(token in lowered for token in ["hey", "hi", "hallo", "guten tag", "moin", "servus"]):
        return "Hallo! Wie kann ich dir helfen?"
    return "Gerne helfe ich dir weiter."


def looks_like_request_engine_message(text: str, state: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    lower = (text or "").lower()
    if payload.get("selected_pois"):
        return True
    if state.get("pending_question_field") and message_answers_pending_field(text, state.get("pending_question_field"), bool(state.get("pending_question_optional"))):
        return True
    if any(word in lower for word in ["easy", "medium", "heavy", "leicht", "mittel", "intensiv", "activities per day", "aktivitäten pro tag", "stopps pro tag"]):
        return bool(state.get("fulfilled") or state.get("trip_type") or payload.get("current_trip"))
    keywords = [
        "plan", "trip", "route", "travel", "reise", "ausflug", "verbindung", "things to do", "activities", "aktivitäten", "aktivitaeten", "around", "rund um", "from", "to", "von", "nach", " in ",
    ]
    return any(keyword in f" {lower} " for keyword in keywords)




def should_force_guided_request_flow(text: str, state: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    if payload.get("current_trip") or payload.get("selection") or payload.get("edit_operation") or payload.get("drag_override"):
        return False
    if payload.get("selected_pois"):
        return False
    if state.get("pending_question_field"):
        return False
    if state.get("fulfilled"):
        return False

    word_count = len(re.findall(r"\S+", cleaned))
    lower = cleaned.lower()
    explicit_request_markers = [
        "plan", "reise", "trip", "route", "verbindung", "von", "nach", "around", "rund um",
        "activities", "aktivitäten", "things to do", "multiday", "mehrtag", "road trip",
    ]
    if any(marker in lower for marker in explicit_request_markers):
        return False

    # Very short or location-like inputs should never trigger tool execution directly.
    if word_count <= 5:
        return True
    if not re.search(r"[?.!,]", cleaned) and word_count <= 8:
        return True
    return False

def should_reset_request_state(text: str, state: Dict[str, Any]) -> bool:
    lower = (text or "").lower()
    if not state.get("fulfilled"):
        return False
    if any(word in lower for word in ["new trip", "neue reise", "anderer trip", "plan a trip", "plane eine reise", "route from", "reise von", "ausflug von"]):
        return True
    if re.search(r"from.*to|von.*nach|around|rund\s+um", lower):
        return True
    return False


# ----------------------
# Deterministic edit pass
# ----------------------

def parse_distance(text: str, keyword_group: str) -> Optional[float]:
    pattern = rf"(?:max(?:imal)?|höchstens|unter|weniger als|bis zu)?\s*(\d+(?:[\.,]\d+)?)\s*(km|m)\s*(?:{keyword_group})"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        alt = re.search(rf"(?:{keyword_group}).{{0,25}}?(\d+(?:[\.,]\d+)?)\s*(km|m)", text, re.IGNORECASE)
        match = alt
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    return value * 1000 if unit == "km" else value


def _route_mode_patterns() -> Dict[str, List[str]]:
    return {
        "TRANSIT": [
            r"öffis",
            r"oeffis",
            r"öffentliche(?:n|r)?\s+verkehrsmittel(?:n)?",
            r"oeffentliche(?:n|r)?\s+verkehrsmittel(?:n)?",
            r"öpnv",
            r"oepnv",
            r"nahverkehr",
            r"bus(?:\s+und\s+bahn)?",
            r"bahn",
            r"zug",
            r"transit",
            r"öffi",
            r"oeffi",
        ],
        "CAR": [
            r"auto",
            r"pkw",
            r"wagen",
            r"car",
            r"mietwagen",
        ],
        "BICYCLE": [
            r"fahrrad",
            r"rad(?:l)?",
            r"bike",
            r"bicycle",
        ],
        "WALK": [
            r"zu\s+fuß",
            r"zu\s+fuss",
            r"fußweg",
            r"fussweg",
            r"zu\s+gehen",
            r"laufen",
            r"gehen",
            r"walk",
            r"walking",
        ],
    }


MODE_PATTERNS = _route_mode_patterns()


def _match_mode_in_fragment(fragment: str) -> Optional[str]:
    fragment = fragment or ""
    for mode, patterns in MODE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, fragment, re.IGNORECASE):
                return mode
    return None


def _extract_forbidden_modes(lower: str) -> List[str]:
    negation_templates = [
        r"nicht\s+(?:mit\s+dem\s+|mit\s+der\s+|mit\s+)?(?P<fragment>.{0,40}?)(?:\s+(?:sondern|aber|,|\.|$))",
        r"ohne\s+(?:den\s+|dem\s+|die\s+|das\s+)?(?P<fragment>.{0,40}?)(?:\s+(?:sondern|aber|,|\.|$))",
        r"kein(?:e|en|em|er)?\s+(?P<fragment>.{0,40}?)(?:\s+(?:sondern|aber|,|\.|$))",
        r"(?:vermeide|vermeiden|avoid)\s+(?P<fragment>.{0,40}?)(?:\s+(?:sondern|aber|,|\.|$))",
        r"(?:statt|anstatt|instead\s+of)\s+(?P<fragment>.{0,40}?)(?:\s+(?:mit|per|via|zu\s+fuß|zu\s+fuss|walk|laufen|gehen)|$)",
    ]

    forbidden: List[Tuple[int, str]] = []
    for pattern in negation_templates:
        for match in re.finditer(pattern, lower, re.IGNORECASE):
            fragment = (match.groupdict().get("fragment") or "").strip()
            mode = _match_mode_in_fragment(fragment)
            if mode:
                forbidden.append((match.start(), mode))

    forbidden.sort()
    deduped: List[str] = []
    seen = set()
    for _, mode in forbidden:
        if mode not in seen:
            deduped.append(mode)
            seen.add(mode)
    return deduped


def _extract_target_mode(lower: str, forbidden_modes: Optional[List[str]] = None) -> Optional[str]:
    forbidden = set(forbidden_modes or [])

    explicit_target_patterns = [
        r"sondern\s+(?:mit\s+|per\s+|via\s+)?(?P<target>.{0,60})$",
        r"(?:aber|lieber)\s+(?:mit\s+|per\s+|via\s+)?(?P<target>.{0,60})$",
        r"(?:statt|anstatt|instead\s+of)\s+.{0,60}?(?:mit\s+|per\s+|via\s+)?(?P<target>.{0,60})$",
        r"(?:mit|per|via)\s+(?P<target>.{0,60}?)(?:statt|anstatt|instead\s+of)",
        r"(?:nutze|verwende|benutze|route|plane|berechne|fahre).{0,30}(?:mit|per|via)\s+(?P<target>.{0,60})$",
    ]

    for pattern in explicit_target_patterns:
        match = re.search(pattern, lower, re.IGNORECASE)
        if not match:
            continue
        mode = _match_mode_in_fragment(match.group('target'))
        if mode and mode not in forbidden:
            return mode

    mentions: List[Tuple[int, str]] = []
    for mode, patterns in MODE_PATTERNS.items():
        if mode in forbidden:
            continue
        for pattern in patterns:
            found = re.search(pattern, lower, re.IGNORECASE)
            if found:
                mentions.append((found.start(), mode))
                break
    if not mentions:
        return None
    mentions.sort()
    return mentions[0][1]

def extract_route_preferences_from_text(text: str, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lower = (text or "").lower()
    prefs: Dict[str, Any] = dict(base or {})

    forbidden_modes = _extract_forbidden_modes(lower)
    if forbidden_modes:
        prefs["forbidden_modes"] = forbidden_modes

    target_mode = _extract_target_mode(lower, forbidden_modes)
    if target_mode == "CAR":
        prefs["primary_mode"] = "CAR"
        prefs["allowed_modes"] = ["CAR"]
    elif target_mode == "BICYCLE":
        prefs["primary_mode"] = "BICYCLE"
        prefs["allowed_modes"] = ["BICYCLE", "WALK"]
    elif target_mode == "WALK":
        prefs["primary_mode"] = "WALK"
        prefs["allowed_modes"] = ["WALK"]
    elif target_mode == "TRANSIT":
        prefs["primary_mode"] = "TRANSIT"
        prefs["allowed_modes"] = ["WALK", "TRANSIT"]
    elif forbidden_modes:
        current_allowed = [str(m).upper() for m in (prefs.get("allowed_modes") or []) if m]
        if current_allowed:
            prefs["allowed_modes"] = [m for m in current_allowed if m not in set(forbidden_modes)]

    if any(word in lower for word in ["weniger umst", "wenig umst", "möglichst wenig umst", "avoid transfer", "direkt", "ohne umstieg", "ohne umsteigen"]):
        prefs["avoid_transfers"] = True
        prefs.setdefault("transfer_penalty", 900)
        prefs.setdefault("min_transfer_time", 180)
        prefs.setdefault("max_transfers", 1)
        prefs.setdefault("num_itineraries", 1)

    if any(word in lower for word in ["rollstuhl", "wheelchair", "barrierefrei"]):
        prefs["wheelchair_accessible"] = True

    if any(word in lower for word in ["ankommen bis", "arrive by", "spätestens", "spaetestens"]):
        prefs["arrive_by"] = True

    max_walk = parse_distance(lower, r"(?:laufen|fuß|fuss|gehen|walk)")
    if max_walk is not None:
        prefs["max_walk_distance"] = max_walk

    walk_reluctance_match = re.search(r"(?:möglichst wenig laufen|kaum laufen|wenig laufen)", lower)
    if walk_reluctance_match:
        prefs.setdefault("walk_reluctance", 12)

    wait_reluctance_match = re.search(r"(?:wenig warten|kaum warten|nicht lange warten)", lower)
    if wait_reluctance_match:
        prefs.setdefault("wait_reluctance", 2.5)

    if "mehr optionen" in lower or "mehrere optionen" in lower:
        prefs["num_itineraries"] = 5

    return prefs


def infer_edit_operation(payload: Dict[str, Any], route_preferences: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    selection = payload.get("selection") or {}
    current_trip = payload.get("current_trip")
    drag_override = payload.get("drag_override")
    text = (payload.get("text") or "").lower()

    if not current_trip or not selection:
        return None

    selection_type = selection.get("selection_type")

    if selection_type == "leg":
        return {"operation": "regenerate_leg", "scope": "leg", "route_preferences": route_preferences}
    if selection_type == "activity":
        if drag_override:
            return {"operation": "move_activity", "scope": "activity", "route_preferences": route_preferences}
        if any(word in text for word in ["lösch", "loesch", "delete", "entfern", "remove"]):
            return {"operation": "delete_activity", "scope": "activity", "route_preferences": route_preferences}
        if any(word in text for word in ["ersetz", "replace", "ander", "andere"]):
            return {"operation": "replace_activity", "scope": "activity", "route_preferences": route_preferences}
        return {"operation": "apply_route_preferences", "scope": "activity", "route_preferences": route_preferences}
    if selection_type == "trip":
        return {"operation": "regenerate_trip", "scope": "trip", "route_preferences": route_preferences}
    if selection_type == "step":
        return {"operation": "regenerate_step", "scope": "step", "route_preferences": route_preferences}
    if selection_type == "day":
        return {"operation": "reroute_day", "scope": "day", "route_preferences": route_preferences}
    return None


def normalize_explicit_edit_operation(payload: Dict[str, Any], route_preferences: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    edit_operation = payload.get("edit_operation") or {}
    if not isinstance(edit_operation, dict) or not edit_operation.get("operation"):
        return None
    normalized = {
        "operation": edit_operation.get("operation"),
        "scope": edit_operation.get("scope") or (payload.get("selection") or {}).get("selection_type"),
        "route_preferences": route_preferences,
    }
    return normalized


def update_session_from_result(session_state: Dict[str, Any], result_str: str, selection: Optional[Dict[str, Any]] = None) -> None:
    parsed = parse_json_result(result_str)
    if isinstance(parsed, dict):
        if parsed.get("legs") or parsed.get("type") in {"multi_step_plan", "activity_list"}:
            session_state["current_trip"] = parsed
        if parsed.get("type") == "error" or parsed.get("error"):
            session_state["last_error"] = parsed.get("message") or parsed.get("error")
        else:
            session_state["last_error"] = None
    if selection is not None:
        session_state["selection"] = selection


def build_contextual_user_prompt(payload: Dict[str, Any]) -> str:
    user_text = str(payload.get("text", "")).strip()
    selection = payload.get("selection")
    current_trip = payload.get("current_trip")
    drag_override = payload.get("drag_override")
    edit_operation = payload.get("edit_operation")
    selected_pois = payload.get("selected_pois") or []

    chunks = [f"USER_REQUEST:\n{user_text}"]

    if selection:
        chunks.append("AKTUELLE AUSWAHL IM UI:\n" + json.dumps(selection, ensure_ascii=False, indent=2))
    if drag_override:
        chunks.append(
            "KARTEN-VERSCHIEBUNG (benutze diese Koordinaten für die Neuberechnung des ausgewählten Elements):\n"
            + json.dumps(drag_override, ensure_ascii=False, indent=2)
        )
    if edit_operation:
        chunks.append("STRUKTURIERTE EDIT-OPERATION:\n" + json.dumps(edit_operation, ensure_ascii=False, indent=2))
    if selected_pois:
        chunks.append("EXPLIZIT AUSGEWÄHLTE POIS (priorisiere sie in der Planung):\n" + json.dumps(selected_pois, ensure_ascii=False, indent=2))
    if current_trip:
        chunks.append(
            "AKTUELLER REISEPLAN-KONTEXT (nutze ihn für Änderungen statt komplett neu zu raten):\n"
            + json.dumps(current_trip, ensure_ascii=False)
        )

    chunks.append(
        "ANWEISUNG:\n"
        "- Übertrage alle sinnvollen Transport- und Routingwünsche in route_preferences.\n"
        "- Beispiele: Auto => primary_mode=CAR und allowed_modes=[CAR].\n"
        "- Weniger Umstiege => avoid_transfers=true und transfer_penalty erhöhen.\n"
        "- Zu Fuß/Fahrrad entsprechend in allowed_modes.\n"
        "- Bei bestehenden Änderungen selection/edit_operation respektieren.\n"
        "- Nach einem Planungs-Tool keinen freien Text erzeugen."
    )

    return "\n\n".join(chunks)


def parse_json_result(value: str) -> Dict[str, Any]:
    try:
        return json.loads(value)
    except Exception:
        return {"type": "error", "message": value}


def trip_start_time_string(trip_obj: Dict[str, Any], fallback: str = "tomorrow 07:30") -> str:
    first_leg = (trip_obj or {}).get("legs", [{}])[0]
    start_time = first_leg.get("start_time")
    if start_time:
        return f"tomorrow {start_time}"
    return fallback


def recalc_trip_total_duration(trip_obj: Dict[str, Any]) -> None:
    trip_obj["total_duration"] = int(sum(int(leg.get("duration", 0)) for leg in trip_obj.get("legs", [])))


def apply_query_preferences(trip_obj: Dict[str, Any], route_preferences: Dict[str, Any]) -> None:
    merged = dict(trip_obj.get("query_preferences") or {})
    merged.update(route_preferences or {})
    trip_obj["query_preferences"] = merged


def apply_trip_endpoint_labels(
    trip_obj: Dict[str, Any],
    *,
    start_name: Optional[str] = None,
    end_name: Optional[str] = None,
) -> None:
    if not isinstance(trip_obj, dict):
        return
    legs = list(trip_obj.get("legs") or [])
    if start_name:
        trip_obj["start"] = start_name
        if legs:
            legs[0]["from"] = start_name
    if end_name:
        trip_obj["end"] = end_name
        if legs:
            legs[-1]["to"] = end_name


def _valid_coords(coords: Any) -> bool:
    return (
        isinstance(coords, (list, tuple))
        and len(coords) >= 2
        and coords[0] is not None
        and coords[1] is not None
    )


def _trip_terminal_coords(trip_obj: Dict[str, Any]) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
    legs = trip_obj.get("legs", []) or []
    start_coords = None
    end_coords = None
    if legs:
        first_leg = legs[0] or {}
        last_leg = legs[-1] or {}
        if _valid_coords(first_leg.get("from_coords")):
            start_coords = tuple(first_leg.get("from_coords")[:2])
        if _valid_coords(last_leg.get("to_coords")):
            end_coords = tuple(last_leg.get("to_coords")[:2])
    return start_coords, end_coords


def reroute_trip_object(
    trip_obj: Dict[str, Any],
    route_preferences: Dict[str, Any],
    *,
    start_override: Optional[Tuple[float, float]] = None,
    end_override: Optional[Tuple[float, float]] = None,
    selection: Optional[Dict[str, Any]] = None,
    time_override: Optional[str] = None,
) -> Dict[str, Any]:
    start_name = trip_obj.get("start") or trip_obj.get("legs", [{}])[0].get("from")
    end_name = trip_obj.get("end") or trip_obj.get("legs", [{}])[-1].get("to")
    fallback_start_coords, fallback_end_coords = _trip_terminal_coords(trip_obj)
    result = parse_json_result(
        plan_journey_logic(
            start=start_name,
            end=end_name,
            time_str=time_override or trip_start_time_string(trip_obj),
            start_coords_override=start_override or fallback_start_coords,
            end_coords_override=end_override or fallback_end_coords,
            route_preferences=route_preferences,
            selection=selection,
        )
    )
    if isinstance(result, dict) and result.get("legs"):
        apply_trip_endpoint_labels(result, start_name=start_name, end_name=end_name)
    return result


def find_selected_trip_ref(current_trip: Dict[str, Any], selection: Dict[str, Any]):
    selection_type = selection.get("selection_type")
    if current_trip.get("legs"):
        if selection_type in {"trip", "leg"}:
            return current_trip, None, None
        return None, None, None

    if current_trip.get("type") != "multi_step_plan":
        return None, None, None

    if selection_type == "step":
        idx = selection.get("step_index")
        if isinstance(idx, int) and 0 <= idx < len(current_trip.get("steps", [])):
            step = current_trip["steps"][idx]
            if step.get("type") == "trip":
                return step.get("data"), idx, step
    if selection_type == "leg":
        idx = selection.get("step_index")
        if isinstance(idx, int) and 0 <= idx < len(current_trip.get("steps", [])):
            step = current_trip["steps"][idx]
            if step.get("type") == "trip":
                return step.get("data"), idx, step
    if selection_type == "trip":
        idx = selection.get("step_index")
        if isinstance(idx, int) and 0 <= idx < len(current_trip.get("steps", [])):
            step = current_trip["steps"][idx]
            if step.get("type") == "trip":
                return step.get("data"), idx, step
    return None, None, None


def get_day_step_indices(current_trip: Dict[str, Any], day_index: int):
    if current_trip.get("type") != "multi_step_plan":
        return []

    steps = current_trip.get("steps", []) or []
    has_headers = any((step or {}).get("type") == "header" for step in steps)

    # Single-day plans currently use multi_step_plan without day headers.
    # In that case the full plan is effectively Tag 1.
    if not has_headers:
        return list(range(len(steps))) if int(day_index or 1) == 1 else []

    current_day = 0
    collected = []
    for idx, step in enumerate(steps):
        if step.get("type") == "header":
            current_day += 1
            continue
        if current_day == day_index:
            collected.append(idx)
    return collected


def extract_trip_start_time(trip_obj: Dict[str, Any], fallback: str = "07:30") -> str:
    first_leg = (trip_obj or {}).get("legs", [{}])[0]
    return first_leg.get("start_time") or fallback


def extract_trip_end_time(trip_obj: Dict[str, Any]) -> Optional[str]:
    legs = (trip_obj or {}).get("legs", [])
    if not legs:
        return None
    return legs[-1].get("end_time")


def estimate_activity_duration_minutes(activity: Dict[str, Any]) -> int:
    if not isinstance(activity, dict):
        return 90
    explicit = activity.get("duration") or activity.get("duration_minutes")
    try:
        if explicit is not None:
            return max(5, int(explicit))
    except Exception:
        pass
    if activity.get("geometry"):
        return 120
    category = str(activity.get("category") or "").lower()
    if any(word in category for word in ["hotel", "unterkunft"]):
        return 30
    if any(word in category for word in ["restaurant", "gasthof", "essen"]):
        return 90
    return 90


def shift_clock_time(clock_time: Optional[str], delta_minutes: int) -> Optional[str]:
    if not clock_time:
        return None
    try:
        hours, minutes = map(int, str(clock_time).split(":"))
        total = hours * 60 + minutes + int(delta_minutes)
        total %= 24 * 60
        return f"{total // 60:02d}:{total % 60:02d}"
    except Exception:
        return None


def build_tomorrow_time_str(clock_time: Optional[str], fallback: str = "07:30") -> str:
    return f"tomorrow {clock_time or fallback}"


def replace_leg_in_trip(
    trip_obj: Dict[str, Any],
    leg_index: int,
    route_preferences: Dict[str, Any],
    drag_override: Optional[Dict[str, Any]] = None,
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if leg_index is None or leg_index < 0 or leg_index >= len(trip_obj.get("legs", [])):
        return {"type": "error", "message": "Ausgewählter Leg nicht gefunden."}

    leg = trip_obj["legs"][leg_index]
    start_override = None
    end_override = None
    if drag_override and drag_override.get("type") == "leg-start":
        start_override = tuple(drag_override.get("coords"))
    if drag_override and drag_override.get("type") == "leg-end":
        end_override = tuple(drag_override.get("coords"))

    rerouted = parse_json_result(
        plan_journey_logic(
            start=leg.get("from") or selection.get("from_name") or trip_obj.get("start"),
            end=leg.get("to") or selection.get("to_name") or trip_obj.get("end"),
            time_str=f"tomorrow {leg.get('start_time', '07:30')}",
            start_coords_override=start_override or (tuple(leg.get("from_coords")[:2]) if _valid_coords(leg.get("from_coords")) else None),
            end_coords_override=end_override or (tuple(leg.get("to_coords")[:2]) if _valid_coords(leg.get("to_coords")) else None),
            route_preferences=route_preferences,
            selection=selection,
        )
    )
    if "legs" not in rerouted:
        return rerouted

    updated_trip = copy.deepcopy(trip_obj)
    updated_trip["legs"] = (
        updated_trip.get("legs", [])[:leg_index]
        + rerouted.get("legs", [])
        + updated_trip.get("legs", [])[leg_index + 1 :]
    )
    recalc_trip_total_duration(updated_trip)
    apply_query_preferences(updated_trip, route_preferences)
    return updated_trip


def _resolve_activity_coords(activity: Dict[str, Any], selection: Optional[Dict[str, Any]] = None) -> Optional[Tuple[float, float]]:
    if activity.get("lat") is not None and activity.get("lon") is not None:
        return (activity.get("lat"), activity.get("lon"))
    if selection and _valid_coords(selection.get("coords")):
        return tuple(selection.get("coords")[:2])
    if selection and _valid_coords(selection.get("replacement_coords")):
        return tuple(selection.get("replacement_coords")[:2])
    return None


def update_adjacent_trips_for_activity(
    plan_data: Dict[str, Any],
    step_index: int,
    activity_step: Dict[str, Any],
    route_preferences: Dict[str, Any],
    drag_override: Optional[Dict[str, Any]] = None,
    selection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    updated = copy.deepcopy(plan_data)
    steps = updated.get("steps", [])
    if step_index < 0 or step_index >= len(steps):
        return {"type": "error", "message": "Ausgewählte Aktivität nicht gefunden."}

    activity = copy.deepcopy((activity_step or {}).get("data") or steps[step_index].get("data", {}))
    if drag_override and drag_override.get("coords"):
        activity["lat"], activity["lon"] = drag_override["coords"]
        activity["moved_by_user"] = True

    resolved_coords = _resolve_activity_coords(activity, selection)
    if resolved_coords is None:
        return {"type": "error", "message": "Für die Aktivität fehlen Koordinaten für das Rerouting."}
    activity["lat"], activity["lon"] = resolved_coords

    prev_trip_idx = next((i for i in range(step_index - 1, -1, -1) if steps[i].get("type") == "trip"), None)
    next_trip_idx = next((i for i in range(step_index + 1, len(steps)) if steps[i].get("type") == "trip"), None)

    rerouted_prev = None
    rerouted_next = None

    if prev_trip_idx is not None:
        prev_trip = steps[prev_trip_idx].get("data", {})
        rerouted_prev = reroute_trip_object(
            prev_trip,
            route_preferences,
            end_override=(activity["lat"], activity["lon"]),
            selection=selection,
        )
        if "legs" in rerouted_prev:
            apply_trip_endpoint_labels(rerouted_prev, end_name=activity.get("name"))
            steps[prev_trip_idx]["data"] = rerouted_prev

    if next_trip_idx is not None:
        next_trip = steps[next_trip_idx].get("data", {})
        next_time_override = None
        if isinstance(rerouted_prev, dict) and rerouted_prev.get("legs"):
            arrival_time = extract_trip_end_time(rerouted_prev)
            next_departure = shift_clock_time(arrival_time, estimate_activity_duration_minutes(activity))
            next_time_override = build_tomorrow_time_str(next_departure, extract_trip_start_time(next_trip))
        rerouted_next = reroute_trip_object(
            next_trip,
            route_preferences,
            start_override=(activity["lat"], activity["lon"]),
            selection=selection,
            time_override=next_time_override,
        )
        if "legs" in rerouted_next:
            apply_trip_endpoint_labels(rerouted_next, start_name=activity.get("name"))
            steps[next_trip_idx]["data"] = rerouted_next

    refreshed_selection = dict(selection or {})
    if refreshed_selection.get("selection_type") == "activity":
        refreshed_selection["name"] = activity.get("name")
        refreshed_selection["label"] = activity.get("name")
        refreshed_selection["coords"] = [activity.get("lat"), activity.get("lon")]
        refreshed_selection["step_index"] = step_index

    steps[step_index]["data"] = activity
    updated["selection"] = refreshed_selection or selection
    updated["query_preferences"] = dict(updated.get("query_preferences") or {}) | route_preferences

    day_index = _resolve_selected_day_index(updated, selection)
    rebuild_from_idx = next_trip_idx if isinstance(next_trip_idx, int) else step_index + 1
    updated = _rebuild_day_schedule_from_index(
        updated,
        day_index,
        rebuild_from_idx,
        route_preferences,
        selection=updated.get("selection") or selection,
    )
    return updated


def replace_activity_in_plan(
    plan_data: Dict[str, Any],
    step_index: int,
    selection: Dict[str, Any],
    route_preferences: Dict[str, Any],
    user_text: str,
) -> Dict[str, Any]:
    updated = copy.deepcopy(plan_data)
    steps = updated.get("steps", [])
    if step_index < 0 or step_index >= len(steps) or steps[step_index].get("type") != "activity":
        return {"type": "error", "message": "Ausgewählte Aktivität nicht gefunden."}

    current_activity = steps[step_index].get("data", {})
    location_hint = current_activity.get("city") or current_activity.get("location") or current_activity.get("name")
    search_interest = user_text.strip() or current_activity.get("category") or "Highlights"
    try:
        candidates = parse_json_result(plan_activities_logic(location_hint, search_interest))
    except Exception as exc:
        return {"type": "error", "message": f"Ersatzaktivität konnte nicht gesucht werden: {exc}"}

    items = candidates.get("items") or []
    replacement = None
    for item in items:
        if item.get("name") and item.get("name") != current_activity.get("name"):
            replacement = item
            break
    if not replacement:
        return {"type": "error", "message": "Keine passende Ersatzaktivität gefunden."}

    if replacement.get("lat") is None or replacement.get("lon") is None:
        return {"type": "error", "message": "Die Ersatzaktivität hat keine Koordinaten."}

    steps[step_index]["data"] = replacement
    replacement_selection = dict(selection or {})
    replacement_selection.update({
        "selection_type": "activity",
        "name": replacement.get("name"),
        "label": replacement.get("name"),
        "coords": [replacement.get("lat"), replacement.get("lon")],
        "step_index": step_index,
    })
    return update_adjacent_trips_for_activity(
        updated,
        step_index,
        steps[step_index],
        route_preferences,
        {"coords": [replacement["lat"], replacement["lon"]]},
        replacement_selection,
    )


def delete_activity_from_plan(
    plan_data: Dict[str, Any],
    step_index: int,
    selection: Dict[str, Any],
    route_preferences: Dict[str, Any],
) -> Dict[str, Any]:
    updated = copy.deepcopy(plan_data)
    steps = updated.get("steps", []) or []
    if step_index < 0 or step_index >= len(steps) or steps[step_index].get("type") != "activity":
        return {"type": "error", "message": "Ausgewählte Aktivität nicht gefunden."}

    day_index = selection.get("day_index")
    if not isinstance(day_index, int):
        day_index = 1

    day_indices = get_day_step_indices(updated, day_index)
    if not day_indices:
        return {"type": "error", "message": "Tag der ausgewählten Aktivität konnte nicht bestimmt werden."}

    activity = steps[step_index].get("data", {}) or {}
    activity_name, activity_coords, activity_duration = _get_activity_identity(activity)

    prev_activity_idx = next((i for i in range(step_index - 1, -1, -1) if i in day_indices and steps[i].get("type") == "activity"), None)
    prev_trip_idx = next((i for i in range(step_index - 1, -1, -1) if i in day_indices and steps[i].get("type") == "trip"), None)
    next_activity_idx = next((i for i in day_indices if i > step_index and steps[i].get("type") == "activity"), None)
    next_trip_idx = next((i for i in day_indices if i > step_index and steps[i].get("type") == "trip"), None)

    source_name = None
    source_coords = None
    departure_time = None

    if prev_activity_idx is not None:
        prev_activity = steps[prev_activity_idx].get("data", {}) or {}
        source_name, source_coords, prev_duration = _get_activity_identity(prev_activity)
        incoming_trip_idx = next((i for i in day_indices if prev_activity_idx < i < step_index and steps[i].get("type") == "trip"), None)
        if incoming_trip_idx is not None:
            departure_time = extract_trip_end_time(steps[incoming_trip_idx].get("data", {}))
        departure_time = shift_clock_time(departure_time, prev_duration) or departure_time
    elif prev_trip_idx is not None:
        prev_trip = steps[prev_trip_idx].get("data", {}) or {}
        source_name, _old_end_name, source_coords, _old_end_coords = _extract_trip_endpoints(prev_trip)
        departure_time = extract_trip_start_time(prev_trip, "07:30")
    else:
        source_name = activity_name
        source_coords = activity_coords
        departure_time = extract_trip_start_time(steps[next_trip_idx].get("data", {}), "07:30") if next_trip_idx is not None else "07:30"

    target_name = None
    target_coords = None

    if next_activity_idx is not None:
        next_activity = steps[next_activity_idx].get("data", {}) or {}
        target_name, target_coords, _dur = _get_activity_identity(next_activity)
    elif next_trip_idx is not None:
        next_trip = steps[next_trip_idx].get("data", {}) or {}
        _old_start_name, target_name, _old_start_coords, target_coords = _extract_trip_endpoints(next_trip)

    updated_steps = copy.deepcopy(steps)

    if prev_trip_idx is not None and next_trip_idx is not None and (target_name or target_coords) and (source_name or source_coords):
        combined_trip = _reroute_between_points(
            start_name=source_name,
            end_name=target_name,
            start_coords=source_coords,
            end_coords=target_coords,
            time_str=build_tomorrow_time_str(departure_time, departure_time or "07:30"),
            route_preferences=route_preferences,
            selection=selection,
        )
        if "legs" not in combined_trip:
            return combined_trip

        del updated_steps[next_trip_idx]
        del updated_steps[step_index]
        updated_steps[prev_trip_idx] = {"type": "trip", "data": combined_trip}
        rebuild_anchor = prev_trip_idx + 1
    elif prev_trip_idx is not None:
        del updated_steps[step_index]
        del updated_steps[prev_trip_idx]
        rebuild_anchor = prev_trip_idx
    elif next_trip_idx is not None and (target_name or target_coords) and (source_name or source_coords):
        rerouted_next = _reroute_between_points(
            start_name=source_name,
            end_name=target_name,
            start_coords=source_coords,
            end_coords=target_coords,
            time_str=build_tomorrow_time_str(departure_time, departure_time or "07:30"),
            route_preferences=route_preferences,
            selection=selection,
        )
        if "legs" not in rerouted_next:
            return rerouted_next

        del updated_steps[step_index]
        updated_steps[next_trip_idx - 1] = {"type": "trip", "data": rerouted_next}
        rebuild_anchor = next_trip_idx
    else:
        del updated_steps[step_index]
        rebuild_anchor = step_index

    refreshed_day_indices = get_day_step_indices({**updated, "steps": updated_steps}, day_index)
    updated_steps = _rebuild_remaining_day_trips(
        updated_steps,
        refreshed_day_indices,
        rebuild_anchor,
        route_preferences,
        selection=selection,
    )

    updated["steps"] = updated_steps
    updated["query_preferences"] = dict(updated.get("query_preferences") or {}) | route_preferences
    updated["selection"] = {
        "selection_type": "day",
        "day_index": day_index,
        "label": f"Tag {day_index}",
    }
    return updated


def apply_deterministic_edit(payload: Dict[str, Any]) -> Optional[str]:
    current_trip = payload.get("current_trip")
    selection = payload.get("selection") or {}
    drag_override = payload.get("drag_override")
    if not current_trip or not selection:
        return None

    existing_prefs = dict(current_trip.get("query_preferences") or {})
    route_preferences = extract_route_preferences_from_text(payload.get("text", ""), existing_prefs)
    operation = normalize_explicit_edit_operation(payload, route_preferences) or infer_edit_operation(payload, route_preferences)
    if not operation:
        return None

    print(f"🛠️ Structured edit: {operation['operation']}")
    updated = copy.deepcopy(current_trip)
    selection_type = selection.get("selection_type")

    if operation["operation"] == "regenerate_leg":
        trip_obj, step_idx, _ = find_selected_trip_ref(updated, selection)
        if not trip_obj:
            return json.dumps({"type": "error", "message": "Kein passender Trip für den ausgewählten Leg gefunden."})
        new_trip = replace_leg_in_trip(trip_obj, selection.get("leg_index"), route_preferences, drag_override, selection)
        if step_idx is None:
            updated = new_trip
        else:
            updated["steps"][step_idx]["data"] = new_trip
        return json.dumps(updated, ensure_ascii=False)

    if operation["operation"] in {"regenerate_trip", "regenerate_step"}:
        trip_obj, step_idx, _ = find_selected_trip_ref(updated, selection)
        if not trip_obj:
            return None
        start_override = tuple(drag_override["coords"]) if drag_override and drag_override.get("type") == "leg-start" else None
        end_override = tuple(drag_override["coords"]) if drag_override and drag_override.get("type") in {"leg-end", "activity"} else None
        rerouted = reroute_trip_object(trip_obj, route_preferences, start_override=start_override, end_override=end_override, selection=selection)
        if "legs" not in rerouted:
            return json.dumps(rerouted, ensure_ascii=False)
        if step_idx is None:
            updated = rerouted
        else:
            updated["steps"][step_idx]["data"] = rerouted
            updated["selection"] = selection
            updated["query_preferences"] = dict(updated.get("query_preferences") or {}) | route_preferences
        return json.dumps(updated, ensure_ascii=False)

    if operation["operation"] == "reroute_day":
        day_index = selection.get("day_index")
        if not isinstance(day_index, int):
            return None
        changed = False
        for idx in get_day_step_indices(updated, day_index):
            step = updated["steps"][idx]
            if step.get("type") != "trip":
                continue
            rerouted = reroute_trip_object(step.get("data", {}), route_preferences, selection=selection)
            if "legs" in rerouted:
                updated["steps"][idx]["data"] = rerouted
                changed = True
        if not changed:
            return json.dumps({"type": "error", "message": "Für den ausgewählten Tag konnten keine Teilstrecken neu berechnet werden."}, ensure_ascii=False)
        updated["selection"] = selection
        updated["query_preferences"] = dict(updated.get("query_preferences") or {}) | route_preferences
        return json.dumps(updated, ensure_ascii=False)

    if operation["operation"] == "replace_activity" and updated.get("type") == "multi_step_plan":
        step_index = selection.get("step_index")
        if not isinstance(step_index, int):
            return None
        return json.dumps(replace_activity_in_plan(updated, step_index, selection, route_preferences, payload.get("text", "")), ensure_ascii=False)

    if operation["operation"] == "delete_activity" and updated.get("type") == "multi_step_plan":
        step_index = selection.get("step_index")
        if not isinstance(step_index, int):
            return None
        return json.dumps(delete_activity_from_plan(updated, step_index, selection, route_preferences), ensure_ascii=False)

    if operation["operation"] in {"move_activity", "apply_route_preferences"} and updated.get("type") == "multi_step_plan":
        step_index = selection.get("step_index")
        if not isinstance(step_index, int):
            return None
        return json.dumps(
            update_adjacent_trips_for_activity(updated, step_index, updated["steps"][step_index], route_preferences, drag_override, selection),
            ensure_ascii=False,
        )

    return None


@app.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("✅ Frontend verbunden!")

    messages = [{
        "role": "system",
        "content": (
            "Du bist KIRA. Deine Aufgabe ist es, JSON-Daten für das Frontend zu generieren.\n"
            "Regeln:\n"
            "1. Übertrage Transportwünsche des Users konsequent in route_preferences.\n"
            "2. Für bestehende Auswahl-Kontexte kann eine strukturierte edit_operation vorliegen.\n"
            "3. Für reine Verbindung A->B: get_simple_route.\n"
            "4. Für lokale Ortssuche ohne Reiseplan: search_local_places.\n"
            "5. Für Tagestrip: plan_single_day_trip.\n"
            "6. Für Mehrtagesreise: plan_multiday_trip.\n"
            "7. Wenn das Ziel unbekannt ist, zuerst find_best_city.\n"
            "8. Sobald du ein Planungs-Tool ausgeführt hast, gib keinen zusätzlichen Fließtext aus."
        ),
    }]

    try:
        while True:
            raw_input = await websocket.receive_text()
            payload = normalize_ws_payload(raw_input)
            user_text = str(payload.get('text', '')).strip()
            print(f"📩 User: {user_text}")
            session_state = get_session_state(payload.get("session_id"))
            ensure_request_state(session_state)
            payload.setdefault("selection", session_state.get("selection"))
            if not payload.get("current_trip") and session_state.get("current_trip"):
                payload["current_trip"] = session_state.get("current_trip")
            payload.setdefault("route_preferences", session_state.get("route_preferences") or {})

            deterministic_result = apply_deterministic_edit(payload)
            if deterministic_result is not None:
                update_session_from_result(session_state, deterministic_result, payload.get("selection"))
                await websocket.send_text(deterministic_result)
                continue

            request_state = ensure_request_state(session_state)
            if should_reset_request_state(user_text, request_state):
                request_state = build_empty_request_state()
                session_state["request_state"] = request_state

            message_mode = classify_message_mode(user_text, request_state, payload)

            if message_mode == "request":
                updates = extract_request_updates(user_text, request_state)
                updates["route_preferences"] = extract_route_preferences_from_text(
                    user_text,
                    request_state.get("route_preferences") or session_state.get("route_preferences") or {},
                )
                if payload.get("selected_pois"):
                    updates["selected_pois"] = payload.get("selected_pois")
                request_state = merge_request_state(request_state, updates, raw_text=user_text)
                request_state["missing_fields"] = get_missing_request_fields(request_state)
                request_state["optional_fields_remaining"] = get_optional_request_fields(request_state)
                request_state["pending_question_field"] = None
                request_state["pending_question_optional"] = False
                session_state["request_state"] = request_state
                session_state["route_preferences"] = dict(session_state.get("route_preferences") or {}) | dict(request_state.get("route_preferences") or {})

                clarification = build_clarification_question(request_state, request_state["missing_fields"])
                if clarification:
                    field, question, is_optional = clarification
                    request_state["pending_question_field"] = field
                    request_state["pending_question_optional"] = is_optional
                    session_state["request_state"] = request_state
                    await websocket.send_text(request_state_to_response(request_state, question))
                    continue

                try:
                    result_str = execute_request_state(request_state, payload)
                    request_state["fulfilled"] = True
                    request_state["pending_question_field"] = None
                    request_state["missing_fields"] = []
                    session_state["request_state"] = request_state
                    update_session_from_result(session_state, result_str, payload.get("selection"))
                    await websocket.send_text(result_str)
                    continue
                except Exception as exc:
                    session_state["last_error"] = str(exc)
                    await websocket.send_text(json.dumps({"type": "error", "message": f"Dynamische Anfrage konnte nicht verarbeitet werden: {exc}"}, ensure_ascii=False))
                    continue

            if message_mode == "chat":
                final_text = generate_normal_chat_response(session_state, user_text)
                session_state["selection"] = payload.get("selection")
                await websocket.send_text(final_text)
                continue

    except WebSocketDisconnect:
        print("❌ Frontend getrennt")
    except Exception as exc:
        print(f"❌ WebSocket Fehler: {exc}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": f"Backend-Fehler: {exc}"}, ensure_ascii=False))
        except Exception:
            pass



@app.post("/api/debug/pois")
def debug_pois(request: Dict[str, Any]):
    bbox = request.get("bbox")

    if not bbox:
        raise HTTPException(status_code=400, detail="bbox missing")

    north = bbox.get("north")
    south = bbox.get("south")
    east = bbox.get("east")
    west = bbox.get("west")

    indices = [POI_MAP_INDEX, POI_INDEX]

    query = {
        "size": 10,
        "_source": True,
        "query": {
            "geo_bounding_box": {
                "location": {
                    "top_left": {"lat": north, "lon": west},
                    "bottom_right": {"lat": south, "lon": east},
                }
            }
        }
    }

    results = {}
    total_hits = 0

    for index in indices:
        try:
            resp = os_client.search(index=index, body=query)
            hits = resp.get("hits", {}).get("hits", [])

            results[index] = {
                "hit_count": len(hits),
                "sample_docs": [h["_source"] for h in hits[:3]],
            }

            total_hits += len(hits)

        except Exception as e:
            results[index] = {"error": str(e)}

    return {
        "bbox_received": bbox,
        "indices_checked": indices,
        "total_hits": total_hits,
        "index_results": results,
    }