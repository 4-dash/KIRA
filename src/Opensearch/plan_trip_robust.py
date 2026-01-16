import requests
import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Literal, Union
from pydantic import BaseModel, Field, ConfigDict
from opensearchpy import OpenSearch
from uuid import UUID, uuid4

# --- CONFIGURATION ---
OTP_URL = "http://localhost:8080/otp/routers/default/index/graphql"
OPENSEARCH_HOST = {'host': 'localhost', 'port': 9200}
INDEX_NAME = "travel-plans"

# TARGET STOPS (Start und Ziel)
START_NAME = "Fischen"
END_NAME = "Sonthofen"

# --- DATA MODELS (Pydantic) ---
class Location(BaseModel):
    name: str
    latitude: float
    longitude: float
    address: Optional[str] = None

class Leg(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: Literal["leg"] = "leg" 
    transport_mode: str 
    start_location: Location
    end_location: Location
    departure_time: datetime
    arrival_time: datetime
    duration_min: int 
    carrier_number: Optional[str] = None 

class Activity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: Literal["activity"] = "activity"
    name: str
    description: Optional[str] = None
    location: Location
    start_time: datetime
    end_time: datetime
    duration_min: int
    cost: Optional[float] = 0.0

class Day(BaseModel):
    date: datetime 
    itinerary: List[Union[Activity, Leg]] = [] 
    notes: Optional[str] = None 

class Trip(BaseModel):
    trip_id: UUID = Field(default_factory=uuid4)
    version: int = 1
    name: str
    start_date: datetime
    end_date: datetime
    travelers: int = 1
    days: List[Day] = []
    created: datetime = Field(default_factory=datetime.now)
    model_config = ConfigDict(use_enum_values=True)

# --- HELPER: ROBUST COORDINATE FINDER ---
def get_coords_robust(target_name):
    query = """
    {
      stops {
        name
        lat
        lon
      }
    }
    """
    try:
        response = requests.post(OTP_URL, json={"query": query})
        if response.status_code != 200:
            print(f"❌ Server Error: {response.status_code}")
            return None, None
            
        data = response.json()
        if 'data' in data and 'stops' in data['data']:
            all_stops = data['data']['stops']
            for stop in all_stops:
                # Exakter Vergleich
                if stop['name'] == target_name:
                    print(f"📍 Gefunden: {stop['name']} ({stop['lat']}, {stop['lon']})")
                    return stop['lat'], stop['lon']
            
            print(f"❌ Haltestelle '{target_name}' nicht gefunden.")
            return None, None
        else:
            return None, None

    except Exception as e:
        print(f"❌ Python Error: {e}")
        return None, None

# --- CORE: TRIP PLANNER (OTP 2.8 COMPATIBLE) ---
def get_otp_route(from_lat, from_lon, to_lat, to_lon, departure_time):
    # UPDATE: 'routeShortName' durch 'route { shortName }' ersetzt für OTP 2.8+
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
          legs {
            mode
            startTime
            endTime
            duration
            # Nested Object for OTP 2.8
            route {
                shortName
                longName
            }
            from { name lat lon }
            to { name lat lon }
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

    print(f"📡 Sende Anfrage an OTP für {variables['date']} um {variables['time']}...")
    response = requests.post(OTP_URL, json={"query": query, "variables": variables})
    
    data = response.json()
    
    # 1. Error Checking
    if 'errors' in data:
        print("\n⚠️  SERVER FEHLER (GraphQL):")
        for err in data['errors']:
            print(f"   - {err.get('message')}")
        return None

    # 2. Parse Result
    if data.get('data') and data['data'].get('plan'):
        itineraries = data['data']['plan'].get('itineraries')
        
        if not itineraries:
            print("\n⚠️  KEINE ROUTE GEFUNDEN.")
            print("   Mögliche Gründe: Kein Fahrplan für dieses Datum oder Haltestelle zu weit von Straße.")
            return None
            
        # Wir nehmen die erste vorgeschlagene Route
        itinerary = itineraries[0]
        
        for leg_data in itinerary['legs']:
            # Wir suchen das Hauptverkehrsmittel (Zug, Bus, etc.)
            if leg_data['mode'] in ['BUS', 'RAIL', 'TRAM', 'SUBWAY', 'TRAIN']:
                
                # UPDATE: Daten sicher extrahieren
                route_info = leg_data.get('route') or {}
                carrier = route_info.get('shortName') or route_info.get('longName') or 'Unknown'

                return Leg(
                    transport_mode=leg_data['mode'],
                    start_location=Location(name=leg_data['from']['name'], latitude=leg_data['from']['lat'], longitude=leg_data['from']['lon']),
                    end_location=Location(name=leg_data['to']['name'], latitude=leg_data['to']['lat'], longitude=leg_data['to']['lon']),
                    departure_time=datetime.fromtimestamp(leg_data['startTime'] / 1000),
                    arrival_time=datetime.fromtimestamp(leg_data['endTime'] / 1000),
                    duration_min=int(leg_data['duration'] / 60),
                    carrier_number=carrier
                )
    return None

# --- MAIN EXECUTION ---
if __name__ == "__main__":
    print(f"--- Starte Finale Reiseplanung (OTP 2.8) ---")
    print(f"📍 Start: {START_NAME}")
    print(f"📍 Ziel:  {END_NAME}")

    # 1. Koordinaten holen
    start_lat, start_lon = get_coords_robust(START_NAME)
    end_lat, end_lon = get_coords_robust(END_NAME)

    if start_lat and end_lat:
        # 2. DATUM: Morgen früh 07:30 Uhr (Sicherer Testzeitpunkt)
        tomorrow = datetime.now() + timedelta(days=1)
        trip_time = tomorrow.replace(hour=7, minute=30, second=0, microsecond=0)
        
        # 3. Route berechnen
        real_leg = get_otp_route(start_lat, start_lon, end_lat, end_lon, trip_time)

        if real_leg:
            print(f"\n✅ ERFOLG: Verbindung gefunden!")
            print(f"   Modus:   {real_leg.transport_mode} {real_leg.carrier_number}")
            print(f"   Dauer:   {real_leg.duration_min} Min")
            print(f"   Abfahrt: {real_leg.departure_time}")
            print(f"   Ankunft: {real_leg.arrival_time}")
            
            # 4. In OpenSearch speichern
            try:
                client = OpenSearch(hosts=[OPENSEARCH_HOST], use_ssl=False, verify_certs=False)
                # Check connection without crashing if failed
                if not client.ping():
                    print("\n⚠️  OpenSearch nicht erreichbar. Daten werden NICHT gespeichert.")
                else:
                    if not client.indices.exists(index=INDEX_NAME):
                        client.indices.create(index=INDEX_NAME)
                        
                    my_trip = Trip(
                        name=f"Schulweg: {START_NAME} -> {END_NAME}",
                        start_date=trip_time,
                        end_date=trip_time,
                        days=[Day(date=trip_time, itinerary=[real_leg], notes="Generated by KIRA")]
                    )
                    
                    trip_json = my_trip.model_dump(mode='json')
                    doc_id = f"{my_trip.trip_id}_v{my_trip.version}"
                    client.index(index=INDEX_NAME, body=trip_json, id=doc_id, refresh=True)
                    print(f"🚀 Erfolgreich gespeichert in OpenSearch! ID: {doc_id}")
            except Exception as e:
                print(f"\n⚠️  Fehler beim Speichern in OpenSearch: {e}")
                print("   (Die Route wurde aber trotzdem korrekt berechnet!)")

        else:
            print("\n❌ Leider keine Route gefunden. Prüfe, ob Züge zu dieser Uhrzeit fahren.")
    else:
        print("❌ Koordinaten konnten nicht ermittelt werden.")