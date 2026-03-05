import os
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests


BAYERNCLOUD_API_KEY = os.getenv("BAYERNCLOUD_API_KEY")
BAYERNCLOUD_API_BASE_URL = os.getenv("BAYERNCLOUD_API_BASE_URL")
BAYERNCLOUD_DATA_DIR = os.getenv("BAYERNCLOUD_DATA_DIR", "/data/bayerncloud")
PAGE_SIZE = int(os.getenv("BAYERNCLOUD_PAGE_SIZE", "100"))

# Same IDs used in the microservice repo (api-gateway/main.py)
ENDPOINT_IDS: List[str] = [
    "915cbd6f-4434-4723-a54d-046b43ad52c5",
    "9d164080-9226-4f32-9d07-c5a83e970a58",
    "cf5cce8d-cc0c-4835-816a-d7c22e32394f",
    "e0ed98a3-4137-4e62-9227-eb084e292151",
    "0f102b60-cca7-4b80-ad6e-31bea5ea641c",
    "58056461-59dc-42e2-9025-3c16ce6968d7",
    "7a71084c-3802-42bc-88e7-f5c7bd22354c",
    "36a736f7-9e2d-4be5-b0f0-45ada2ff7013",
]

WITH_SUBTREES: List[str] = ["2db595fc-c60d-46fe-85d1-a4da648910da"]


def die(msg: str, code: int = 1) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
    raise SystemExit(code)


def fetch_page(endpoint_id: str, subtree: str, page: int, size: int) -> Tuple[Dict[str, Any], int]:
    url = f"{BAYERNCLOUD_API_BASE_URL}/{endpoint_id}"
    params = {"page[size]": size, "page[number]": page}
    payload = {
        "filter": {"classifications": {"in": {"withSubtree": [subtree]}}},
        "include": ["dc:additionalInformation", "dc:classification", "location", "address"],
    }
    headers = {
        "Authorization": f"Bearer {BAYERNCLOUD_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/ld+json",
    }
    r = requests.post(url, params=params, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    data = r.json()
    total = int(data.get("meta", {}).get("total", 0) or 0)
    return data, total


def safe_filename(slug: str) -> str:
    return "bayerncloud_" + "".join(c.lower() if c.isalnum() or c in "_-" else "_" for c in slug).strip("_") + ".json"


def main() -> None:
    if not BAYERNCLOUD_API_KEY or not BAYERNCLOUD_API_BASE_URL:
        die("BayernCloud not configured. Set BAYERNCLOUD_API_KEY and BAYERNCLOUD_API_BASE_URL.", 2)

    out_dir = Path(BAYERNCLOUD_DATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = []

    for endpoint_id in ENDPOINT_IDS:
        for subtree in WITH_SUBTREES:
            first, total = fetch_page(endpoint_id, subtree, page=1, size=PAGE_SIZE)
            meta = first.get("meta", {}).get("collection", {}) or {}
            slug = str(meta.get("slug") or meta.get("name") or endpoint_id)
            filename = safe_filename(slug)

            total_pages = int(math.ceil((total or 0) / PAGE_SIZE)) if total else 1
            graph = first.get("@graph", [])
            for p in range(2, total_pages + 1):
                page_data, _ = fetch_page(endpoint_id, subtree, page=p, size=PAGE_SIZE)
                if isinstance(page_data, dict) and "@graph" in page_data:
                    graph.extend(page_data["@graph"])

            if isinstance(first, dict):
                first["@graph"] = graph

            path = out_dir / filename
            path.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
            saved.append({"file": filename, "count": len(graph)})

            sys.stderr.write(f"[BAYERNCLOUD] saved {filename} ({len(graph)} items)\n")
            sys.stderr.flush()

    sys.stderr.write("[BAYERNCLOUD] done\n")
    sys.stderr.flush()


if __name__ == "__main__":
    main()
