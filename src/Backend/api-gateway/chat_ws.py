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
    # Uses Azure OpenAI (Chat Completions)
    return AzureOpenAI(
        azure_endpoint=_env("AZURE_OPENAI_ENDPOINT"),
        api_key=_env("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
    )


TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "plan_journey",
            "description": "Plan a public-transport journey between two places.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "date": {"type": "string", "description": "YYYY-MM-DD (optional)"},
                    "time": {"type": "string", "description": "HH:MM (optional)"},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_activities",
            "description": "Find activities/POIs for a location, optionally filtered by interest.",
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
            "name": "plan_multiday_trip",
            "description": "Create a multi-day trip plan from start to end with activities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "days": {"type": "integer"},
                    "interest": {"type": "string"},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "plan_complete_trip",
            "description": "Create a complete trip plan with multiple stops and activities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "interest": {"type": "string"},
                    "num_stops": {"type": "integer"},
                },
                "required": ["start", "end", "interest"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_best_city",
            "description": "Pick best-matching city for a query (internal step; not shown to user).",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]


SYSTEM_PROMPT = """
Du bist ein Reiseassistent.
Regeln:
1) Wenn der Nutzer keine Zielstadt nennt, nutze find_best_city(query) um eine passende Stadt zu bestimmen (intern).
2) Wenn der Nutzer keinen Start nennt, setze Start standardmäßig auf "Fischen".
3) Danach nutze plan_multiday_trip(start, end, days, interest) als Standard.
4) Bei Tool-Aufrufen: gib NUR JSON-Argumente zurück.
"""


async def handle_chat_websocket(websocket: WebSocket) -> None:
    await websocket.accept()

    client = build_azure_client()
    deployment = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")

    messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    try:
        while True:
            user_text = await websocket.receive_text()
            messages.append({"role": "user", "content": user_text})

            # Tool loop: allow the model to call tools up to N times
            for _ in range(6):
                resp = client.chat.completions.create(
                    model=deployment,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                )

                choice = resp.choices[0]
                msg = choice.message

                # If the model replied normally (no tools), send to frontend as-is
                if not msg.tool_calls:
                    if msg.content:
                        await websocket.send_text(
                            json.dumps({"type": "assistant_message", "content": msg.content})
                        )
                        messages.append({"role": "assistant", "content": msg.content})
                    break

                # Otherwise: execute tool calls
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                    }
                )

                for tc in msg.tool_calls:
                    tool_name = tc.function.name
                    raw_args = tc.function.arguments or "{}"
                    try:
                        args = json.loads(raw_args)
                    except Exception:
                        args = {}

                    # Route tools
                    if tool_name == "plan_journey":
                        result = plan_journey_logic(
                            start=args.get("start", ""),
                            end=args.get("end", ""),
                            date=args.get("date"),
                            time=args.get("time"),
                        )

                        # Stream to frontend immediately
                        await websocket.send_text(result)

                    elif tool_name == "plan_activities":
                        result = plan_activities_logic(
                            location=args.get("location", ""),
                            interest=args.get("interest", ""),
                        )
                        await websocket.send_text(result)

                    elif tool_name == "plan_multiday_trip":
                        result = plan_multiday_trip_logic(
                            start=args.get("start", ""),
                            end=args.get("end", ""),
                            days=int(args.get("days", 4) or 4),
                            interest=args.get("interest", ""),
                        )
                        await websocket.send_text(result)

                    elif tool_name == "plan_complete_trip":
                        result = plan_complete_trip_logic(
                            start=args.get("start", ""),
                            end=args.get("end", ""),
                            interest=args.get("interest", ""),
                            num_stops=int(args.get("num_stops", 2) or 2),
                        )
                        await websocket.send_text(result)

                    elif tool_name == "find_best_city":
                        # Internal step: do NOT stream to frontend
                        result = find_best_city_logic(query=args.get("query", ""))
                    else:
                        result = json.dumps(
                            {"type": "error", "message": f"Unknown tool: {tool_name}"}
                        )

                    # Always feed tool result back to the model
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tool_name,
                            "content": result,
                        }
                    )

            # end tool loop

    except WebSocketDisconnect:
        return
