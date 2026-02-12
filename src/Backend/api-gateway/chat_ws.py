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
                    "time_str": {"type": "string", "description": "e.g. 'tomorrow 08:00'"}
                },
                "required": ["start", "end"]
            }
        }
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
                    "interest": {"type": "string"}
                },
                "required": ["location"]
            }
        }
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
                    "interest": {"type": "string", "description": "Type of activity, e.g. 'Museums' or 'Food'"}
                },
                "required": ["start", "end", "interest"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "plan_multiday_trip",
            "description": "Generates a full itinerary for a specific number of days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "days": {
                        "type": "integer", 
                        "description": "Number of days. Extract from user prompt (e.g. 'weekend' = 2). Default to 4."
                    }
                },
                "required": ["start", "end"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_best_city",
            "description": "Finds the best matching city in Allgäu for specific interests. Use FIRST if user has no destination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The interests, e.g. 'Quad activities'"}
                },
                "required": ["query"]
            }
        }
    }
]


# --- SYSTEM PROMPT (from Eric's branch) ---
SYSTEM_PROMPT = """
Du bist KIRA. 
1. Wenn der User keine Zielstadt nennt, nutze 'find_best_city' um sie zu finden. 
2. Wenn der User keinen Startort nennt, nimm 'Fischen' als Standard an. 
3. Nutze DANN 'plan_multiday_trip' um den Plan zu erstellen. 
4. Antworte bei Tools NUR mit dem JSON.
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
                        except:
                            args = {}

                        result_str = ""

                        if func_name == "plan_journey":
                            result_str = plan_journey_logic(
                                start=args.get("start", ""),
                                end=args.get("end", ""),
                                time_str=args.get("time_str", "tomorrow 07:30")
                            )
                            await websocket.send_text(result_str)

                        elif func_name == "plan_activities":
                            result_str = plan_activities_logic(
                                location=args.get("location", ""),
                                interest=args.get("interest", "")
                            )
                            await websocket.send_text(result_str)

                        elif func_name == "plan_multiday_trip":
                            result_str = plan_multiday_trip_logic(
                                start=args.get("start", ""),
                                end=args.get("end", ""),
                                days=int(args.get("days", 4) or 4)
                            )
                            await websocket.send_text(result_str)

                        elif func_name == "plan_complete_trip":
                            result_str = plan_complete_trip_logic(
                                start=args.get("start", ""),
                                end=args.get("end", ""),
                                interest=args.get("interest", ""),
                                num_stops=int(args.get("num_stops", 2) or 2)
                            )
                            await websocket.send_text(result_str)

                        elif func_name == "find_best_city":
                            result_str = find_best_city_logic(
                                query=args.get("query", "")
                            )
                            print(f"   📍 Stadt gefunden: {result_str}")
                            # Internal step, do NOT send to frontend directly

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_str,
                        })

                else:
                    # Final text response
                    final_text = msg.content
                    if final_text:
                        # Wrap in JSON if the frontend expects it, or send raw text
                        # Eric's api.py sent raw text at the end.
                        await websocket.send_text(final_text)
                    break
    except WebSocketDisconnect:
        print("❌ Frontend getrennt")