import uuid
from typing import Literal, Optional
from pydantic import BaseModel, Field
from opensearchpy import OpenSearch

class Location(BaseModel):
    name:str
    latitude:float
    longitude:float
    address:Optional[str] = None

class PointOfInterest(BaseModel):
    id:str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["sight","restaurant","museum","park"]
    name:str
    location:Location
    tags:list[str] = []

class ParkingFacilities(BaseModel):
    id:str = Field(default_factory=lambda: str(uuid.uuid4()))
    type:Literal["parking_garage","park_and_ride","street_parking"]
    name:str
    capacity:int
    location:Location
    fee_per_hour:Optional[float]=0.0


client = OpenSearch(
    hosts=[{'host' : 'localhost', 'port' : 9200}],
    use_ssl = False,
    verify_certs= False
    )
 
# define location as coordinate for OpenSearch
def create_geo_index(index_name):
    if not client.indices.exists(index=index_name) :
        mapping = {
            "mappings" : {
                "properties":{
                    "location":{
                        "properties":{
                            "latitude" : {"type" : "float"},
                            "longitude" : {"type" : "float"},
                             # specific geo_point field for map visualization
                            "geo" : {"type": "geo_point"}
                        }
                    }
                }
            }
        }
        client.indices.create(index=index_name,body=mapping)
        print(f"Created index: {index_name}")
    else :
        print(f"Index {index_name} already exists!")

#Creating two db
create_geo_index("poi-data")
create_geo_index("parking-data")

#Sample POI
poi = PointOfInterest(
    type="museum",
    name="Allgäu Museum",
    location= Location(
        name="Museum Entry",
        latitude=47.728,
        longitude=10.311,
        address="Kempten"
    ),
    tags=["culture","history","indoor"]
)

parking = ParkingFacilities(
    type="park_and_ride",
    name="P+R Kempten South",
    capacity=150,
    location=Location(
        name="P+R Entry",
        longitude=47.720,
        latitude=10.315,
    ),
    fee_per_hour=0.0
)

def prep_upload(obj):
    data = obj.model_dump(mode='json')
    #create geo field format for OpenSearch Maps
    data['location']['geo'] = f"{data['location']['latitude']},{data['location']['longitude']}"
    return data

client.index(
    index = "poi-data",
    body = prep_upload(poi),
    id = poi.id,
    refresh=True
) 
print(f"Uploaded POI: {poi.name}")

client.index(
    index = "parking-data",
    body = prep_upload(parking),
    id = parking.id,
    refresh=True
) 
print(f"Uploaded Parking: {parking.name}")

