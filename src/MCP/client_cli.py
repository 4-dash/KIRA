import asyncio
import os
import sys
import json
from dotenv import load_dotenv

from openai import AzureOpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 1) Load .env (local dev)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(ROOT, ".env"))


AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o")
API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview")

if not AZURE_API_KEY or not AZURE_ENDPOINT:
    print("FEHLER: Bitte stelle sicher, dass deine .env Datei existiert und AZURE_OPENAI_ENDPOINT/AZURE_OPENAI_API_KEY gesetzt sind.")
    sys.exit(1)

# Azure client
client = AzureOpenAI(
    azure_endpoint=AZURE_ENDPOINT,
    api_key=AZURE_API_KEY,
    api_version=API_VERSION,
)

# 2) MCP server via stdio (LOCAL PROCESS)
server_params = StdioServerParameters(
    command=sys.executable,
    args=["server.py"],
    env=None,
)


def _pretty(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)[:4000]
    except Exception:
        return str(obj)[:4000]


async def run_chat_loop():
    print("🔌 Verbinde mit MCP Server (server.py via stdio/local) ...")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # A) Load tools
            mcp_tools = await session.list_tools()

            # B) Convert MCP tools -> OpenAI tool schema
            openai_tools = []
            for tool in mcp_tools.tools:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    },
                })

            print(f"✅ Verbunden! {len(openai_tools)} Tools geladen.")
            print("Schreibe 'exit' zum Beenden.")

            messages = [
                {"role": "system", "content": "Du bist ein hilfreicher Assistent, der Zugang zu Tools via MCP hat."}
            ]

            while True:
                try:
                    user_input = input("\nDu: ").strip()
                except EOFError:
                    break

                if user_input.lower() in {"exit", "quit"}:
                    break

                messages.append({"role": "user", "content": user_input})

                print("[DEV] Sending to Azure OpenAI ...")
                response = client.chat.completions.create(
                    model=DEPLOYMENT_NAME,
                    messages=messages,
                    tools=openai_tools if openai_tools else None,
                    tool_choice="auto",
                )

                response_msg = response.choices[0].message

                # Tool call path
                if response_msg.tool_calls:
                    print(f"[DEV] Model requested {len(response_msg.tool_calls)} tool call(s).")
                    messages.append(response_msg)

                    for tool_call in response_msg.tool_calls:
                        func_name = tool_call.function.name
                        func_args_raw = tool_call.function.arguments or "{}"

                        try:
                            func_args = json.loads(func_args_raw)
                        except Exception:
                            func_args = {}
                        print(f"[DEV] Tool call: {func_name} args={_pretty(func_args)}")

                        try:
                            result = await session.call_tool(func_name, arguments=func_args)
                            tool_output = str(result.content)
                        except Exception as e:
                            tool_output = f"Error executing tool: {e}"

                        print(f"[DEV] Tool output (preview): {tool_output[:800]}")

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": tool_output,
                        })

                    print("[DEV] Sending tool outputs back to Azure OpenAI for final response ...")
                    final_response = client.chat.completions.create(
                        model=DEPLOYMENT_NAME,
                        messages=messages,
                        tools=openai_tools,
                    )
                    ai_text = final_response.choices[0].message.content
                    print(f"KIRA: {ai_text}")
                    messages.append(final_response.choices[0].message)

                else:
                    # No tool usage
                    print(f"KIRA: {response_msg.content}")
                    messages.append(response_msg)


if __name__ == "__main__":
    try:
        asyncio.run(run_chat_loop())
    except KeyboardInterrupt:
        print("\nBeendet.")
