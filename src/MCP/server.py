import os
import json
import requests
from fastmcp import FastMCP
from dotenv import load_dotenv


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(ROOT, ".env"))

mcp = FastMCP("KIRA-Agent-Server")

TRIP_PLANNER_URL = os.getenv("TRIP_PLANNER_URL", "http://trip-planner:8001").rstrip("/")


def _pretty(obj) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)[:4000]
    except Exception:
        return str(obj)[:4000]


@mcp.tool()
def plan_journey(start: str, end: str, date: str = "", time: str = "") -> str:
    """
    Plant eine Reise via trip-planner Service (OTP-Logik bleibt im trip-planner).

    Args:
        start: Starthaltestelle (z.B. "Fischen")
        end: Zielhaltestelle (z.B. "Sonthofen")
        date: optional YYYY-MM-DD
        time: optional HH:MM
    """
    payload = {"from_stop": start, "to_stop": end}
    if date:
        payload["date"] = date
    if time:
        payload["time"] = time

    # DEV DEBUG
    print(f"[MCP][plan_journey] Calling {TRIP_PLANNER_URL}/plan-by-stops with payload:\n{_pretty(payload)}")

    try:
        r = requests.post(f"{TRIP_PLANNER_URL}/plan-by-stops", json=payload, timeout=60)
        print(f"[MCP][plan_journey] HTTP {r.status_code}")
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[MCP][plan_journey] ERROR calling trip-planner: {e}")
        return f"Error calling trip-planner: {e}"

    # DEV DEBUG (preview response)
    print(f"[MCP][plan_journey] trip-planner response (preview):\n{_pretty(data)}")

    # Try to format a readable summary; fallback to raw JSON
    try:
        itins = data["data"]["plan"]["itineraries"]
        if not itins:
            return "Leider keine Verbindung gefunden."

        legs = itins[0]["legs"]
        lines = []
        for leg in legs:
            mode = leg.get("mode")
            from_name = leg.get("from", {}).get("name")
            to_name = leg.get("to", {}).get("name")
            dur_min = int((leg.get("duration", 0) or 0) / 60)

            route = leg.get("route") or {}
            line = route.get("shortName") or route.get("longName") or ""

            if mode == "WALK":
                lines.append(f"WALK ({dur_min} min): {from_name} → {to_name}")
            else:
                lines.append(f"{mode} {line}: {from_name} → {to_name} ({dur_min} min)")

        summary = "\n".join(lines)
        print(f"[MCP][plan_journey] Summary:\n{summary}")
        return summary
    except Exception as e:
        print(f"[MCP][plan_journey] Could not parse plan response: {e}")
        return _pretty(data)


if __name__ == "__main__":
    print("[MCP] Starting server.py ...")
    print(f"[MCP] TRIP_PLANNER_URL={TRIP_PLANNER_URL}")
    mcp.run()
