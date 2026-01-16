import asyncio
import os
import sys
import json
from dotenv import load_dotenv

# OpenAI & MCP Bibliotheken
from openai import AzureOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 1. KONFIGURATION LADEN (.env)
load_dotenv()

AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

if not AZURE_API_KEY or not AZURE_ENDPOINT:
    print("❌ FEHLER: Bitte stelle sicher, dass deine .env Datei existiert und gefüllt ist.")
    sys.exit(1)

# Azure Client initialisieren
client = AzureOpenAI(
    azure_endpoint=AZURE_ENDPOINT,
    api_key=AZURE_API_KEY,
    api_version=API_VERSION
)

# 2. MCP SERVER KONFIGURATION
# Wir nutzen sys.executable, um sicherzustellen, dass wir dieselbe stabile Python-Version nutzen
server_params = StdioServerParameters(
    command=sys.executable, 
    args=["agent_server.py"], 
    env=None
)

async def run_chat_loop():
    print(f"🔌 Verbinde mit MCP Server (agent_server.py)...")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # A. TOOLS LADEN
            mcp_tools = await session.list_tools()
            
            # B. TOOLS FÜR OPENAI UMWANDELN
            openai_tools = []
            for tool in mcp_tools.tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema
                    }
                })

            print(f"✅ Verbunden! {len(openai_tools)} Tools geladen.")
            print("💬 Du kannst jetzt mit deinem Agenten chatten. (Schreibe 'exit' zum Beenden)")

            # C. CHAT LOOP
            messages = [
                {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Zugang zu speziellen Tools hat via MCP."}
            ]
            
            while True:
                try:
                    user_input = input("\nDu: ")
                except EOFError:
                    break
                    
                if user_input.lower() in ["exit", "quit"]:
                    break
                
                messages.append({"role": "user", "content": user_input})

                # 1. Anfrage an GPT-4o
                response = client.chat.completions.create(
                    model=DEPLOYMENT_NAME,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                    tool_choice="auto"
                )
                
                response_msg = response.choices[0].message
                
                # 2. Prüfen, ob GPT ein Tool nutzen will
                if response_msg.tool_calls:
                    messages.append(response_msg) # Verlauf speichern
                    
                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        func_args = tool_call.function.arguments
                        
                        print(f"🤖 Agent nutzt Tool: {func_name} ...")
                        
                        # 3. Tool auf dem MCP Server ausführen
                        try:
                            result = await session.call_tool(
                                func_name,
                                arguments=json.loads(func_args)
                            )
                            tool_output = str(result.content)
                        except Exception as e:
                            tool_output = f"Error executing tool: {str(e)}"

                        # 4. Ergebnis an GPT zurücksenden
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_output
                        })
                    
                    # 5. Finale Antwort generieren (mit dem Wissen aus dem Tool)
                    final_response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=messages,
                        tools=openai_tools
                    )
                    ai_text = final_response.choices[0].message.content
                    print(f"KIRA: {ai_text}")
                    messages.append(final_response.choices[0].message)
                
                else:
                    # Keine Tool-Nutzung, einfache Antwort
                    print(f"KIRA: {response_msg.content}")
                    messages.append(response_msg)

if __name__ == "__main__":
    try:
        asyncio.run(run_chat_loop())
    except KeyboardInterrupt:
        print("\nBeendet.")