"""
gntb_fetch_test.py
------------------
Wie gntb_fetch.py, aber holt nur EINE Seite pro Typ.
Zum schnellen Testen ob alle Typen funktionieren.

Output: gntb_raw_test.json
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import requests

load_dotenv()

# =============================================================================
# CONFIGURATION
# =============================================================================
API_KEY  = os.getenv("GNTB_API_KEY", "")
BASE_URL = "https://proxy.opendatagermany.io/api/ts/v2/kg/things"

DATA_DIR    = os.getenv("GNTB_DATA_DIR", ".")
OUTPUT_FILE = "gntb_raw_test.json"
PAGE_SIZE   = 5        # Nur 5 Objekte pro Typ
FETCH_DELAY = 0.15

TYPES_TO_FETCH = [
    ("odta:Place",              "odta",   "https://odta.io/voc/"),
    ("schema:Event",            "schema", "https://schema.org/"),
    ("schema:FoodEstablishment","schema", "https://schema.org/"),
    ("schema:LodgingBusiness",  "schema", "https://schema.org/"),
    ("schema:TouristAttraction","schema", "https://schema.org/"),
    ("schema:LocalBusiness",    "schema", "https://schema.org/"),
    ("odta:Trail",              "odta",   "https://odta.io/voc/"),
]

# =============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def fetch_one_page(type_tuple: tuple) -> List[Dict[str, Any]]:
    query_type, ctx_key, ctx_iri = type_tuple
    payload = {
        "@context": {ctx_key: ctx_iri, "sq": "http://www.onlim.com/shapequery/"},
        "sq:query": [{"@type": query_type}]
    }
    headers = {
        "x-api-key": API_KEY,
        "Content-Type": "application/ld+json",
        "Accept": "application/json",
        "page-size": str(PAGE_SIZE),
        "page": "1",
    }
    try:
        resp = requests.post(BASE_URL, headers=headers, json=payload, timeout=100)
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        total = data.get("metaData", {}).get("total", 0)
        logger.info(f"  → {len(items)} Stubs geholt (gesamt verfügbar: {total})")
        return items
    except Exception as e:
        logger.error(f"  Fehler: {e}")
        return []


def fetch_details(full_url_id: str) -> Optional[Dict[str, Any]]:
    if not full_url_id or "/" not in full_url_id:
        return None
    headers = {"x-api-key": API_KEY, "Accept": "application/json"}
    if "onlim.com" in full_url_id:
        local_id = full_url_id.rstrip("/").split("/")[-1]
        params: Dict[str, str] = {}
    else:
        namespace, local_id = full_url_id.rsplit("/", 1)
        params = {"ns": namespace + "/"}
    try:
        resp = requests.get(f"{BASE_URL}/{local_id}", headers=headers, params=params, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data, list) and data else data
    except Exception:
        return None


def main() -> None:
    if not API_KEY:
        raise SystemExit("GNTB_API_KEY nicht gesetzt.")

    all_details: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for type_tuple in TYPES_TO_FETCH:
        query_type = type_tuple[0]
        logger.info(f"\n--- {query_type} ---")

        stubs = fetch_one_page(type_tuple)

        for stub in stubs:
            raw_id = stub.get("@id")
            if not raw_id or raw_id in seen_ids:
                continue
            seen_ids.add(raw_id)

            detail = fetch_details(raw_id)
            if detail:
                all_details.append(detail)
            time.sleep(FETCH_DELAY)

    import pathlib
    out_path = pathlib.Path(DATA_DIR) / OUTPUT_FILE
    out_path.write_text(
        json.dumps({"@graph": all_details}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"\nFertig! {len(all_details)} Objekte → {out_path}")
    logger.info("Weiter mit: python gntb_transform.py (INPUT_PATTERN auf gntb_raw_test.json setzen)")


if __name__ == "__main__":
    main()
