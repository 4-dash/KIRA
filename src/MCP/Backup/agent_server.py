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
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
# 1. KONFIGURATION LADEN
load_dotenv()

# --- DEINE ORIGINALE KONFIGURATION (UNVERÄNDERT) ---
OTP_URL = "http://localhost:8080/otp/routers/default/index/graphql"
OPENSEARCH_HOST = {'host': 'localhost', 'port': 9200}
INDEX_NAME = "tourism-data-v7"
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
INDEX_NAME = os.getenv("POI_INDEX", "tourism-data-v7")

# --- ACTIVITY ENGINE SETUP ---
activity_retriever = None 
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_EMBED_ENDPOINT = os.getenv("AZURE_EMBED_ENDPOINT")
# Fallback auf den Modellnamen, falls Variable leer ist
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME_EMBED", "text-embedding-3-large") 
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION_EMBED", "2024-02-01")
EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))

try:
    sys.stderr.write(f"[SERVER] Setup Embeddings: Endpoint='{AZURE_EMBED_ENDPOINT}', Deployment='{AZURE_DEPLOYMENT_NAME}'\n")
    
    # 1. Embedding Modell laden
    embed_model = AzureOpenAIEmbedding(
        model="text-embedding-3-large",
        deployment_name=AZURE_DEPLOYMENT_NAME,
        api_key=AZURE_OPENAI_KEY,
        azure_endpoint=AZURE_EMBED_ENDPOINT,
        api_version=AZURE_API_VERSION,
    )
    Settings.embed_model = embed_model
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
        dim=EMBED_DIM,
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

def encode_polyline(points):
    """
    Wandelt eine Liste von [lat, lon] Punkten in einen Google Polyline String um.
    Das braucht das Frontend, um Linien zu zeichnen (genau wie bei OTP).
    """
    result = []
    last_lat = 0
    last_lon = 0

    for point in points:
        # Auf 5 Nachkommastellen runden & in Integer wandeln
        lat = int(round(point[0] * 1e5))
        lon = int(round(point[1] * 1e5))

        d_lat = lat - last_lat
        d_lon = lon - last_lon

        _encode_value(d_lat, result)
        _encode_value(d_lon, result)

        last_lat = lat
        last_lon = lon

    return "".join(result)

def _encode_value(value, result):
    value = ~(value << 1) if value < 0 else (value << 1)
    while value >= 0x20:
        result.append(chr((0x20 | (value & 0x1f)) + 63))
        value >>= 5
    result.append(chr(value + 63))

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
    # UPDATE: "Ultra-Lazy-Mode"
    # Wir erlauben weite Wege zur Haltestelle (5km), damit er das Naturschutzgebiet erreicht.
    # ABER: Wir setzen walkReluctance auf 500! Das ist astronomisch hoch.
    # Das zwingt den Router, jeden Meter Fußweg zu vermeiden, wenn IRGENDWIE ein Bus fährt.
    
    query = """
    query PlanTrip($fromLat: Float!, $fromLon: Float!, $toLat: Float!, $toLon: Float!, $date: String!, $time: String!) {
      plan(
        from: {lat: $fromLat, lon: $fromLon}
        to: {lat: $toLat, lon: $toLon}
        date: $date
        time: $time
        numItineraries: 3
        transportModes: [{mode: TRANSIT}, {mode: WALK}]
        walkReluctance: 500.0    # <--- EXTREM! Laufen ist der absolute Feind.
        waitReluctance: 0.1      # <--- Warten ist okay.
        maxWalkDistance: 5000.0  # <--- Radius groß genug für abgelegene Ziele.
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
            intermediateStops { name lat lon }
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
    
    # --- DYNAMISCHE RADIUS KONFIGURATION ---
    max_radius = 15.0 
    lower_interest = interest.lower()
    
    if "museum" in lower_interest:
        search_query = f"Museum Ausstellung Geschichte Kultur in {location}"
        max_radius = 3.0 
    elif "food" in lower_interest or "essen" in lower_interest or "restaurant" in lower_interest:
         search_query = f"Restaurant Gasthof Essen Traditionelle Küche in {location}"
         max_radius = 3.0

    try:
        sys.stderr.write(f"[LOGIC] Suche Activities: '{search_query}' (Radius {max_radius}km)\n")
        nodes = activity_retriever.retrieve(search_query)
        
        activities_list = []
        
        for node_with_score in nodes:
            node = node_with_score.node
            meta = node.metadata
            name = meta.get("name", "Unbekannt")
            
            # 1. Koordinaten (Punkt)
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

            # Radius Check
            dist = calculate_distance(center_lat, center_lon, lat, lon)
            if dist > max_radius: continue

           # --- 🔥 GEOMETRIE PARSEN & ENCODEN 🔥 ---
            encoded_geometry = None
            geometry_points = []
            
            if "geo_line" in meta:
                raw_geo = meta["geo_line"]
                try:
                    if isinstance(raw_geo, str):
                        raw_geo = json.loads(raw_geo.replace("'", '"'))
                    
                    coords_source = []
                    geo_type = raw_geo.get("type")
                    
                    if geo_type == "LineString":
                        coords_source = raw_geo["coordinates"]
                    elif geo_type == "MultiLineString":
                        for segment in raw_geo["coordinates"]:
                            coords_source.extend(segment)
                            
                    # Umwandlung [Lon, Lat] -> [Lat, Lon]
                    for p in coords_source:
                        if isinstance(p, list) and len(p) >= 2:
                            # Ignoriere 3. Wert (Höhe), falls vorhanden
                            geometry_points.append([p[1], p[0]])
                    
                    # JETZT WIRD ENCODIERT!
                    if geometry_points:
                        encoded_geometry = encode_polyline(geometry_points)

                except Exception as e:
                    sys.stderr.write(f"[WARN] Geometrie-Fehler bei {name}: {e}\n")

            # ---------------------------------------------------------

            cat_display = meta.get("type", "Attraction")
            if "museum" in name.lower() or "heimathaus" in name.lower(): cat_display = "Museum"
            elif "gasthof" in name.lower() or "restaurant" in name.lower(): cat_display = "Restaurant"

            activity_item = {
                "name": name,
                "category": cat_display,
                "city": meta.get("city", location),
                "description": node.get_text()[:150] + "...",
                "lat": lat,
                "lon": lon,
                "source": meta.get("source", "unknown"),
                "geometry": encoded_geometry # <--- Jetzt als String!
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

    except Exception as e:
        sys.stderr.write(f"[ERROR] DB-Fehler in plan_activities: {e}\n")
        return json.dumps({"error": str(e)})
    
def plan_complete_trip_logic(start: str, end: str, interest: str, num_stops: int = 2) -> str:
    sys.stderr.write(f"[LOGIC] Plane Rundreise: {start} -> {end} ({interest}) -> {start}\n")
    
    start_lat, start_lon = get_coords(start)
    if not start_lat:
         return json.dumps({"type": "error", "message": f"Startort {start} nicht gefunden."})
    start_coords = (start_lat, start_lon)

    # --- SCHRITT 1: INTERESSEN & SPLIT ---
    interests_to_search = []
    lower_int = interest.lower()
    
    wants_museum = "museum" in lower_int or "kultur" in lower_int
    wants_food = "food" in lower_int or "essen" in lower_int or "restaurant" in lower_int
    
    if wants_museum and wants_food:
        interests_to_search.append("Museum Geschichte Kultur")
        interests_to_search.append("Gasthof Restaurant Essen")
    else:
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
                    break 
        
        if len(stops) >= num_stops: break

    intro_msg = f"Ich habe einen Ausflug von {start} nach {end} mit {len(stops)} Stopps geplant:"
    if not stops:
        intro_msg = f"Keine passenden Aktivitäten in {end} gefunden. Hier ist die reine Fahrt:"

    # --- SCHRITT 3: ROUTING MIT ZEIT-MANAGEMENT 🕒 ---
    steps = []
    current_coords = start_coords
    current_name = start
    
    # Wir starten morgen um 09:00 Uhr
    current_time_obj = datetime.now() + timedelta(days=1)
    current_time_obj = current_time_obj.replace(hour=9, minute=0, second=0)
    
    for i, stop in enumerate(stops):
        stop_name = stop["name"]
        stop_coords = (stop["lat"], stop["lon"])
        label = f"Anreise zu: {stop['category']} ({stop_name})"
        
        # Dynamischen Zeit-String bauen
        time_str_dynamic = f"tomorrow {current_time_obj.strftime('%H:%M')}"
        
        # 1. ECHTE ANREISE (Bus/Bahn)
        trip_json = plan_journey_logic(
            start=current_name, end=stop_name, time_str=time_str_dynamic,
            start_coords_override=current_coords, end_coords_override=stop_coords
        )
        trip_data = json.loads(trip_json)
        
        trip_duration_minutes = 30 # Fallback
        
        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data, "label": label })
            trip_duration_minutes = trip_data.get("total_duration", 30)
        else:
            steps.append({ "type": "error", "message": f"Kein Weg nach {stop_name}" })

        # ZEIT UPDATE: Ankunft am Startpunkt der Wanderung
        current_time_obj += timedelta(minutes=trip_duration_minutes)

        # --- 🔥 NEU: VISUAL TRACKING (Wanderweg als Trip) 🔥 ---
        # Wenn die Aktivität eine Geometrie hat (Wanderweg), erstellen wir einen
        # künstlichen "Trip", damit die Karte die Linie zeichnet!
        if stop.get("geometry"):
            track_label = f"Route: {stop['name']}"
            
            # Wir simulieren eine 2-stündige Wanderung entlang des Pfades
            hike_duration = 120 
            
            visual_trip = {
                "start": stop["name"],
                "end": stop["name"], # Rundweg
                "date": current_time_obj.strftime("%d.%m.%Y"),
                "total_duration": hike_duration,
                "legs": [{
                    "mode": "WALK",
                    "from": stop["name"], # Start
                    "to": stop["name"],   # Ziel
                    "from_coords": [stop["lat"], stop["lon"]],
                    "to_coords": [stop["lat"], stop["lon"]],
                    "start_time": current_time_obj.strftime('%H:%M'),
                    "end_time": (current_time_obj + timedelta(minutes=hike_duration)).strftime('%H:%M'),
                    "line": "Wanderweg",
                    "duration": hike_duration,
                    "geometry": stop["geometry"] # <--- HIER IST DER MAGISCHE TRACK!
                }]
            }
            # Diesen "Wander-Trip" fügen wir VOR der Aktivitäts-Karte ein
            steps.append({ "type": "trip", "data": visual_trip, "label": track_label })
            
            # Zeit für die Wanderung draufrechnen
            current_time_obj += timedelta(minutes=hike_duration)
        # -------------------------------------------------------
        else:
            # Falls kein Track da ist, pauschal 90 Min Aufenthalt
            current_time_obj += timedelta(minutes=90)

        # 2. AKTIVITÄTS-KARTE
        steps.append({ "type": "activity", "data": stop })
        
        current_coords = stop_coords
        current_name = stop_name

    # Rückreise
    time_str_return = f"tomorrow {current_time_obj.strftime('%H:%M')}"
    
    final_trip_json = plan_journey_logic(
        start=current_name, end=start, time_str=time_str_return,
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
    if days < 1: days = 1
    
    sys.stderr.write(f"[LOGIC] Plane Trip für {days} Tage nach {end} (Basis-Strategie: Zentral)\n")
    
    # 1. Start-Koordinaten
    start_lat, start_lon = get_coords(start)
    start_coords = (start_lat, start_lon) if start_lat else None
    
    end_lat, end_lon = get_coords(end)
    if not end_lat:
         return json.dumps({"type": "error", "message": f"Zielort {end} nicht gefunden."})

    # 2. HOTEL-SUCHE MIT FALLBACK 🏨
    # Strategie: Wir suchen ein Hotel < 2.5 km vom Zentrum.
    # Wenn keines da ist (z.B. Sonthofen DB leer), nutzen wir das ZENTRUM als Basis.
    
    sys.stderr.write(f"[LOGIC] Suche Hotel in {end}...\n")
    hotels_json = plan_activities_logic(end, "Hotel Unterkunft Central")
    hotels_data = json.loads(hotels_json)
    
    hotel = None
    if "items" in hotels_data:
        for h in hotels_data["items"]:
            dist = calculate_distance(end_lat, end_lon, h["lat"], h["lon"])
            if dist <= 2.5: 
                hotel = h
                break
    
    if hotel:
        base_name = hotel["name"]
        base_coords = (hotel["lat"], hotel["lon"])
        intro_text = f"Ich habe eine Reise nach {end} geplant. Deine Basis ist das **{base_name}**."
    else:
        # 🔥 FALLBACK: KEIN HOTEL GEFUNDEN -> STADT-ZENTRUM NUTZEN 🔥
        base_name = f"{end} Zentrum"
        base_coords = (end_lat, end_lon)
        intro_text = f"Ich habe eine Reise nach {end} geplant. Da ich kein zentrales Hotel in der Datenbank gefunden habe, starten wir vom Zentrum."
        sys.stderr.write(f"[WARN] Kein Hotel gefunden. Nutze Koordinaten von {end} als Basis.\n")

    # 3. POOLS FÜLLEN
    museums = json.loads(plan_activities_logic(end, "Museum"))
    food = json.loads(plan_activities_logic(end, "Restaurant Gaststätte"))
    leisure = json.loads(plan_activities_logic(end, "Wandern Natur Freizeit"))
    
    pool_museums = museums.get("items", [])
    pool_food = food.get("items", [])
    pool_leisure = leisure.get("items", [])
    
    steps = []
    
    def get_item(pool):
        return pool.pop(0) if pool else None

    # --- HELPER: ROUTE ---
    def add_route(origin_name, origin_coords, dest_name, dest_coords, time_str, label="Fahrt"):
        if not origin_name or not dest_name: return
        
        # Check: Sind wir schon da?
        dist = calculate_distance(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1])
        if dist < 0.2: return

        trip_json = plan_journey_logic(
            start=origin_name, end=dest_name, time_str=time_str,
            start_coords_override=origin_coords, end_coords_override=dest_coords      
        )
        trip_data = json.loads(trip_json)
        
        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data, "label": label })
        else:
            steps.append({ "type": "error", "message": f"Kein Weg von {origin_name} nach {dest_name}" })

    # --- HELPER: WANDERUNG ---
    def add_visual_tracking(activity):
        if activity.get("geometry"):
             visual_trip = {
                "start": activity["name"], "end": activity["name"], "date": "Wandertag",
                "total_duration": 120,
                "legs": [{
                    "mode": "WALK", "from": activity["name"], "to": activity["name"],
                    "from_coords": [activity["lat"], activity["lon"]],
                    "to_coords": [activity["lat"], activity["lon"]],
                    "start_time": "10:30", "end_time": "12:30",
                    "line": "Wanderweg", "duration": 120, "geometry": activity["geometry"]
                }]
            }
             steps.append({ "type": "trip", "data": visual_trip, "label": f"Route: {activity['name']}" })

    # Start-Zustand
    curr_name = start
    curr_coords = start_coords

    # === TAG 1 ===
    steps.append({ "type": "header", "title": "📅 Tag 1: Anreise & Start" })
    
    # 1. Anreise Basis
    add_route(curr_name, curr_coords, base_name, base_coords, "tomorrow 11:00", f"Anreise nach {end}")
    
    if hotel: steps.append({ "type": "activity", "data": hotel })
    
    curr_name = base_name
    curr_coords = base_coords
    
    # 2. Nachmittag
    act1 = get_item(pool_leisure) or get_item(pool_museums)
    if act1:
        act1_coords = (act1["lat"], act1["lon"])
        add_route(curr_name, curr_coords, act1["name"], act1_coords, "tomorrow 14:30", "Erster Ausflug")
        add_visual_tracking(act1)
        steps.append({ "type": "activity", "data": act1 })
        curr_name = act1["name"]
        curr_coords = act1_coords

    # 3. Abendessen & RÜCKWEG
    dinner1 = get_item(pool_food)
    if dinner1:
        dinner_coords = (dinner1["lat"], dinner1["lon"])
        add_route(curr_name, curr_coords, dinner1["name"], dinner_coords, "tomorrow 18:30", "Zum Abendessen")
        steps.append({ "type": "activity", "data": dinner1 })
        
        # 🔥 ZWINGENDER RÜCKWEG 🔥
        add_route(dinner1["name"], dinner_coords, base_name, base_coords, "tomorrow 20:30", "Zurück zur Unterkunft")
    else:
        # Kein Restaurant gefunden? Dann direkt zurück zur Basis (falls wir nicht schon da sind)
        add_route(curr_name, curr_coords, base_name, base_coords, "tomorrow 19:00", "Zurück zur Unterkunft")

    # === TAGE 2 bis N ===
    for i in range(2, days):
        steps.append({ "type": "header", "title": f"📅 Tag {i}: Entdeckungstour" })
        
        # Morgens immer von der Basis starten
        curr_name = base_name
        curr_coords = base_coords
        
        # Vormittag
        act_am = get_item(pool_leisure)
        if act_am:
            act_am_coords = (act_am["lat"], act_am["lon"])
            add_route(curr_name, curr_coords, act_am["name"], act_am_coords, "tomorrow 09:30", "Ausflug am Morgen")
            add_visual_tracking(act_am)
            steps.append({ "type": "activity", "data": act_am })
            curr_name = act_am["name"]
            curr_coords = act_am_coords
        
        # Nachmittag
        act_pm = get_item(pool_museums)
        if act_pm:
            act_pm_coords = (act_pm["lat"], act_pm["lon"])
            add_route(curr_name, curr_coords, act_pm["name"], act_pm_coords, "tomorrow 14:00", "Kultur am Nachmittag")
            steps.append({ "type": "activity", "data": act_pm })
            curr_name = act_pm["name"]
            curr_coords = act_pm_coords
        
        # Abendessen & RÜCKWEG
        act_eve = get_item(pool_food)
        if act_eve:
            act_eve_coords = (act_eve["lat"], act_eve["lon"])
            add_route(curr_name, curr_coords, act_eve["name"], act_eve_coords, "tomorrow 19:00", "Abendessen")
            steps.append({ "type": "activity", "data": act_eve })
            
            # 🔥 ZWINGENDER RÜCKWEG 🔥
            add_route(act_eve["name"], act_eve_coords, base_name, base_coords, "tomorrow 21:00", "Zurück zur Unterkunft")
        else:
             add_route(curr_name, curr_coords, base_name, base_coords, "tomorrow 20:00", "Zurück zur Unterkunft")

    # === LETZTER TAG ===
    steps.append({ "type": "header", "title": f"📅 Tag {days}: Heimreise" })
    
    curr_name = base_name
    curr_coords = base_coords
    
    last_act = get_item(pool_leisure) or get_item(pool_museums)
    if last_act:
        last_coords = (last_act["lat"], last_act["lon"])
        add_route(curr_name, curr_coords, last_act["name"], last_coords, "tomorrow 10:00", "Letzter Ausflug")
        add_visual_tracking(last_act)
        steps.append({ "type": "activity", "data": last_act })
        curr_name = last_act["name"]
        curr_coords = last_coords
    
    # Heimreise
    add_route(curr_name, curr_coords, start, start_coords, "tomorrow 15:00", "Heimreise")

    result = {
        "type": "multi_step_plan",
        "intro": intro_text,
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