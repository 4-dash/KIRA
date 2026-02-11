from fastapi import FastAPI, HTTPException, WebSocket
from pydantic import BaseModel
from typing import List, Optional, Any, Dict
import httpx
import os
import json
import asyncio
import math
from anyio import to_thread

from chat_ws import handle_chat_websocket

app = FastAPI()

# ============================================================
# WebSocket Chat (old frontend compatibility)
# ============================================================

@app.websocket("/chat")
async def chat_endpoint(websocket: WebSocket):
    await handle_chat_websocket(websocket)


# ============================================================
# Trip Planning Gateway (proxies to trip-planner service)
# ============================================================

TRIP_PLANNER_URL = os.getenv("TRIP_PLANNER_URL", "http://trip-planner:8001").rstrip("/")


class PlanTripRequest(BaseModel):
    origin: str
    destination: str
    date: Optional[str] = None   # YYYY-MM-DD
    time: Optional[str] = None   # HH:MM


@app.post("/plan-trip")
async def plan_trip(request: PlanTripRequest) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "from_stop": request.origin,
        "to_stop": request.destination,
    }
    if request.date is not None:
        payload["date"] = request.date
    if request.time is not None:
        payload["time"] = request.time

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{TRIP_PLANNER_URL}/plan-by-stops",
            json=payload
        )
        resp.raise_for_status()
        return resp.json()


# ============================================================
# BayernCloud ingestion (gateway-owned for now)
# ============================================================

class BayernCloudPOIRequest(BaseModel):
    retrieve_data: bool


BAYERNCLOUD_API_KEY = os.getenv("BAYERNCLOUD_API_KEY", "")
BAYERNCLOUD_API_BASE_URL = os.getenv("BAYERNCLOUD_API_BASE_URL", "")
BAYERNCLOUD_DATA_DIR = os.getenv("BAYERNCLOUD_DATA_DIR", "bayerncloud-data")

os.makedirs(BAYERNCLOUD_DATA_DIR, exist_ok=True)


@app.post("/poi/fetch-bayerncloud")
async def fetch_bayerncloud_pois(request: BayernCloudPOIRequest):
    if not request.retrieve_data:
        return {"detail": "retrieve_data is False"}

    if not BAYERNCLOUD_API_KEY or not BAYERNCLOUD_API_BASE_URL:
        raise HTTPException(
            status_code=500,
            detail="BayernCloud API not configured (set BAYERNCLOUD_API_KEY and BAYERNCLOUD_API_BASE_URL).",
        )

    endpoint_ids: List[str] = [
        "915cbd6f-4434-4723-a54d-046b43ad52c5",
        "9d164080-9226-4f32-9d07-c5a83e970a58",
        "cf5cce8d-cc0c-4835-816a-d7c22e32394f",
        "e0ed98a3-4137-4e62-9227-eb084e292151",
        "0f102b60-cca7-4b80-ad6e-31bea5ea641c",
        "58056461-59dc-42e2-9025-3c16ce6968d7",
        "7a71084c-3802-42bc-88e7-f5c7bd22354c",
        "36a736f7-9e2d-4be5-b0f0-45ada2ff7013",
    ]

    with_subtrees: List[str] = ["2db595fc-c60d-46fe-85d1-a4da648910da"]

    PAGE_SIZE = 100
    file_info = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for endpoint_id in endpoint_ids:
            for subtree in with_subtrees:
                master_data, total_items = await fetch_external_data(
                    client, endpoint_id, subtree, page=1, size=PAGE_SIZE
                )

                if "error" in master_data:
                    file_info.append({"endpoint_id": endpoint_id, "error": master_data["error"]})
                    continue

                meta_collection = master_data.get("meta", {}).get("collection", {})
                endpoint_slug = meta_collection.get("slug") or meta_collection.get("name") or endpoint_id
                filename = f"bayerncloud_{str(endpoint_slug).replace(' ', '_').lower()}.json"

                total_pages = math.ceil((total_items or 0) / PAGE_SIZE)

                if total_pages > 1:
                    tasks = [
                        fetch_external_data(client, endpoint_id, subtree, page=p, size=PAGE_SIZE)
                        for p in range(2, total_pages + 1)
                    ]
                    pages_results = await asyncio.gather(*tasks)

                    for page_data, _ in pages_results:
                        if isinstance(page_data, dict) and "@graph" in page_data:
                            master_data["@graph"].extend(page_data["@graph"])

                await to_thread.run_sync(
                    save_json_file,
                    master_data,
                    os.path.join(BAYERNCLOUD_DATA_DIR, filename),
                )

                file_info.append({
                    "file": filename,
                    "count": len(master_data.get("@graph", []))
                })

    return {"status": "success", "processed_files": file_info}


async def fetch_external_data(
    client: httpx.AsyncClient,
    endpoint_id: str,
    with_subtree: str,
    page: int,
    size: int,
):
    url = f"{BAYERNCLOUD_API_BASE_URL}/{endpoint_id}"
    params = {"page[size]": size, "page[number]": page}

    payload = {
        "filter": {"classifications": {"in": {"withSubtree": [with_subtree]}}},
        "include": ["dc:additionalInformation", "dc:classification", "location", "address"],
    }

    headers = {
        "Authorization": f"Bearer {BAYERNCLOUD_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/ld+json",
    }

    try:
        response = await client.post(url, params=params, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        total_items = data.get("meta", {}).get("total", 0)
        return data, total_items
    except Exception as e:
        return {"error": str(e)}, 0


def save_json_file(data: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
