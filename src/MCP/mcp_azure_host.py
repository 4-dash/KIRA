import asyncio
import os
import sys
import json
from dotenv import load_dotenv
from datetime import datetime
import locale

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
    print(" FEHLER: Bitte stelle sicher, dass deine .env Datei existiert und gefüllt ist.")
    sys.exit(1)

# Azure Client initialisieren
client = AzureOpenAI(
    azure_endpoint=AZURE_ENDPOINT,
    api_key=AZURE_API_KEY,
    api_version=API_VERSION
)
try:
    locale.setlocale(locale.LC_TIME, 'de_DE.UTF-8')
except:
    pass

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

            print(f" Verbunden! {len(openai_tools)} Tools geladen.")
            print("Du kannst jetzt mit deinem Agenten chatten. (Schreibe 'exit' zum Beenden)")

            today_str = datetime.now().strftime("%A, %d.%m.%Y")

            system_instruction = f"""
    Du bist KIRA, ein intelligenter Reiseassistent für das Allgäu.
    
    WICHTIGE INFORMATION:
    - Heute ist: {today_str}.
    - Wenn der Nutzer sagt "morgen", "übermorgen" oder "nächsten Freitag", 
      rechne das Datum basierend auf dem heutigen Tag aus und nutze das Format YYYY-MM-DD für die Tools.
    
    Verhalte dich hilfreich und präzise.
    """

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

               # --- START CHANGE: Loop for handling Retries/Multi-step tools ---
                while True:
                    # 1. Ask GPT-4o
                    response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=messages,
                        tools=openai_tools if openai_tools else None,
                        tool_choice="auto"
                    )
                    
                    response_msg = response.choices[0].message
                    messages.append(response_msg) # Always save the AI response immediately
                    
                    # 2. Check if GPT wants to use a tool
                    if response_msg.tool_calls:
                        for tool_call in response_msg.tool_calls:
                            func_name = tool_call.function.name
                            func_args = tool_call.function.arguments
                            
                            print(f" ⚙️ Agent nutzt Tool: {func_name} ...")
                            
                            # 3. Execute Tool
                            try:
                                result = await session.call_tool(
                                    func_name,
                                    arguments=json.loads(func_args)
                                )
                                # Clean up the output format
                                tool_output = ""
                                if result.content:
                                    for item in result.content:
                                        if hasattr(item, 'text'):
                                            tool_output += item.text
                                        else:
                                            tool_output += str(item)
                                else:
                                    tool_output = "Success"
                            except Exception as e:
                                tool_output = f"Error executing tool: {str(e)}"

                            # 4. Send Result back to GPT
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": tool_output
                            })
                        
                        # IMPORTANT: No 'break' here! 
                        # The loop continues so GPT can read the result and decide 
                        # if it needs to retry (fix the error) or answer you.
                    
                    else:
                        # No tools used? Then this is the final answer.
                        print(f"KIRA: {response_msg.content}")
                        break # Break inner loop, wait for next user input
                # --- END CHANGE ---
if __name__ == "__main__":
    try:
        asyncio.run(run_chat_loop())
    except KeyboardInterrupt:
        print("\nBeendet.")