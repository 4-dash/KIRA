import os
import requests
import sys
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastmcp import FastMCP
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.core import Settings
from opensearchpy import OpenSearch
from typing import Optional

# 1. KONFIGURATION LADEN
load_dotenv()

# --- DEINE ORIGINALE KONFIGURATION (UNVERÄNDERT) ---
OTP_URL = "http://localhost:8080/otp/routers/default/index/graphql"
OPENSEARCH_HOST = {'host': 'localhost', 'port': 9200}
INDEX_NAME = "travel-plans"
# ---------------------------------------------------
def log(msg):
    sys.stderr.write(f"[LOG] {msg}\n")
    sys.stderr.flush()
# Azure Config prüfen
if not os.getenv("AZURE_OPENAI_API_KEY"):
    log("WARNUNG: AZURE_OPENAI_API_KEY fehlt in der .env Datei!")

# 2. LLM SETUP
try:
    llm = AzureOpenAI(
        model="gpt-4o",
        deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o"),
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
        temperature=0
    )
    Settings.llm = llm
except Exception as e:
    log(f"LLM Fehler: {e}")

# 3. INITIALISIERUNG MCP SERVER
mcp = FastMCP("KIRA-Agent-Server")

# --- HILFSFUNKTIONEN ---

def get_coords(target_name: str):
    """
    FIX: Nutzt Nominatim (OpenStreetMap) statt OTP GraphQL.
    Das war der Grund, warum 'Fischen' nicht gefunden wurde.
    """
    try:
        headers = {'User-Agent': 'KIRA-Agent/1.0'}
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={target_name}"
        
        # Timeout etwas höher für langsame Verbindungen
        r = requests.get(url, headers=headers, timeout=5)
        
        if r.status_code == 200 and len(r.json()) > 0:
            lat = float(r.json()[0]['lat'])
            lon = float(r.json()[0]['lon'])
            return lat, lon
    except Exception as e:
        log(f"Fehler bei Nominatim Suche nach '{target_name}': {e}")
    
    return None, None

def query_otp_api(from_lat, from_lon, to_lat, to_lon, departure_time):
    """
    Nutzt deine GraphQL URL für die Abfrage.
    """
    # Standard OTP v2 GraphQL Query
    query = """
    query PlanTrip($fromLat: Float!, $fromLon: Float!, $toLat: Float!, $toLon: Float!, $date: String!, $time: String!) {
      plan(
        from: {lat: $fromLat, lon: $fromLon}
        to: {lat: $toLat, lon: $toLon}
        date: $date
        time: $time
        numItineraries: 1
        transportModes: [{mode: TRANSIT}, {mode: WALK}]
        walkReluctance: 2.0
      ) {
        itineraries {
          duration
          legs {
            mode
            startTime
            endTime
            duration
            route { shortName longName }
            from { name }
            to { name }
          }
        }
      }
    }
    """
    
    variables = {
        "fromLat": from_lat, "fromLon": from_lon,
        "toLat": to_lat, "toLon": to_lon,
        "date": departure_time.strftime("%Y-%m-%d"),
        "time": departure_time.strftime("%H:%M")
    }
    
    try:
        log(f"Sende GraphQL an: {OTP_URL}")
        # Wir nutzen requests.post für GraphQL
        response = requests.post(OTP_URL, json={"query": query, "variables": variables}, timeout=60)
        return response.json()
    except Exception as e:
        log(f"OTP GraphQL Fehler: {e}")
        return {"error": str(e)}

# --- DAS TOOL FÜR DEN AGENTEN ---

@mcp.tool()
def plan_journey(start: str, end: str, time_str: str = "tomorrow 07:30") -> str:
    """
    Plant eine Reise mit öffentlichen Verkehrsmitteln (Zug/Bus).
    """
    log(f"🤖 Agent: Suche Route {start} -> {end} ({time_str})")

    # 1. Datum parsen
    try:
        trip_time = datetime.now()
        if "tomorrow" in time_str.lower():
            trip_time = trip_time + timedelta(days=1)
            parts = time_str.split()
            if len(parts) > 1 and ":" in parts[-1]:
                h, m = map(int, parts[-1].split(':'))
                trip_time = trip_time.replace(hour=h, minute=m, second=0)
            else:
                trip_time = trip_time.replace(hour=7, minute=30)
        elif "-" in time_str:
             try:
                trip_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
             except:
                pass
    except:
        return "Fehler: Datumsformat nicht erkannt."

    # 2. Koordinaten holen (JETZT REPARIERT MIT NOMINATIM)
    start_lat, start_lon = get_coords(start)
    end_lat, end_lon = get_coords(end)

    if not start_lat or not end_lat:
        return f"Ich konnte die Koordinaten für '{start}' oder '{end}' nicht finden (Nominatim)."

    # 3. OTP abfragen (Nimmt deine GraphQL URL)
    data = query_otp_api(start_lat, start_lon, end_lat, end_lon, trip_time)

    # 4. Ergebnis auswerten
    if data and data.get('data') and data['data'].get('plan') and data['data']['plan'].get('itineraries'):
        itinerary = data['data']['plan']['itineraries'][0]
        
        duration = int(itinerary['duration'] / 60)
        summary = f"✅ Route gefunden ({duration} Min) für {trip_time.strftime('%d.%m.%Y')}:\n"
        
        for leg in itinerary['legs']:
            mode = leg['mode']
            start_t = datetime.fromtimestamp(leg['startTime'] / 1000).strftime('%H:%M')
            end_t = datetime.fromtimestamp(leg['endTime'] / 1000).strftime('%H:%M')
            origin = leg['from']['name']
            dest = leg['to']['name']
            
            line = ""
            if leg.get('route'):
                line = leg['route'].get('shortName') or leg['route'].get('longName') or ""
            
            if mode == "WALK":
                summary += f"🚶 Laufweg ({int(leg['duration']/60)} min) -> {dest}\n"
            else:
                summary += f"🚆 {mode} {line}: {origin} ({start_t}) -> {dest} ({end_t})\n"

        # 5. Optional: In OpenSearch speichern (Deine Logik)
        try:
            client = OpenSearch(hosts=[OPENSEARCH_HOST], use_ssl=False, verify_certs=False)
            if client.indices.exists(index=INDEX_NAME):
                doc = {
                    "start": start, "end": end, "time": trip_time, 
                    "summary": summary, "created": datetime.now()
                }
                client.index(index=INDEX_NAME, body=doc, refresh=True)
        except:
            pass 

        return summary
    else:
        err = "Keine Verbindung gefunden."
        if data.get("errors"):
            log(f"OTP Error Details: {data['errors']}")
            err += f" (Server: {data['errors'][0]['message']})"
        return err

if __name__ == "__main__":
    mcp.run()