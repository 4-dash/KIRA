import json
import os
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


# --- TOOLS SCHEMA (Matched to Eric's branch) ---
TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "plan_journey",
            "description": "Plant eine Reise. MUSS benutzt werden wenn nach Routen gefragt wird.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "time_str": {"type": "string", "description": "e.g. 'tomorrow 08:00'"},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_activities",
            "description": "Sucht nach Aktivitäten.",
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
            "name": "plan_complete_trip",
            "description": "Plans a full itinerary from A to B including stops at interesting places (museums, restaurants).",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "interest": {"type": "string", "description": "Type of activity, e.g. 'Museums' or 'Food'"},
                    "num_stops": {"type": "integer", "description": "How many intermediate POI stops to add", "default": 2},
                },
                "required": ["start", "end", "interest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_multiday_trip",
            "description": "Plans a MULTI-DAY itinerary (e.g. 'Weekend', '3 days').",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "days": {"type": "integer"},
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

SYSTEM_PROMPT = """Du bist KIRA. Nutze Tools wenn der User nach Routen/Trips/Aktivitäten fragt.
WICHTIG: Antworte bei Tools NUR mit dem JSON.
"""


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

                        if func_name == "plan_journey":
                            result_str = plan_journey_logic(
                                start=args.get("start", ""),
                                end=args.get("end", ""),
                                time_str=args.get("time_str", "tomorrow 07:30"),
                            )
                            await websocket.send_text(result_str)

                            # Tool payload sent -> stop the assistant loop (frontend renders JSON)
                            should_break_loop = True

                        elif func_name == "plan_activities":
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

                        elif func_name == "plan_complete_trip":
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
