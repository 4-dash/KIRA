import time
from typing import List, Optional, Literal,Union
from pydantic import BaseModel, Field
from opensearchpy import OpenSearch
from datetime import datetime, date
from uuid import UUID, uuid4

class Location(BaseModel):
    name:str
    latitude:float
    longitude:float
    address:Optional[str] = None

class Leg(BaseModel):
    id:UUID = Field(default_factory=uuid4)
    type:Literal["leg"] = "leg" 
    transport_mode:str #transportation mode : Bus, Tram etc.
    start_location:Location
    end_location:Location
    departure_time:datetime
    arrival_time:datetime
    duration_min:int 
    carrier_number:Optional[str] = None # e.g. Number of tram 9, Flight LH402, Bus F etc.

class Activity(BaseModel):
    id:UUID = Field(default_factory=uuid4)
    type:Literal["activity"]="activity"
    name:str
    description:Optional[str] = None
    location:Location
    start_time:datetime
    end_time:datetime
    duration_min:int
    cost:Optional[float] = 0.0

class Day(BaseModel):
    date:date
    itinerary:List[Union[Activity, Leg]] = []  # mix of legs and activities
    notes:Optional[str] = None 

class Trip(BaseModel):
    trip_id:UUID = Field(default_factory=uuid4)
    version:int = 1
    name:str
    start_date:date
    end_date:date
    travelers:int = 1
    days:List[Day] = []
    created:datetime = Field(default_factory=datetime.now)

    class Config : 
        use_enum_values = True


loc_home = Location(name="Home", latitude=49.8728, longitude=8.6512, address="Darmstadt")
loc_station_da = Location(name="Darmstadt Hbf", latitude=49.8724, longitude=8.6296)
loc_station_ffm = Location(name="Frankfurt Hbf", latitude=50.1071, longitude=8.6638)
loc_restaurant = Location(name="ChiKing", latitude=50.1075, longitude=8.6692, address="ElbeStrasse 14")

day1_date = date(2025,12,3)

leg_train = Leg(
    transport_mode="TRAIN",
    start_location=loc_station_da,
    end_location=loc_station_ffm,
    departure_time= datetime(2025, 12, 3, 9, 00),
    arrival_time= datetime(2025, 12, 3, 9, 30),
    duration_min=30,
    carrier_number="RB68"
)

activity_restaurant = Activity(
    name = "Visit ChiKing restaurant",
    description="Eat tasty korean fried chicken at ChiKing restaurant",
    location= loc_restaurant,
    start_time=datetime(2025, 12, 3, 9, 50),
    end_time=datetime(2025, 12, 3, 11, 00),
    duration_min=70,
    cost=15.0
)

my_trip = Trip(
    name = "Eating out in Frankfurt",
    start_date=day1_date,
    end_date=day1_date,
    days=[Day(
        date=day1_date,
        itinerary=[leg_train,activity_restaurant],
        notes="Be careful its spicy!"
    )]
)

client = OpenSearch(
    hosts=[{'host' : 'localhost', 'port' : 9200}],
    use_ssl = False,
    verify_certs= False

)

index_name = "travel-plans"

if not client.indices.exists(index=index_name) :
    client.indices.create(index=index_name)  # Check index and create if missing


trip_json = my_trip.model_dump(mode='json')

doc_id = f"{my_trip.trip_id}_v{my_trip.version}"

response = client.index(
    index =index_name,
    body = trip_json,
    id=doc_id,
    refresh = True

)

print(f"Successfully uploaded: {my_trip.name}")
print(f"Document ID: {doc_id}")
print(f"Result: {response['result']}")
    

