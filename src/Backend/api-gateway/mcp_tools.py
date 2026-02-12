import json
import os
import sys
import requests
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from collections import Counter

# --- LlamaIndex & OpenSearch Imports ---
from llama_index.core import VectorStoreIndex, Settings
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from opensearchpy import OpenSearch, RequestsHttpConnection

def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None:
        return ""
    return v

# ============================================================================
# 1. INITIALIZATION (DB Connections & Embeddings)
# ============================================================================

# Configuration
TRIP_PLANNER_URL = _env("TRIP_PLANNER_URL", "http://trip-planner:8001").rstrip("/")
OPENSEARCH_HOST = _env("OPENSEARCH_HOST", "opensearch")
OPENSEARCH_PORT = int(_env("OPENSEARCH_PORT", "9200"))
INDEX_NAME = _env("POI_INDEX", "tourism-data-v-working") 

activity_engine = None

def init_activity_engine():
    """
    Initializes the LlamaIndex engine for activity search.
    This mimics the setup in Eric's agent_server.py.
    """
    global activity_engine
    if activity_engine:
        return

    try:
        print("[MCP] Loading Embedding Model...")
        
        Settings.embed_model = HuggingFaceEmbedding(model_name="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        Settings.llm = None # We use Azure OpenAI separately for the agent, this is just for vector search

        print(f"[MCP] Connecting to OpenSearch Index '{INDEX_NAME}' at {OPENSEARCH_HOST}...")
        
        # OpenSearch Client
        os_client = OpenSearch(
            hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
            use_ssl=False, 
            verify_certs=False, 
            connection_class=RequestsHttpConnection
        )
        
        # LlamaIndex Wrapper
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
        
        # Create Query Engine (Top 5 results)
        activity_engine = activity_index.as_query_engine(similarity_top_k=5)
        print("[MCP] ✅ Activity Database successfully connected.")

    except Exception as e:
        print(f"[MCP] ⚠️ WARNING: Could not load Activity Database: {e}")

# Initialize on module load (best effort)
init_activity_engine()


# ============================================================================
# 2. CORE LOGIC FUNCTIONS (Transplanted from Eric's agent_server.py)
# ============================================================================

def plan_journey_logic(start: str, end: str, time_str: str = "tomorrow 07:30") -> str:
    """
    Plans a journey using the Trip Planner microservice but formats the result
    specifically for the frontend (matching Eric's logic).
    """
    print(f"[LOGIC] Searching route {start} -> {end} ({time_str})")

    # 1. Parse Date/Time locally to format the request for the microservice
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
        
        # Formats required by trip-planner API
        date_param = trip_time.strftime("%Y-%m-%d")
        time_param = trip_time.strftime("%H:%M")
    except Exception as e:
        return json.dumps({"error": f"Date parse error: {str(e)}"})

    # 2. Call Trip Planner Microservice
    # Optimizer branch uses a separate service for OTP, Eric's used direct GraphQL.
    # We bridge this by calling the service.
    payload = {
        "from_stop": start,
        "to_stop": end,
        "date": date_param,
        "time": time_param
    }

    try:
        r = requests.post(f"{TRIP_PLANNER_URL}/plan-by-stops", json=payload, timeout=60)
        r.raise_for_status()
        data = r.json() # This corresponds to the raw OTP GraphQL response
    except Exception as e:
        return json.dumps({"error": f"Trip planner service error: {str(e)}"})

    # 3. Process JSON (Logic from Eric's agent_server.py)
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

            # Fix "Origin"/"Destination" names
            if from_name == "Origin": from_name = start
            if to_name == "Destination": to_name = end
            
            frontend_data["legs"].append({
                "mode": mode,
                "from": from_name,
                "to": to_name,
                "start_time": start_t,
                "end_time": end_t,
                "line": line_name,
                "duration": int(leg['duration'] / 60)
            })

        return json.dumps(frontend_data, ensure_ascii=False)
    else:
        return json.dumps({"error": "No connection found"}, ensure_ascii=False)


def plan_activities_logic(location: str, interest: str = "") -> str:
    """
    Searches for activities using LlamaIndex vector search.
    """
    if not activity_engine:
        # Attempt lazy re-init
        init_activity_engine()
        if not activity_engine:
            return json.dumps({"error": "Database not connected."})
    
    query = f"{interest} in {location}" if interest else f"Highlights in {location}"
    print(f"[LOGIC] Searching Activities: {query}")

    try:
        # 1. Query LlamaIndex
        response = activity_engine.query(query)
        
        # 2. Extract Data
        activities_list = []
        for node_with_score in response.source_nodes:
            node = node_with_score.node
            meta = node.metadata
            
            activity_item = {
                "name": meta.get("name", "Unbekannter Ort"),
                "category": meta.get("category", "Sehenswürdigkeit"),
                "city": meta.get("city", location),
                "description": node.get_text()[:150] + "...", 
            }
            activities_list.append(activity_item)

        # 3. Return JSON
        result = {
            "type": "activity_list",
            "location": location,
            "items": activities_list
        }
        return json.dumps(result, ensure_ascii=False)

    except Exception as e:
        print(f"[ERROR] {e}")
        return json.dumps({"error": str(e)})


def plan_complete_trip_logic(start: str, end: str, interest: str, num_stops: int = 2) -> str:
    """
    Plans a complete route: Start -> Activity 1 -> Activity 2 -> Destination.
    """
    print(f"[LOGIC] Planning complete trip: {start} -> {interest} -> {end}")
    
    # 1. Find Activities
    activities_json = plan_activities_logic(location=end, interest=interest)
    activities_data = json.loads(activities_json)
    
    if "error" in activities_data or not activities_data.get("items"):
        return json.dumps({"error": "No matching activities found."})

    stops = activities_data["items"][:num_stops]
    
    steps = []
    current_location = start
    
    # 2. Loop through stops
    for stop in stops:
        stop_name = stop["name"]
        
        # Route: Current -> Stop
        trip_json = plan_journey_logic(start=current_location, end=stop_name, time_str="tomorrow 09:00")
        trip_data = json.loads(trip_json)
        
        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data })
        else:
            steps.append({ "type": "error", "message": f"No way found from {current_location} to {stop_name}" })

        # Activity
        steps.append({ "type": "activity", "data": stop })
        
        current_location = stop_name

    # 3. Final leg: Last Stop -> End
    final_trip_json = plan_journey_logic(start=current_location, end=end, time_str="tomorrow 16:00")
    final_trip_data = json.loads(final_trip_json)
    if "legs" in final_trip_data:
         steps.append({ "type": "trip", "data": final_trip_data })

    result = {
        "type": "multi_step_plan",
        "intro": f"I planned a route from {start} to {end} with {len(stops)} stops ({interest}):",
        "steps": steps
    }
    
    return json.dumps(result, ensure_ascii=False)


def plan_multiday_trip_logic(start: str, end: str, days: int = 4) -> str:
    """
    Plans a multi-day trip with routes between activities (Chaining).
    """
    if days < 1: days = 1
    
    print(f"[LOGIC] Planning {days}-day trip: {start} -> {end}")
    
    # 1. Fill Pools
    museums = json.loads(plan_activities_logic(end, "Museum"))
    food = json.loads(plan_activities_logic(end, "Restaurant Gaststätte"))
    leisure = json.loads(plan_activities_logic(end, "Wandern Natur Freizeit"))
    
    pool_museums = museums.get("items", [])
    pool_food = food.get("items", [])
    pool_leisure = leisure.get("items", [])
    
    steps = []
    
    def get_item(pool):
        return pool.pop(0) if pool else None

    def add_route(origin, destination, time_str, label="Fahrt"):
        if not origin or not destination: return
        trip_json = plan_journey_logic(origin, destination, time_str)
        trip_data = json.loads(trip_json)
        
        if "legs" in trip_data:
            steps.append({ "type": "trip", "data": trip_data, "label": label })
        else:
            steps.append({ 
                "type": "error", 
                "message": f"Kein Weg gefunden von {origin} nach {destination}" 
            })

    base_location = end 
    current_loc = start 

    # --- Day 1 ---
    steps.append({ "type": "header", "title": "📅 Tag 1: Anreise & Erstes Erkunden" })
    
    add_route(current_loc, base_location, "tomorrow 10:00", "Anreise")
    current_loc = base_location 
    
    act1 = get_item(pool_museums) or get_item(pool_leisure)
    if act1:
        add_route(current_loc, act1["name"], "tomorrow 14:00")
        steps.append({ "type": "activity", "data": act1 })
        current_loc = act1["name"]
        
    dinner = get_item(pool_food)
    if dinner:
        add_route(current_loc, dinner["name"], "tomorrow 18:00")
        steps.append({ "type": "activity", "data": dinner })

    # --- Days 2...N-1 ---
    for i in range(2, days):
        steps.append({ "type": "header", "title": f"📅 Tag {i}: Entdeckungstour" })
        current_loc = base_location 
        
        act_am = get_item(pool_leisure)
        if act_am:
            add_route(current_loc, act_am["name"], "tomorrow 10:00")
            steps.append({ "type": "activity", "data": act_am })
            current_loc = act_am["name"]
        
        act_pm = get_item(pool_museums)
        if act_pm:
            add_route(current_loc, act_pm["name"], "tomorrow 14:00")
            steps.append({ "type": "activity", "data": act_pm })
            current_loc = act_pm["name"]
        
        act_eve = get_item(pool_food)
        if act_eve:
            add_route(current_loc, act_eve["name"], "tomorrow 19:00")
            steps.append({ "type": "activity", "data": act_eve })

    # --- Last Day ---
    steps.append({ "type": "header", "title": f"📅 Tag {days}: Abschied & Heimreise" })
    current_loc = base_location
    
    last_act = get_item(pool_leisure)
    if last_act:
        add_route(current_loc, last_act["name"], "tomorrow 10:00")
        steps.append({ "type": "activity", "data": last_act })
    
    add_route(base_location, start, "tomorrow 16:00", "Rückreise")

    result = {
        "type": "multi_step_plan",
        "intro": f"Ich habe die komplette Route für {days} Tage inkl. aller Wege berechnet:",
        "steps": steps
    }
    
    return json.dumps(result, ensure_ascii=False)


def find_best_city_logic(query: str) -> str:
    """
    Finds the best matching city in Allgäu for specific interests.
    """
    if not activity_engine:
        return "Oberstdorf" 
        
    print(f"[LOGIC] Finding best city for: {query}")
    
    response = activity_engine.query(f"Best location for {query}")
    
    cities = []
    for node in response.source_nodes:
        city = node.metadata.get("city")
        if city:
            cities.append(city)
            
    if not cities:
        return "Sonthofen"
        
    most_common = Counter(cities).most_common(1)
    return most_common[0][0]