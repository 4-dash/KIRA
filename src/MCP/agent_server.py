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
from math import radians, cos, sin, asin, sqrt
# 1. KONFIGURATION LADEN
load_dotenv()

# --- DEINE ORIGINALE KONFIGURATION (UNVERÄNDERT) ---
OTP_URL = "http://localhost:8080/otp/routers/default/index/graphql"
OPENSEARCH_HOST = {'host': 'localhost', 'port': 9200}
INDEX_NAME = "tourism-data-v6"
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
activity_retriever = None 

try:
    # 1. Embedding Modell laden
    sys.stderr.write("[SERVER] Lade Embedding Modell...\n")
    Settings.embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    Settings.llm = None 

    # 2. Verbindung zur VM-Datenbank
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
    
    # 4. Index & RETRIEVER erstellen
    # WICHTIG: .as_retriever() verhindert den Context-Size Fehler!
    # Es holt nur Daten, ohne sie durch ein LLM zu jagen.
    activity_index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
    activity_retriever = activity_index.as_retriever(similarity_top_k=500)
    
    sys.stderr.write("[SERVER] ✅ Activities Datenbank erfolgreich verbunden (Retriever Mode).\n")

except Exception as e:
    sys.stderr.write(f"[SERVER] ⚠️ ACHTUNG: Konnte Activity-Datenbank nicht laden: {e}\n")

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Berechnet die Entfernung zwischen zwei Punkten in km (Haversine-Formel).
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return 99999.0 # Unendlich weit weg
        
    R = 6371 # Erdradius in km
    dLat = radians(lat2 - lat1)
    dLon = radians(lon2 - lon1)
    a = sin(dLat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dLon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

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
    # UPDATE: Wir fragen jetzt auch 'intermediateStops' ab!
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
            legGeometry { points }
            route { shortName longName }
            from { name lat lon }
            to { name lat lon }
            intermediateStops { name lat lon }  # <--- NEU: Alle Haltestellen dazwischen!
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
        response = requests.post(OTP_URL, json={"query": query, "variables": variables}, timeout=60)
        return response.json()
    except Exception as e:
        sys.stderr.write(f"[ERROR] OTP Anfrage fehlgeschlagen: {e}\n")
        return {"error": str(e)}

def plan_journey_logic(start: str, end: str, time_str: str = "tomorrow 07:30", 
                       start_coords_override=None, end_coords_override=None) -> str:
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

    # 2. Koordinaten bestimmen (Entweder Override nutzen oder suchen)
    if start_coords_override:
        start_lat, start_lon = start_coords_override
    else:
        start_lat, start_lon = get_coords(start)

    if end_coords_override:
        end_lat, end_lon = end_coords_override
    else:
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

            # Start & Ziel
            from_node = leg['from']
            to_node = leg['to']
            from_name = from_node['name']
            to_name = to_node['name']
            from_coords = [from_node['lat'], from_node['lon']]
            to_coords = [to_node['lat'], to_node['lon']]

            if from_name == "Origin": from_name = start
            if to_name == "Destination": to_name = end
            
            # Geometrie
            geometry = ""
            if leg.get('legGeometry'): geometry = leg['legGeometry'].get('points', "")

            frontend_data["legs"].append({
                "mode": mode,
                "from": from_name,
                "to": to_name,
                "from_coords": from_coords,
                "to_coords": to_coords,
                "stops": [], 
                "start_time": start_t,
                "end_time": end_t,
                "line": line_name,
                "duration": int(leg['duration'] / 60),
                "geometry": geometry 
            })

        return json.dumps(frontend_data)
    else:
        return json.dumps({"error": "Keine Verbindung gefunden"})
    
def plan_activities_logic(location: str, interest: str = "") -> str:
    if not activity_retriever:
        return json.dumps({"error": "Datenbank nicht verbunden."})
    
    center_lat, center_lon = get_coords(location)
    if not center_lat:
        return json.dumps({"type": "activity_list", "location": location, "items": []})

    search_query = f"{interest} in {location}" if interest else f"Highlights in {location}"
    
    # --- DYNAMISCHE KONFIGURATION ---
    # Standard: Weiter Radius für Natur/Wandern (15 km)
    max_radius = 15.0 
    required_keywords = []
    
    lower_interest = interest.lower()
    
    # SPEZIAL-REGELN FÜR STADT-AKTIVITÄTEN
    if "museum" in lower_interest:
        search_query = f"Museum Ausstellung Geschichte Kultur in {location}"
        required_keywords = ["museum", "galerie", "ausstellung", "heimathaus", "sammlung"]
        max_radius = 3.0 # Museen müssen zentral sein
        
    elif "food" in lower_interest or "essen" in lower_interest or "restaurant" in lower_interest:
         search_query = f"Restaurant Gasthof Essen Traditionelle Küche in {location}"
         required_keywords = ["restaurant", "gasthof", "gaststätte", "bräu", "stube", "wirtshaus", "pizzeria"]
         max_radius = 3.0 # Zum Essen will man nicht weit fahren

    try:
        sys.stderr.write(f"[LOGIC] Suche Activities: '{search_query}' (Radius {max_radius}km)\n")
        nodes = activity_retriever.retrieve(search_query)
        
        activities_list = []
        
        for node_with_score in nodes:
            node = node_with_score.node
            meta = node.metadata
            name = meta.get("name", "Unbekannt")
            lower_name = name.lower()
            raw_category = str(meta.get("category", "")).lower()
            
            # --- 🛡️ TÜRSTEHER (Nur aktiv wenn Keywords gesetzt) ---
            if required_keywords:
                match_found = False
                for kw in required_keywords:
                    if kw in lower_name or kw in raw_category:
                        match_found = True
                        break
                if not match_found: continue
            # ------------------------------------------------------

            # Koordinaten Parsing
            lat = None
            lon = None
            if "lat" in meta: lat = meta["lat"]
            elif "latitude" in meta: lat = meta["latitude"]
            if "lon" in meta: lon = meta["lon"]
            elif "longitude" in meta: lon = meta["longitude"]

            if (lat is None or lon is None) and "location" in meta:
                loc_data = meta["location"]
                if isinstance(loc_data, str) and "," in loc_data:
                    try:
                        parts = loc_data.split(",")
                        lat = float(parts[0].strip())
                        lon = float(parts[1].strip())
                    except: pass
                elif isinstance(loc_data, dict):
                    lat = loc_data.get("lat") or loc_data.get("latitude")
                    lon = loc_data.get("lon") or loc_data.get("longitude")

            if lat is None or lon is None: continue 
            lat = float(lat)
            lon = float(lon)

            # --- DYNAMISCHER RADIUS CHECK ---
            dist = calculate_distance(center_lat, center_lon, lat, lon)
            if dist > max_radius: continue

            # Kategorie Display
            cat_display = meta.get("type", "Attraction")
            if "museum" in lower_name or "heimathaus" in lower_name: cat_display = "Museum"
            elif "gasthof" in lower_name or "restaurant" in lower_name: cat_display = "Restaurant"

            activity_item = {
                "name": name,
                "category": cat_display,
                "city": meta.get("city", location),
                "description": node.get_text()[:150] + "...",
                "lat": lat,
                "lon": lon,
                "source": meta.get("source", "unknown")
            }
            
            if any(a['name'] == activity_item['name'] for a in activities_list): continue
            activities_list.append(activity_item)
            if len(activities_list) >= 5: break
        
        result = {
            "type": "activity_list",
            "location": location,
            "items": activities_list
        }
        return json.dumps(result)

    except Exception as e:
        sys.stderr.write(f"[ERROR] DB-Fehler in plan_activities: {e}\n")
        return json.dumps({"error": str(e)})
    
def plan_complete_trip_logic(start: str, end: str, interest: str, num_stops: int = 2) -> str:
    sys.stderr.write(f"[LOGIC] Plane Rundreise: {start} -> {end} ({interest}) -> {start}\n")
    
    start_lat, start_lon = get_coords(start)
    if not start_lat:
         return json.dumps({"type": "error", "message": f"Startort {start} nicht gefunden."})
    start_coords = (start_lat, start_lon)

    # --- SCHRITT 1: INTERESSEN ANALYSE ---
    interests_to_search = []
    lower_int = interest.lower()
    
    # Prüfen auf die "Museum & Food" Kombi
    wants_museum = "museum" in lower_int or "kultur" in lower_int
    wants_food = "food" in lower_int or "essen" in lower_int or "restaurant" in lower_int
    
    if wants_museum and wants_food:
        # JA, das ist die Spezial-Kombi -> Split!
        interests_to_search.append("Museum Geschichte Kultur")
        interests_to_search.append("Gasthof Restaurant Essen")
    else:
        # NEIN, normale Suche (z.B. "Wandern", "Aussicht", "Action")
        # Wir suchen einfach 2x nach dem Thema, um verschiedene Treffer zu kriegen
        interests_to_search = [interest, interest]

    # --- SCHRITT 2: AKTIVITÄTEN SAMMELN ---
    stops = []
    seen_names = set()
    
    for sub_interest in interests_to_search:
        act_json = plan_activities_logic(location=end, interest=sub_interest)
        act_data = json.loads(act_json)
        
        if "items" in act_data:
            for item in act_data["items"]:
                if item["name"] not in seen_names:
                    stops.append(item)
                    seen_names.add(item["name"])
                    break # Top 1 pro Runde
        
        if len(stops) >= num_stops: break

    intro_msg = f"Ich habe einen Ausflug von {start} nach {end} mit {len(stops)} Stopps geplant:"
    if not stops:
        intro_msg = f"Keine passenden Aktivitäten in {end} gefunden. Hier ist die reine Fahrt:"

    # --- SCHRITT 3: ROUTING (Identisch wie zuvor) ---
    steps = []
    current_coords = start_coords
    current_name = start
    
    for i, stop in enumerate(stops):
        stop_name = stop["name"]
        stop_coords = (stop["lat"], stop["lon"])
        label = f"Fahrt zu: {stop['category']} ({stop_name})"
        
        trip_json = plan_journey_logic(
            start=current_name, end=stop_name, time_str="tomorrow 09:00",
            start_coords_override=current_coords, end_coords_override=stop_coords
        )
        trip_data = json.loads(trip_json)
        
        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data, "label": label })
        else:
            steps.append({ "type": "error", "message": f"Kein Weg nach {stop_name}" })

        steps.append({ "type": "activity", "data": stop })
        current_coords = stop_coords
        current_name = stop_name

    final_trip_json = plan_journey_logic(
        start=current_name, end=start, time_str="tomorrow 16:00",
        start_coords_override=current_coords, end_coords_override=start_coords
    )
    final_trip_data = json.loads(final_trip_json)
    
    if "legs" in final_trip_data:
         steps.append({ "type": "trip", "data": final_trip_data, "label": "Heimreise" })
    else:
         steps.append({ "type": "error", "message": "Keine Rückverbindung gefunden." })

    result = {
        "type": "multi_step_plan",
        "intro": intro_msg,
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
    # Fallback, falls DB nicht läuft
    if not activity_retriever:
        return "Oberstdorf" 
        
    sys.stderr.write(f"[LOGIC] Suche beste Stadt für: {query}\n")
    
    # Retrieve statt Query
    nodes = activity_retriever.retrieve(f"Best location for {query}")
    
    cities = []
    for node_with_score in nodes:
        node = node_with_score.node
        city = node.metadata.get("city")
        if city:
            cities.append(city)
            
    if not cities:
        return "Sonthofen"
        
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