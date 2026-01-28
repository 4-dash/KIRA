import os
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from fastmcp import FastMCP
from llama_index.llms.azure_openai import AzureOpenAI
from llama_index.core import Settings
from opensearchpy import OpenSearch
from typing import Optional

# 1. KONFIGURATION LADEN
load_dotenv()

# OTP & OpenSearch Config
OTP_URL = "http://localhost:8080/otp/routers/default/index/graphql"
OPENSEARCH_HOST = {'host': 'localhost', 'port': 9200}
INDEX_NAME = "travel-plans"

# Azure Config prüfen
if not os.getenv("AZURE_OPENAI_API_KEY"):
    raise ValueError(" FEHLER: AZURE_OPENAI_API_KEY fehlt in der .env Datei!")

# 2. LLM SETUP (Für RAG/Wissen - optional, aber gut zu haben)
llm = AzureOpenAI(
    model="gpt-4o",
    deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
    temperature=0
)
Settings.llm = llm

# 3. INITIALISIERUNG MCP SERVER
mcp = FastMCP("KIRA-Agent-Server")

# --- HILFSFUNKTIONEN (Aus deinem robusten Skript) ---

def get_coords(target_name: str):
    """Sucht Koordinaten für einen Ortsnamen in OTP."""
    query = """
    {
      stops { name lat lon }
    }
    """
    try:
        response = requests.post(OTP_URL, json={"query": query}, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if 'data' in data and 'stops' in data['data']:
                for stop in data['data']['stops']:
                    if stop['name'].lower() == target_name.lower(): # Toleranter Vergleich
                        return stop['lat'], stop['lon']
    except Exception as e:
        print(f" Fehler bei Koordinatensuche: {e}")
    return None, None

def query_otp_api(from_lat, from_lon, to_lat, to_lon, departure_time):
    """Fragt die OTP 2.8 API nach einer Route."""
    # GraphQL Query für OTP 2.8 (angepasst an deinen Erfolg vorhin)
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
        response = requests.post(OTP_URL, json={"query": query, "variables": variables}, timeout=10)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- DAS NEUE TOOL FÜR DEN AGENTEN ---

@mcp.tool()
def plan_journey(start: str, end: str, time_str: str = "tomorrow 07:30") -> str:
    """
    Plant eine Reise mit öffentlichen Verkehrsmitteln (Zug/Bus).
    
    Args:
        start: Name der Starthaltestelle (z.B. "Fischen")
        end: Name der Zielhaltestelle (z.B. "Sonthofen")
        time_str: Uhrzeit (Format "YYYY-MM-DD HH:MM" oder "tomorrow 07:30")
    """
    

    # 1. Datum parsen
    try:
        if "tomorrow" in time_str.lower():
            tomorrow = datetime.now() + timedelta(days=1)
            # Versuche Uhrzeit aus "tomorrow 07:30" zu lesen
            parts = time_str.split()
            if len(parts) > 1:
                hour, minute = map(int, parts[1].split(':'))
                trip_time = tomorrow.replace(hour=hour, minute=minute, second=0)
            else:
                trip_time = tomorrow.replace(hour=7, minute=30) # Default
        else:
            trip_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    except:
        return " Fehler: Ich konnte das Datumsformat nicht verstehen. Bitte nutze 'YYYY-MM-DD HH:MM'."

    # 2. Koordinaten holen
    start_lat, start_lon = get_coords(start)
    end_lat, end_lon = get_coords(end)

    if not start_lat or not end_lat:
        return f" Ich konnte die Koordinaten für '{start}' oder '{end}' nicht finden. Sind die Namen korrekt?"

    # 3. OTP abfragen
    data = query_otp_api(start_lat, start_lon, end_lat, end_lon, trip_time)

    # 4. Ergebnis auswerten
    if data and data.get('data') and data['data'].get('plan') and data['data']['plan'].get('itineraries'):
        itinerary = data['data']['plan']['itineraries'][0]
        
        # Zusammenfassung bauen
        summary = f" Route gefunden für {trip_time.strftime('%d.%m.%Y')}:\n"
        
        for leg in itinerary['legs']:
            mode = leg['mode']
            start_t = datetime.fromtimestamp(leg['startTime'] / 1000).strftime('%H:%M')
            end_t = datetime.fromtimestamp(leg['endTime'] / 1000).strftime('%H:%M')
            origin = leg['from']['name']
            dest = leg['to']['name']
            
            # Zug/Bus Details
            route_info = leg.get('route') or {}
            line = route_info.get('shortName') or route_info.get('longName') or ""
            
            if mode == "WALK":
                summary += f" Laufweg ({int(leg['duration']/60)} min) von {origin} nach {dest}\n"
            else:
                summary += f" {mode} {line}: Abfahrt {start_t} ({origin}) -> Ankunft {end_t} ({dest})\n"

        # 5. Optional: In OpenSearch speichern (Loggen)
        try:
            client = OpenSearch(hosts=[OPENSEARCH_HOST], use_ssl=False, verify_certs=False)
            if client.indices.exists(index=INDEX_NAME):
                doc = {
                    "start": start, "end": end, "time": trip_time, 
                    "summary": summary, "created": datetime.now()
                }
                client.index(index=INDEX_NAME, body=doc, refresh=True)
                
        except:
            pass # Fehler beim Speichern ignorieren, dem User trotzdem antworten

        return summary
    else:
        return " Leider keine Verbindung gefunden. Vielleicht fahren um diese Zeit keine Züge?"

if __name__ == "__main__":
    mcp.run()