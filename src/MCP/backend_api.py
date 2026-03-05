import asyncio
import os
import sys
import json
from contextlib import asynccontextmanager, AsyncExitStack
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from datetime import datetime

from openai import AzureOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from opensearchpy import OpenSearch, RequestsHttpConnection
import uuid

# Konfiguration
load_dotenv()
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

client = AzureOpenAI(
    azure_endpoint=AZURE_ENDPOINT,
    api_key=AZURE_API_KEY,
    api_version=API_VERSION
)

# Pfad zum Agenten
server_params = StdioServerParameters(
    command=sys.executable, 
    args=["agent_server.py"], 
    env=None
)

mcp_session = None
openai_tools = []

@asynccontextmanager
async def lifespan(app: FastAPI):
    global mcp_session, openai_tools
    print("🔌 Starting MCP Client...")
    stack = AsyncExitStack()
    try:
        read, write = await stack.enter_async_context(stdio_client(server_params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        
        tools_result = await session.list_tools()
        openai_tools = [{
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.inputSchema
            }
        } for tool in tools_result.tools]
        
        mcp_session = session
        
        # 🔥 NEU: Druckt die exakten Tool-Namen ins Terminal!
        tool_names = [tool.name for tool in tools_result.tools]
        print(f"✅ MCP Connected! Loaded {len(openai_tools)} tools: {', '.join(tool_names)}")
        
        yield
    finally:
        print("🛑 Shutting down MCP Client...")
        await stack.aclose()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In Produktion anpassen auf deine Frontend-URL (z.B. localhost:3000)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- NEU: DATENBANK VERBINDUNG FÜR GESPEICHERTE TRIPS ---
os_client = OpenSearch(
    hosts=[{'host': os.getenv('OPENSEARCH_HOST','opensearch'), 'port': int(os.getenv('OPENSEARCH_PORT','9200'))}],
    use_ssl=False, verify_certs=False, connection_class=RequestsHttpConnection
)

@app.post("/api/save_trip")
async def save_trip(request: Request):
    try:
        trip_data = await request.json()
        trip_id = str(uuid.uuid4()) # Generiert eine einmalige ID
        
        # Speichert die Daten in einem neuen Index 'saved-trips'
        os_client.index(index="saved-trips", id=trip_id, body=trip_data)
        
        print(f"💾 Trip {trip_id} erfolgreich in DB gespeichert!")
        return {"status": "success", "id": trip_id}
    except Exception as e:
        print(f"❌ Fehler beim Speichern: {e}")
        return {"status": "error", "message": str(e)}

@app.websocket("/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    messages = [{
        "role": "system", 
        "content": f"You are KIRA. Today is {datetime.now().strftime('%Y-%m-%d')}. If you use 'plan_journey', output ONLY the raw JSON string from the tool."
    }]

    try:
        while True:
            user_text = await websocket.receive_text()
            messages.append({"role": "user", "content": user_text})

            response = client.chat.completions.create(
                model=DEPLOYMENT_NAME,
                messages=messages,
                tools=openai_tools if openai_tools else None,
                tool_choice="auto"
            )
            
            msg = response.choices[0].message
            
            if msg.tool_calls:
                messages.append(msg)
                for tool in msg.tool_calls:
                    print(f"Executing {tool.function.name}...")
                    args = json.loads(tool.function.arguments)
                    result = await mcp_session.call_tool(tool.function.name, arguments=args)
                    
                    tool_output = result.content[0].text
                    
                    # 1. WICHTIG: Das JSON direkt an das Frontend senden (für die Karte)
                    await websocket.send_text(tool_output)
                    
                    # 2. Das Ergebnis trotzdem ins Gedächtnis der KI speichern
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool.id,
                        "content": tool_output
                    })
                
                # 3. Wir überspringen die "Zusammenfassung" der KI.
                # Wir wollen nicht, dass sie danach noch Text sendet.
                continue 
            else:
                messages.append(msg)
                await websocket.send_text(msg.content)

    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)