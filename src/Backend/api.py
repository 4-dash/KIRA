import sys
import os
import json
import asyncio
import uuid
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from opensearchpy import OpenSearch, RequestsHttpConnection

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

# --- DATENBANK VERBINDUNG FÜR GESPEICHERTE TRIPS ---
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))

os_client = OpenSearch(
    hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
    use_ssl=False, verify_certs=False, connection_class=RequestsHttpConnection
)

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

# --- NEUES, STRENGES TOOLS SCHEMA ---
tools_schema = [
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
                    "time_str": {"type": "string"}
                },
                "required": ["start", "end"]
            }
        }
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
                    "interest": {"type": "string"}
                },
                "required": ["location"]
            }
        }
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
                    "avoid_places": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["start", "end", "interest"]
            }
        }
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
                    "avoid_places": {"type": "array", "items": {"type": "string"}}
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
    
    messages = [{
        "role": "system", 
        "content": (
            "Du bist KIRA. Deine Aufgabe ist es, JSON-Daten für das Frontend zu generieren.\n"
            "REGELN:\n"
            "1. Wenn das Ziel unbekannt ist -> Nutze 'find_best_city'.\n"
            "2. Für Tagesausflüge/Routen mit Stopps -> Nutze 'plan_single_day_trip'.\n"
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

            # KI Loop
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
                    should_break_loop = False

                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)
                        print(f"⚙️ Tool: {func_name}")
                        
                        result_str = ""
                        
                        # A. INTERNE TOOLS
                        if func_name == "find_best_city":
                            city = find_best_city_logic(**args)
                            result_str = f"City found: {city}. Now call a planning tool for {city}."
                            print(f"   📍 Intern: {city}")

                        # B. VISUELLE TOOLS (Neue Namen zugewiesen!)
                        else:
                            if func_name == "get_simple_route":
                                result_str = plan_journey_logic(**args)
                            elif func_name == "search_local_places":
                                result_str = plan_activities_logic(**args)
                            elif func_name == "plan_single_day_trip":
                                result_str = plan_complete_trip_logic(**args)
                            elif func_name == "plan_multiday_trip":
                                result_str = plan_multiday_trip_logic(**args)
                            
                            await websocket.send_text(result_str)
                            should_break_loop = True

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_str
                        })

                    if should_break_loop:
                        break 
                    
                else:
                    final_text = response_msg.content
                    if final_text:
                        await websocket.send_text(final_text)
                    break 

    except WebSocketDisconnect:
        print("❌ Frontend getrennt")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)