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
# --- LlamaIndex & OpenSearch Imports für Activities ---
from llama_index.core import VectorStoreIndex, Settings
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from opensearchpy import OpenSearch, RequestsHttpConnection
import json
import random
from collections import Counter
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

# --- KONFIGURATION FÜR DATENBANK ---
OPENSEARCH_HOST = "localhost"  # Geht via SSH-Tunnel zur VM
OPENSEARCH_PORT = 9200
INDEX_NAME = os.getenv("POI_INDEX", "tourism-data-v6")

# --- ACTIVITY ENGINE SETUP ---
activity_engine = None

try:
    # 1. Embedding Modell laden (Muss identisch zum Ingester auf der VM sein!)
    # sys.stderr.write hilft beim Debuggen, ohne den MCP-Stream zu stören
    sys.stderr.write("[SERVER] Lade Embedding Modell...\n")
    Settings.embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    Settings.llm = None # Wir brauchen hier kein LLM, nur die Suche

    # 2. Verbindung zur VM-Datenbank (via Tunnel)
    sys.stderr.write(f"[SERVER] Verbinde zu OpenSearch Index '{INDEX_NAME}'...\n")
    os_client = OpenSearch(
        hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
        use_ssl=False, verify_certs=False, connection_class=RequestsHttpConnection
    )
    
    # 3. LlamaIndex verknüpfen
    client_wrapper = OpensearchVectorClient(
        endpoint=f"http://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}",
        index=INDEX_NAME,
        dim=384,
        embedding_field="embedding",
        text_field="description",
        os_client=os_client
    )
    
    vector_store = OpensearchVectorStore(client_wrapper)
    activity_index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
    
    # 4. Engine erstellen (Sucht die Top 5 Ergebnisse)
    activity_engine = activity_index.as_query_engine(similarity_top_k=5)
    sys.stderr.write("[SERVER] ✅ Activities Datenbank erfolgreich verbunden.\n")

except Exception as e:
    sys.stderr.write(f"[SERVER] ⚠️ ACHTUNG: Konnte Activity-Datenbank nicht laden: {e}\n")
    # Wir lassen den Server trotzdem starten, damit andere Tools funktionieren

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
        numItineraries: 3
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



def plan_journey_logic(start: str, end: str, time_str: str = "tomorrow 07:30") -> str:
    """
    Die eigentliche Logik, ohne @mcp.tool Dekorator.
    Kann von api.py direkt aufgerufen werden.
    """
    sys.stderr.write(f"[LOGIC] Suche Route {start} -> {end} ({time_str})\n")

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
    except:
        return json.dumps({"error": "Datumsfehler"})

    # 2. Koordinaten holen (Du musst sicherstellen, dass get_coords hier verfügbar ist)
    # (Falls get_coords nicht definiert ist, füge es oben wieder ein oder importiere es)
    from agent_server import get_coords, query_otp_api # Self-import trick oder Funktionen nach oben schieben
    
    start_lat, start_lon = get_coords(start)
    end_lat, end_lon = get_coords(end)

    if not start_lat or not end_lat:
        return json.dumps({"error": f"Koordinaten nicht gefunden für {start} oder {end}"})

    # 3. OTP abfragen
    data = query_otp_api(start_lat, start_lon, end_lat, end_lon, trip_time)

    # 4. JSON bauen
    if data and data.get('data') and data['data'].get('plan') and data['data']['plan'].get('itineraries'):
        itin = data['data']['plan']['itineraries'][0]
        
        frontend_data = {
            "start": start,
            "end": end,
            "date": trip_time.strftime("%d.%m.%Y"),
            "total_duration": int(itin['duration'] / 60),
            "legs": []
        }

        for leg in itin['legs']:
            mode = leg['mode']
            start_t = datetime.fromtimestamp(leg['startTime'] / 1000).strftime('%H:%M')
            end_t = datetime.fromtimestamp(leg['endTime'] / 1000).strftime('%H:%M')
            
            line_name = ""
            if leg.get('route'):
                line_name = leg['route'].get('shortName') or leg['route'].get('longName') or ""

            from_name = leg['from']['name']
            to_name = leg['to']['name']

            # Wenn OTP "Origin" sagt, nehmen wir den Start-Namen vom User (z.B. "Fischen")
            if from_name == "Origin":
                from_name = start
            
            # Wenn OTP "Destination" sagt, nehmen wir den Ziel-Namen (z.B. "Sonthofen")
            if to_name == "Destination":
                to_name = end
            
            frontend_data["legs"].append({
                "mode": mode,
                "from": from_name,
                "to": to_name,
                "start_time": start_t,
                "end_time": end_t,
                "line": line_name,
                "duration": int(leg['duration'] / 60)
            })

        return json.dumps(frontend_data)
    else:
        return json.dumps({"error": "Keine Verbindung gefunden"})

def plan_activities_logic(location: str, interest: str = "") -> str:
    """
    Sucht Aktivitäten und gibt sie als JSON-Liste zurück (für Frontend-Karten).
    """
    if not activity_engine:
        return json.dumps({"error": "Datenbank nicht verbunden."})
    
    query = f"{interest} in {location}" if interest else f"Highlights in {location}"
    sys.stderr.write(f"[LOGIC] Suche Activities: {query}\n")

    try:
        # 1. Anfrage an LlamaIndex
        response = activity_engine.query(query)
        
        # 2. Daten aus den "Source Nodes" extrahieren
        # (Das sind die echten DB-Einträge, die gefunden wurden)
        activities_list = []
        
        for node_with_score in response.source_nodes:
            node = node_with_score.node
            meta = node.metadata
            
            # Wir bauen ein sauberes Objekt für das Frontend
            activity_item = {
                "name": meta.get("name", "Unbekannter Ort"),
                "category": meta.get("category", "Sehenswürdigkeit"),
                "city": meta.get("city", location),
                "description": node.get_text()[:150] + "...", # Kurze Vorschau
                # Falls du Bild-URLs in den Daten hast: meta.get("image_url")
            }
            activities_list.append(activity_item)

        # 3. Als JSON zurückgeben (mit Typ-Marker "activity_list")
        result = {
            "type": "activity_list",
            "location": location,
            "items": activities_list
        }
        return json.dumps(result)

    except Exception as e:
        sys.stderr.write(f"[ERROR] {e}\n")
        return json.dumps({"error": str(e)})
    
def plan_complete_trip_logic(start: str, end: str, interest: str, num_stops: int = 2) -> str:
    """
    Plant eine komplette Route: Start -> Aktivität 1 -> Aktivität 2 -> Ziel.
    Gibt ein spezielles 'multi_step_plan' JSON zurück.
    """
    sys.stderr.write(f"[LOGIC] Plane kompletten Trip: {start} -> {interest} -> {end}\n")
    
    # 1. Aktivitäten finden (Nutze deine existierende Activity-Engine)
    # Wir suchen Aktivitäten am Zielort (oder am Startort, je nach Logik. Hier: Zielort).
    activities_json = plan_activities_logic(location=end, interest=interest)
    activities_data = json.loads(activities_json)
    
    if "error" in activities_data or not activities_data.get("items"):
        return json.dumps({"error": "Keine passenden Aktivitäten gefunden."})

    # Wir nehmen die Top X Aktivitäten
    stops = activities_data["items"][:num_stops]
    
    steps = []
    current_location = start
    
    # 2. Schleife durch die Stopps und Routen berechnen
    for stop in stops:
        stop_name = stop["name"]
        
        # A. Route berechnen: Aktueller Ort -> Nächster Stopp
        trip_json = plan_journey_logic(start=current_location, end=stop_name, time_str="tomorrow 09:00")
        trip_data = json.loads(trip_json)
        
        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data })
        else:
            # Fallback falls keine Route gefunden
            steps.append({ "type": "error", "message": f"Kein Weg gefunden von {current_location} nach {stop_name}" })

        # B. Die Aktivität selbst anzeigen
        steps.append({ "type": "activity", "data": stop })
        
        # Neuer Startpunkt ist jetzt dieser Stopp
        current_location = stop_name

    # 3. Letzte Strecke: Letzter Stopp -> Endgültiges Ziel (z.B. Hotel in Sonthofen)
    final_trip_json = plan_journey_logic(start=current_location, end=end, time_str="tomorrow 16:00")
    final_trip_data = json.loads(final_trip_json)
    if "legs" in final_trip_data:
         steps.append({ "type": "trip", "data": final_trip_data })

    # 4. Alles zusammenpacken
    result = {
        "type": "multi_step_plan",
        "intro": f"Ich habe eine Route von {start} nach {end} mit {len(stops)} Stopps ({interest}) geplant:",
        "steps": steps
    }
    
    return json.dumps(result)

def plan_multiday_trip_logic(start: str, end: str, days: int = 4) -> str:
    """
    Plant einen Trip mit variabler Dauer (days) UND berechnet die Routen
    zwischen allen Aktivitäten (Chaining).
    """
    if days < 1: days = 1
    
    sys.stderr.write(f"[LOGIC] Plane Trip für {days} Tage mit Routen: {start} -> {end}\n")
    
    # 1. POOLS FÜLLEN
    museums = json.loads(plan_activities_logic(end, "Museum"))
    food = json.loads(plan_activities_logic(end, "Restaurant Gaststätte"))
    leisure = json.loads(plan_activities_logic(end, "Wandern Natur Freizeit"))
    
    pool_museums = museums.get("items", [])
    pool_food = food.get("items", [])
    pool_leisure = leisure.get("items", [])
    
    steps = []
    
    # Hilfsfunktion: Holt nächstes Item
    def get_item(pool):
        return pool.pop(0) if pool else None

    # Hilfsfunktion: Berechnet Route und fügt sie in die Steps ein
    def add_route(origin, destination, time_str, label="Fahrt"):
        if not origin or not destination: return
        
        # Wir nutzen deine existierende Logic
        trip_json = plan_journey_logic(origin, destination, time_str)
        trip_data = json.loads(trip_json)
        
        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data, "label": label })
        else:
            steps.append({ 
                "type": "error", 
                "message": f"Kein Weg gefunden von {origin} nach {destination}" 
            })

    # Das "Hotel" oder der zentrale Punkt ist der Zielort (z.B. Sonthofen)
    base_location = end 
    current_loc = start # Wir starten zuhause

    # --- TAG 1: Anreise & Check-in ---
    steps.append({ "type": "header", "title": "📅 Tag 1: Anreise & Erstes Erkunden" })
    
    # 1. Fahrt: Zuhause -> Hotel/Stadtmitte
    add_route(current_loc, base_location, "tomorrow 10:00", "Anreise")
    current_loc = base_location # Wir sind jetzt im Hotel/Ort
    
    # 2. Erste Aktivität
    act1 = get_item(pool_museums) or get_item(pool_leisure)
    if act1:
        add_route(current_loc, act1["name"], "tomorrow 14:00") # Weg dorthin
        steps.append({ "type": "activity", "data": act1 })     # Die Aktivität
        current_loc = act1["name"]                             # Wir sind jetzt dort
        
    # 3. Abendessen
    dinner = get_item(pool_food)
    if dinner:
        add_route(current_loc, dinner["name"], "tomorrow 18:00")
        steps.append({ "type": "activity", "data": dinner })
        # Wir lassen den User beim Restaurant "stehen" (Rückweg zum Hotel implizit)

    # --- MITTELTEIL (Tag 2 bis Vorletzter Tag) ---
    for i in range(2, days):
        steps.append({ "type": "header", "title": f"📅 Tag {i}: Entdeckungstour" })
        
        # Morgens starten wir wieder vom "Hotel" (Basis)
        current_loc = base_location 
        
        # Vormittag
        act_am = get_item(pool_leisure)
        if act_am:
            add_route(current_loc, act_am["name"], "tomorrow 10:00")
            steps.append({ "type": "activity", "data": act_am })
            current_loc = act_am["name"]
        
        # Nachmittag
        act_pm = get_item(pool_museums)
        if act_pm:
            add_route(current_loc, act_pm["name"], "tomorrow 14:00")
            steps.append({ "type": "activity", "data": act_pm })
            current_loc = act_pm["name"]
        
        # Abend
        act_eve = get_item(pool_food)
        if act_eve:
            add_route(current_loc, act_eve["name"], "tomorrow 19:00")
            steps.append({ "type": "activity", "data": act_eve })

    # --- LETZTER TAG: Abreise ---
    steps.append({ "type": "header", "title": f"📅 Tag {days}: Abschied & Heimreise" })
    
    # Wir starten wieder am Hotel
    current_loc = base_location
    
    # Noch eine letzte kleine Aktivität?
    last_act = get_item(pool_leisure)
    if last_act:
        add_route(current_loc, last_act["name"], "tomorrow 10:00")
        steps.append({ "type": "activity", "data": last_act })
        # Für die Rückreise tun wir so, als würden wir vom Hotel abreisen (Gepäck holen)
    
    # Rückreise: Hotel -> Heimatort
    add_route(base_location, start, "tomorrow 16:00", "Rückreise")

    # ZUSAMMENFASSUNG
    result = {
        "type": "multi_step_plan",
        "intro": f"Ich habe die komplette Route für {days} Tage inkl. aller Wege berechnet:",
        "steps": steps
    }
    
    return json.dumps(result)

def find_best_city_logic(query: str) -> str:
    """
    Sucht basierend auf Interessen (z.B. "Quad fahren") die beste Stadt im Index.
    """
    # Fallback, falls DB nicht läuft
    if not activity_engine:
        return "Oberstdorf" 
        
    sys.stderr.write(f"[LOGIC] Suche beste Stadt für: {query}\n")
    
    # Wir suchen breit nach Aktivitäten
    response = activity_engine.query(f"Best location for {query}")
    
    cities = []
    # Wir zählen, welche Stadt in den Top-Treffern am häufigsten vorkommt
    for node in response.source_nodes:
        city = node.metadata.get("city")
        if city:
            cities.append(city)
            
    if not cities:
        return "Sonthofen" # Fallback Standard
        
    # Die häufigste Stadt gewinnen lassen
    most_common = Counter(cities).most_common(1)
    best_city = most_common[0][0]
    
    sys.stderr.write(f"[LOGIC] Gewinner-Stadt: {best_city}\n")
    return best_city

# ==========================================
# 2. DIE MCP TOOLS (Nur Wrapper)
# ==========================================

@mcp.tool()
def plan_journey(start: str, end: str, time_str: str = "tomorrow 07:30") -> str:
    """Plant eine Reise (Wrapper für MCP)."""
    return plan_journey_logic(start, end, time_str)

@mcp.tool()
def plan_activities(location: str, interest: str = "") -> str:
    """Sucht Aktivitäten (Wrapper für MCP)."""
    return plan_activities_logic(location, interest)

@mcp.tool()
def plan_complete_trip(start: str, end: str, interest: str) -> str:
    """Plant eine Reise mit Zwischenstopps basierend auf Interessen (z.B. Museen)."""
    return plan_complete_trip_logic(start, end, interest)

@mcp.tool()
def plan_multiday_trip(start: str, end: str, days: int = 4) -> str:
    """Plans a multi-day trip. Days can be specified by the user."""
    return plan_multiday_trip_logic(start, end, days)

@mcp.tool()
def find_best_city(query: str) -> str:
    """
    Analyzes the user's interests (e.g. 'Quad', 'Water') and finds the best city name in Allgäu.
    Returns ONLY the city name (e.g. 'Oberstdorf').
    """
    return find_best_city_logic(query)

if __name__ == "__main__":
    mcp.run()