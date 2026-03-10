import copy
import json
import os
import re
import sys
import uuid
from typing import Any, Dict, Optional, Tuple, List

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
    "start": "Startort",
    "end": "Zielort",
    "base_location": "Basisort",
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
    ]
    lower = text.lower()
    for keyword in keywords:
        if keyword in lower:
            return keyword
    explicit = re.search(r"\b(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\b", text)
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


def extract_request_updates(text: str, current_state: Dict[str, Any]) -> Dict[str, Any]:
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
        if pending_field in {"start", "end", "base_location", "date", "interest"} and cleaned:
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
        updates["date"] = date_phrase
        updates["time_str"] = f"{date_phrase} 09:00"

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
        return ["interest", "pace", "activities_per_day", "date"]
    if trip_type in {"day_trip", "base_explore"}:
        return ["pace", "activities_per_day", "date"]
    if trip_type == "local_search":
        return ["pace", "activities_per_day", "date"]
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
        if field == "interest":
            return field, "Möchtest du bestimmte Interessen angeben? Du kannst auch mit 'nein' ablehnen.", True
        return field, f"Optional: {REQUEST_FIELD_LABELS.get(field, field)}. Mit 'nein' überspringen.", True
    return None


def request_state_to_response(state: Dict[str, Any], question: str) -> str:
    summary_keys = [
        "trip_type", "start", "end", "base_location", "roundtrip_base", "days", "date", "interest", "pace", "activities_per_day", "missing_fields", "optional_fields_remaining", "selected_pois"
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
            start=state.get("start"),
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
            start=state.get("start") or base,
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
        start=state.get("start") or base,
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
