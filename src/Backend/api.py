import sys
import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
mcp_path = os.path.abspath(os.path.join(current_dir, "..", "MCP"))
if mcp_path not in sys.path:
    sys.path.append(mcp_path)

# Alle Logic-Funktionen importieren
from agent_server import (
    plan_journey_logic, 
    plan_activities_logic, 
    plan_complete_trip_logic, 
    plan_multiday_trip_logic, 
    find_best_city_logic
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
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
)
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")

# --- TOOLS SCHEMA ---
tools_schema = [
    {
        "type": "function",
        "function": {
            "name": "plan_journey",
            "description": "Plans a simple A to B route (public transport or walking).",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "time_str": {"type": "string"}
                },
                "required": ["start", "end"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "plan_activities",
            "description": "Finds activities, museums, or restaurants in a location.",
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
            "description": "Plans a ONE-DAY trip from A to B with stops (museums, etc.). Use for requests like 'Plan a trip to Sonthofen with museums'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "interest": {"type": "string"}
                },
                "required": ["start", "end", "interest"]
            }
        }
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
                    "days": {"type": "integer"}
                },
                "required": ["start", "end"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_best_city",
            "description": "Internal Tool: Finds a city if the user didn't specify one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        }
    }
]

@app.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("✅ Frontend verbunden!")
    
    # SYSTEM PROMPT UPDATE: Flexibler & Strenger gegen Plauderei
    messages = [{
        "role": "system", 
        "content": (
            "Du bist KIRA. Deine Aufgabe ist es, JSON-Daten für das Frontend zu generieren.\n"
            "REGELN:\n"
            "1. Wenn das Ziel unbekannt ist -> Nutze 'find_best_city'.\n"
            "2. Für Tagesausflüge/Routen mit Stopps -> Nutze 'plan_complete_trip'.\n"
            "3. Für Mehrtagesreisen/Wochenenden -> Nutze 'plan_multiday_trip'.\n"
            "4. WICHTIG: Sobald du ein Planungs-Tool (Punkt 2 oder 3) aufgerufen hast, ist deine Arbeit erledigt. "
            "Generiere danach KEINEN Text mehr."
        )
    }]

    try:
        while True:
            user_text = await websocket.receive_text()
            print(f"📩 User: {user_text}")
            messages.append({"role": "user", "content": user_text})

            # KI Loop (max 5 Schritte)
            for _ in range(5): 
                response = client.chat.completions.create(
                    model=DEPLOYMENT_NAME,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice="auto"
                )
                
                response_msg = response.choices[0].message
                messages.append(response_msg)

                if response_msg.tool_calls:
                    should_break_loop = False # Flag zum Stoppen

                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)
                        print(f"⚙️ Tool: {func_name}")
                        
                        result_str = ""
                        
                        # A. INTERNE TOOLS (Loop läuft weiter)
                        if func_name == "find_best_city":
                            city = find_best_city_logic(**args)
                            result_str = f"City found: {city}. Now call a planning tool for {city}."
                            print(f"   📍 Intern: {city}")

                        # B. VISUELLE TOOLS (JSON senden & Loop stoppen!)
                        else:
                            if func_name == "plan_journey":
                                result_str = plan_journey_logic(**args)
                            elif func_name == "plan_activities":
                                result_str = plan_activities_logic(**args)
                            elif func_name == "plan_complete_trip":
                                result_str = plan_complete_trip_logic(**args)
                            elif func_name == "plan_multiday_trip":
                                result_str = plan_multiday_trip_logic(**args)
                            
                            # SOFORT SENDEN
                            await websocket.send_text(result_str)
                            
                            # Wir haben eine Karte gesendet -> STOPP!
                            # Wir wollen nicht, dass die KI danach noch Text schreibt.
                            should_break_loop = True

                        # Ergebnis ins Gedächtnis
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_str
                        })

                    # Wenn wir eine Karte gesendet haben, brechen wir den KI-Loop ab.
                    # Die KI darf keine Zusammenfassung mehr schreiben.
                    if should_break_loop:
                        break 
                    
                else:
                    # Nur wenn KEIN Tool benutzt wurde, senden wir Text
                    final_text = response_msg.content
                    if final_text:
                        await websocket.send_text(final_text)
                    break 

    except WebSocketDisconnect:
        print("❌ Frontend getrennt")