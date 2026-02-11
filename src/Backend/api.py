import sys
import os
import json
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
current_dir = os.path.dirname(os.path.abspath(__file__))   # Wo bin ich? (src/Backend)
mcp_path = os.path.abspath(os.path.join(current_dir, "..", "MCP")) # Der Weg zum Nachbarn
if mcp_path not in sys.path:
    sys.path.append(mcp_path)
from agent_server import plan_journey_logic, plan_activities_logic, plan_complete_trip_logic, plan_multiday_trip_logic, find_best_city_logic

# Importiere deine Tools
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../MCP")))
from agent_server import plan_journey, plan_activities
from openai import AzureOpenAI

load_dotenv()

app = FastAPI()

# CORS erlauben (damit React zugreifen darf)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Azure Client
client = AzureOpenAI(
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")
)
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")

# Tools Definition für GPT
tools_schema = [
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
            "description": "Plans a full itinerary from A to B including stops at interesting places (museums, restaurants). Use this when user asks for a trip WITH activities.",
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
            "description": "Generates a full itinerary for a specific number of days. Use this when the user asks for a 'trip', 'weekend' (2 days), or specifies a duration.",
            "parameters": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "days": {
                        "type": "integer", 
                        "description": "Number of days. Extract from user prompt (e.g. 'weekend' = 2, '3 days' = 3). Default to 4 if not specified."
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
            "description": "Finds the best matching city/town in Allgäu for specific interests (e.g. 'Quad', 'Wellness'). Use this FIRST if the user does not specify a destination city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The interests, e.g. 'Quad activities and water sports'"}
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
    
    # SYSTEM PROMPT UPDATE: Instruktionen für den mehrstufigen Prozess
    messages = [{
        "role": "system", 
        "content": (
            "Du bist KIRA. "
            "1. Wenn der User keine Zielstadt nennt, nutze 'find_best_city' um sie zu finden. "
            "2. Wenn der User keinen Startort nennt, nimm 'Fischen' als Standard an. "
            "3. Nutze DANN 'plan_multiday_trip' um den Plan zu erstellen. "
            "4. Antworte bei Tools NUR mit dem JSON."
        )
    }]

    try:
        while True:
            # 1. User Input empfangen
            user_text = await websocket.receive_text()
            print(f"📩 User: {user_text}")
            messages.append({"role": "user", "content": user_text})

            # --- START: KI-LOOP (MULTI-STEP) ---
            # Wir loopen so lange, bis die KI keine Tools mehr aufruft (oder max 5 mal)
            for _ in range(5): 
                response = client.chat.completions.create(
                    model=DEPLOYMENT_NAME,
                    messages=messages,
                    tools=tools_schema,
                    tool_choice="auto"
                )
                
                response_msg = response.choices[0].message
                messages.append(response_msg) # Antwort (oder Tool Call) ins Gedächtnis

                if response_msg.tool_calls:
                    # Die KI will Tools nutzen!
                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)
                        print(f"⚙️ Tool Call: {func_name}")
                        
                        result_str = ""
                        # Tool Routing
                        if func_name == "plan_journey":
                            result_str = plan_journey_logic(**args)
                            await websocket.send_text(result_str) # JSON an Frontend

                        elif func_name == "plan_activities":
                            result_str = plan_activities_logic(**args)
                            await websocket.send_text(result_str) # JSON an Frontend

                        elif func_name == "plan_multiday_trip":
                            result_str = plan_multiday_trip_logic(**args)
                            await websocket.send_text(result_str) # JSON an Frontend
                            
                        elif func_name == "find_best_city":
                            # Hier senden wir NICHTS an das Frontend, 
                            # das ist nur ein interner Zwischenschritt für die KI!
                            result_str = find_best_city_logic(**args)
                            print(f"   📍 Stadt gefunden: {result_str}")

                        # Ergebnis zurück ins Gedächtnis, damit die KI weitermachen kann
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_str
                        })
                    
                    # WICHTIG: Der Loop läuft weiter! 
                    # Die KI liest jetzt das Tool-Ergebnis (z.B. "Oberstdorf") 
                    # und entscheidet im nächsten Durchlauf: "Aha, jetzt plane ich den Trip nach Oberstdorf."
                    
                else:
                    # Keine Tools mehr? Dann ist es die finale Textantwort.
                    final_text = response_msg.content
                    if final_text:
                        await websocket.send_text(final_text)
                    break # KI ist fertig, warte auf neuen User Input
            # --- ENDE KI-LOOP ---

    except WebSocketDisconnect:
        print("❌ Frontend getrennt")