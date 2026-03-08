import copy
import json
import os
import re
import sys
import uuid
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
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


def get_session_state(session_id: Optional[str]) -> Dict[str, Any]:
    key = session_id or 'anonymous'
    if key not in SESSION_STATE:
        SESSION_STATE[key] = {
            'current_trip': None,
            'selection': None,
            'route_preferences': {},
            'last_error': None,
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


def extract_route_preferences_from_text(text: str, base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    lower = (text or "").lower()
    prefs: Dict[str, Any] = dict(base or {})

    if any(word in lower for word in ["auto", "car", "mit dem auto", "fahren"]):
        prefs["primary_mode"] = "CAR"
        prefs["allowed_modes"] = ["CAR"]
    elif any(word in lower for word in ["fahrrad", "bike", "rad"]):
        prefs["primary_mode"] = "BICYCLE"
        prefs["allowed_modes"] = ["BICYCLE", "WALK"]
    elif any(word in lower for word in ["zu fuß", "zu fuss", "walk", "laufen"]):
        prefs["primary_mode"] = "WALK"
        prefs["allowed_modes"] = ["WALK"]
    elif any(word in lower for word in ["öpnv", "oepnv", "transit", "bahn", "bus", "zug"]):
        prefs["primary_mode"] = "TRANSIT"
        prefs.setdefault("allowed_modes", ["WALK", "TRANSIT"])

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
    current_day = 0
    collected = []
    for idx, step in enumerate(current_trip.get("steps", [])):
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
            print(f"📩 User: {payload.get('text', '')}")
            session_state = get_session_state(payload.get("session_id"))
            payload.setdefault("selection", session_state.get("selection"))
            if not payload.get("current_trip") and session_state.get("current_trip"):
                payload["current_trip"] = session_state.get("current_trip")

            deterministic_result = apply_deterministic_edit(payload)
            if deterministic_result is not None:
                update_session_from_result(session_state, deterministic_result, payload.get("selection"))
                await websocket.send_text(deterministic_result)
                continue

            prompt = build_contextual_user_prompt(payload)
            messages.append({"role": "user", "content": prompt})

            for _ in range(5):
                response = client.chat.completions.create(
                    model=DEPLOYMENT_NAME,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice="auto",
                )
                response_msg = response.choices[0].message
                messages.append(response_msg)

                if response_msg.tool_calls:
                    should_break_loop = False

                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)
                        print(f"⚙️ Tool: {func_name}")
                        result_str = ""

                        try:
                            if func_name == "find_best_city":
                                city = find_best_city_logic(**args)
                                result_str = f"City found: {city}. Now call a planning tool for {city}."
                            else:
                                args.pop("edit_operation", None)
                                if func_name == "get_simple_route":
                                    result_str = plan_journey_logic(**args)
                                elif func_name == "search_local_places":
                                    args.pop("route_preferences", None)
                                    args.pop("selection", None)
                                    result_str = plan_activities_logic(**args)
                                elif func_name == "plan_single_day_trip":
                                    args.pop("edit_operation", None)
                                    result_str = plan_complete_trip_logic(**args)
                                elif func_name == "plan_multiday_trip":
                                    args.pop("edit_operation", None)
                                    result_str = plan_multiday_trip_logic(**args)
                                else:
                                    result_str = json.dumps({"type": "error", "message": f"Unbekanntes Tool: {func_name}"}, ensure_ascii=False)

                                update_session_from_result(session_state, result_str, payload.get("selection"))
                                await websocket.send_text(result_str)
                                should_break_loop = True
                        except Exception as exc:
                            result_str = json.dumps({"type": "error", "message": f"Tool-Ausführung fehlgeschlagen ({func_name}): {exc}"}, ensure_ascii=False)
                            session_state["last_error"] = str(exc)
                            await websocket.send_text(result_str)
                            should_break_loop = True

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": result_str,
                            }
                        )

                    if should_break_loop:
                        break
                else:
                    final_text = response_msg.content
                    if final_text:
                        session_state["selection"] = payload.get("selection")
                        await websocket.send_text(final_text)
                    break

    except WebSocketDisconnect:
        print("❌ Frontend getrennt")
    except Exception as exc:
        print(f"❌ WebSocket Fehler: {exc}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": f"Backend-Fehler: {exc}"}, ensure_ascii=False))
        except Exception:
            pass
