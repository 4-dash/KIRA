from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List
import httpx

import os

import json
import asyncio
import math
from anyio import to_thread

app = FastAPI()

class PlanTripRequest(BaseModel):
    origin: str
    destination: str

class TripResponse(BaseModel):
    trip_id: str
    origin: str
    destination: str
    duration_minutes: int

@app.post("/plan-trip", response_model=TripResponse)
async def plan_trip(request: PlanTripRequest):

    return TripResponse(
        trip_id="mock-trip-001",
        origin=request.origin,
        destination=request.destination,
        duration_minutes=42
    )


# retrive POI
class BayernCloudPOIRequest(BaseModel):
    retrieve_data: bool
    # endpoint_ids: List[str]
    # with_subtrees: List[str]

# bayerncloud
BAYERNCLOUD_API_KEY = ""
BAYERNCLOUD_API_BASE_URL = ""
BAYERNCLOUD_DATA_DIR = "bayerncloud-data"

@app.post("/fetch-bc-data")
async def get_bayerncloud_poi_data(request: BayernCloudPOIRequest):
    if not request.retrieve_data:
        return {"detail": "retrieve_data is False"}
    
    endpoint_ids: List[str] = [
        "915cbd6f-4434-4723-a54d-046b43ad52c5", # list_attractions
        "9d164080-9226-4f32-9d07-c5a83e970a58", # list_retail
        "cf5cce8d-cc0c-4835-816a-d7c22e32394f", # list_food
        "e0ed98a3-4137-4e62-9227-eb084e292151", # list_mobility 
        "0f102b60-cca7-4b80-ad6e-31bea5ea641c", # list_nature
        "58056461-59dc-42e2-9025-3c16ce6968d7", # list_tracks
        "7a71084c-3802-42bc-88e7-f5c7bd22354c", # list_accommodations
        "36a736f7-9e2d-4be5-b0f0-45ada2ff7013", # list_current_events
    ]
    
    with_subtrees: List[str] = ["2db595fc-c60d-46fe-85d1-a4da648910da"]
    
    PAGE_SIZE = 100

    file_info = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for endpoint_id in endpoint_ids:
            for subtree in with_subtrees:
                # 1. Fetch Page 1 - Get Master Template
                master_data, total_items = await fetch_external_data(client, endpoint_id, subtree, page=1, size=PAGE_SIZE)
                
                if "error" in master_data:
                    continue
                
                # 2. Extract the name for the filename
                # Falls back to endpoint_id if 'slug' or 'name' is missing
                meta_collection = master_data.get("meta", {}).get("collection", {})
                endpoint_slug = meta_collection.get("slug") or meta_collection.get("name") or endpoint_id
                # Sanitize slug: replace spaces with underscores if name was used
                filename = f"bayerncloud_{endpoint_slug.replace(' ', '_').lower()}.json"

                # 3. Handle Pagination
                total_pages = math.ceil(total_items / PAGE_SIZE)
                if total_pages > 1:
                    tasks = [
                        fetch_external_data(client, endpoint_id, subtree, page=p, size=PAGE_SIZE) 
                        for p in range(2, total_pages + 1)
                    ]
                    pages_results = await asyncio.gather(*tasks)
                    
                    for page_data, _ in pages_results:
                        if "@graph" in page_data:
                            master_data["@graph"].extend(page_data["@graph"])

                # 4. Save this specific endpoint's data to its own file
                try:
                    def save_file(data, fname):
                        with open(os.path.join(BAYERNCLOUD_DATA_DIR, fname), "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=4)
                    
                    await to_thread.run_sync(save_file, master_data, filename)
                    file_info.append({"file": filename, "count": len(master_data.get("@graph", []))})
                    
                except Exception as e:
                    print(f"Failed to write {filename}: {e}")

    return {"status": "success", "processed_files": file_info}

async def fetch_external_data(client: httpx.AsyncClient, endpoint_id: str, with_subtree: str, page: int, size: int):
    url = f"{BAYERNCLOUD_API_BASE_URL}/{endpoint_id}"
    params = {"page[size]": size, "page[number]": page}
    payload = {
        "filter": {"classifications": {"in": {"withSubtree": [with_subtree]}}},
        "include": ["dc:additionalInformation", "dc:classification", "location", "address"],
    }
    headers = {
        "Authorization": f"Bearer {BAYERNCLOUD_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/ld+json"
    }

    try:
        response = await client.post(url, params=params, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        total_items = data.get("meta", {}).get("total", 0)
        return data, total_items
    except Exception as e:
        return {"error": str(e)}, 0