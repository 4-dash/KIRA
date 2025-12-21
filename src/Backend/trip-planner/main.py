from fastapi import FastAPI
from pydantic import BaseModel
from typing import Any, Dict, List
import httpx

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

@app.post("/fetch-bc-data")
async def get_bayerncloud_poi_data(request: BayernCloudPOIRequest):
    if not request.retrieve_data:
        return {"detail": "retrieve_data is False"}
    
    endpoint_ids: List[str] = [
        "6f507251-0307-450c-9cb3-b150cd8169eb", # accommodation
    ]
    with_subtrees: List[str] = ["2db595fc-c60d-46fe-85d1-a4da648910da"]

    results = []

    for endpoint_id in endpoint_ids:
        for subtree in with_subtrees:
            raw_data = await fetch_external_data(
                endpoint_id=endpoint_id,
                with_subtree=subtree,
            )

            structured = structure_external_data(
                raw_data=raw_data,
                endpoint_id=endpoint_id,
                with_subtree=subtree,
            )

            results.append(raw_data)

    return {
        "count": len(results),
        "data": results,
    }


async def fetch_external_data(
    endpoint_id: str,
    with_subtree: str,
):
    url = f"{BAYERNCLOUD_API_BASE_URL}/{endpoint_id}"
    params = {"page[size]": 1}

    payload = {
        "filter": {
            "classifications": {
                "in": {
                    "withSubtree": [with_subtree]
                }
            }
        },
        "include": [
            "dc:additionalInformation",
            "dc:classification",
            "location",
            "address",
        ],
    }

    headers = {
        "Authorization": f"Bearer {BAYERNCLOUD_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        try:
            response = await client.post(
                url,
                params=params,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
        
        except httpx.HTTPStatusError as e:
            # API returned a 4xx or 5xx
            return {"error": str(e), "body": e.response.text}
        
        except httpx.RequestError as e:
            # Network or timeout errors
            return {"error": "Request failed", "details": str(e)}


def structure_external_data(
    raw_data: Any, # todo find correct type
    endpoint_id: str,
    with_subtree: str,
) -> Dict[str, Any]:
    structured = {
        "source": "bayerncloud",
        "endpoint_id": endpoint_id,
        "with_subtree": with_subtree,
        "items": raw_data,
    }

    new_structured = edit_fetched_data(structured)

    return new_structured


def edit_fetched_data(data: Dict[str, Any]) -> None:
    """
    Normalize fields, map to DB schema, clean values, etc.
    """
    return data
