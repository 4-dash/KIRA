import json
import os
from dotenv import load_dotenv

load_dotenv()
from typing import Any, Dict, List, Optional

from fastapi import WebSocket, WebSocketDisconnect
from openai import AzureOpenAI

from mcp_tools import (
    find_best_city_logic,
    plan_activities_logic,
    plan_complete_trip_logic,
    plan_journey_logic,
    plan_multiday_trip_logic,
)


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def build_azure_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
        api_key=_env("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
    )


# --- TOOLS SCHEMA (ported from source repo Backend/api.py; keep names/behavior) ---
TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_simple_route",
            "description": "Berechnet nur eine reine Fahrt von A nach B, ohne Aktivitäten.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "time_str": {"type": "string"},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_local_places",
            "description": "Sucht NUR eine lose Liste von Orten. GIBT KEINEN Zeitplan zurück. 🔴 VERBOTEN: Nutze dies NIEMALS, wenn der User eine Reise plant oder ändert.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "interest": {"type": "string"},
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_single_day_trip",
            "description": "Plant oder ändert einen EINZELNEN Tagesausflug (ohne Übernachtung). 🔴 VERBOTEN: Nicht nutzen für Mehrtagesreisen oder wenn der User 'Tag 2' etc. erwähnt!",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "interest": {"type": "string"},
                    "num_stops": {"type": "integer"},
                    "avoid_places": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["start", "end", "interest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_multiday_trip",
            "description": "Plant oder ÄNDERT eine komplette Mehrtagesreise. 🟢 PFLICHT: Nutze zwingend dieses Tool, wenn der User 'Tag 2' erwähnt oder einen bestehenden Trip ändern will! Lese start, end, days aus Chat. Nutze activity_pref/culture_pref='Museum' für mehr Museen.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "days": {"type": "integer"},
                    "hotel_pref": {"type": "string"},
                    "activity_pref": {"type": "string"},
                    "food_pref": {"type": "string"},
                    "culture_pref": {"type": "string"},
                    "avoid_places": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_best_city",
            "description": "Internal Tool: Finds a city if the user didn't specify one.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "Du bist KIRA. Deine Aufgabe ist es, JSON-Daten für das Frontend zu generieren.\n"
    "REGELN:\n"
    "1. Wenn das Ziel unbekannt ist -> Nutze 'find_best_city'.\n"
    "2. Für Tagesausflüge/Routen mit Stopps -> Nutze 'plan_single_day_trip'.\n"
    "3. Für Mehrtagesreisen/Wochenenden -> Nutze 'plan_multiday_trip'.\n"
    "4. WICHTIG: Sobald du ein Planungs-Tool (Punkt 2 oder 3) aufgerufen hast, ist deine Arbeit erledigt. "
    "Generiere danach KEINEN Text mehr."
)


async def handle_chat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    print("✅ Frontend verbunden!")

    client = build_azure_client()
    deployment = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    try:
        while True:
            user_text = await websocket.receive_text()
            print(f"📩 User: {user_text}")
            messages.append({"role": "user", "content": user_text})

            # If we send a tool JSON payload to the frontend, we must stop the loop
            # (Match behavior of the old source branch: no additional assistant summary after tool output).
            should_break_loop = False

            # Main Loop (Multi-Step)
            for _ in range(5):
                response = client.chat.completions.create(
                    model=deployment,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )

                msg = response.choices[0].message
                messages.append(msg)

                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        func_name = tc.function.name
                        args_str = tc.function.arguments or "{}"
                        print(f"⚙️ Tool Call: {func_name}")

                        try:
                            args = json.loads(args_str)
                        except Exception:
                            args = {}

                        result_str = ""

                        if func_name == "get_simple_route":
                            result_str = plan_journey_logic(
                                start=args.get("start", ""),
                                end=args.get("end", ""),
                                time_str=args.get("time_str", "tomorrow 07:30"),
                            )
                            await websocket.send_text(result_str)

                            # Tool payload sent -> stop the assistant loop (frontend renders JSON)
                            should_break_loop = True

                        elif func_name == "search_local_places":
                            result_str = plan_activities_logic(
                                location=args.get("location", ""),
                                interest=args.get("interest", ""),
                            )
                            await websocket.send_text(result_str)

                            # Tool payload sent -> stop the assistant loop (frontend renders JSON)
                            should_break_loop = True

                        elif func_name == "plan_multiday_trip":
                            result_str = plan_multiday_trip_logic(
                                start=args.get("start", ""),
                                end=args.get("end", ""),
                                days=int(args.get("days", 4) or 4),
                            )
                            await websocket.send_text(result_str)

                            # Tool payload sent -> stop the assistant loop (frontend renders JSON)
                            should_break_loop = True

                        elif func_name == "plan_single_day_trip":
                            result_str = plan_complete_trip_logic(
                                start=args.get("start", ""),
                                end=args.get("end", ""),
                                interest=args.get("interest", ""),
                                num_stops=int(args.get("num_stops", 2) or 2),
                            )
                            await websocket.send_text(result_str)

                            # Tool payload sent -> stop the assistant loop (frontend renders JSON)
                            should_break_loop = True

                        elif func_name == "find_best_city":
                            result_str = find_best_city_logic(query=args.get("query", ""))
                            print(f"   📍 Stadt gefunden: {result_str}")
                            # Internal step, do NOT send to frontend directly

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": result_str,
                            }
                        )

                    # If we already sent a tool payload to the frontend, stop here.
                    if should_break_loop:
                        break

                else:
                    # Final text response (only when NO tool was used)
                    final_text = msg.content
                    if final_text:
                        await websocket.send_text(final_text)
                    break

    except WebSocketDisconnect:
        print("❌ Frontend getrennt")