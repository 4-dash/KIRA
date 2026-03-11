"""
gntb_fetch.py
-------------
Holt ALLE PoI-Daten vom DZT/GNTB Knowledge Graph und speichert sie lokal.

Ablauf:
    1. POST /things  – alle IDs paginiert sammeln (pro Typ)
    2. GET  /things/{id}?ns=...  – Detaildaten pro Objekt
    3. Speichert: /data/gntb-data/gntb_raw.json

Danach: python gntb_ingest.py

Usage:
    GNTB_API_KEY=xxx python gntb_fetch.py
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
OUTPUT_FILE = os.getenv("GNTB_OUTPUT_FILE", "gntb_raw.json")

PAGE_SIZE   = int(os.getenv("GNTB_PAGE_SIZE", "50"))
FETCH_DELAY = float(os.getenv("GNTB_FETCH_DELAY", "0.15"))
PAGE_DELAY  = float(os.getenv("GNTB_PAGE_DELAY", "0.5"))

# Korrekte Typen – basierend auf ODTA Domain Specifications
# https://semantify.it/list/CRkyvcqGqeUu
# Format: (query_type, context_key, context_iri)
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
# LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# STEP 1 – IDs sammeln
# =============================================================================

def _page_headers(page_num: int) -> Dict[str, str]:
    return {
        "x-api-key": API_KEY,
        "Content-Type": "application/ld+json",
        "Accept": "application/json",
        "page-size": str(PAGE_SIZE),
        "page": str(page_num),
    }


def fetch_ids_for_type(type_tuple: tuple) -> List[Dict[str, Any]]:
    """Paginiert durch alle Seiten für einen Typ und gibt alle Stubs zurück."""
    query_type, ctx_key, ctx_iri = type_tuple
    payload = {
        "@context": {
            ctx_key: ctx_iri,
            "sq":    "http://www.onlim.com/shapequery/"
        },
        "sq:query": [{"@type": query_type}]
    }

    all_items: List[Dict[str, Any]] = []
    current_page = 1

    while True:
        try:
            resp = requests.post(
                BASE_URL,
                headers=_page_headers(current_page),
                json=payload,
                timeout=100,
            )
            resp.raise_for_status()
            data = resp.json()

            items = data.get("data", [])
            total = data.get("metaData", {}).get("total", 0)

            if not items:
                break

            all_items.extend(items)
            logger.info(f"    Seite {current_page}: {len(items)} IDs ({len(all_items)}/{total})")

            if len(all_items) >= total:
                break

            current_page += 1
            time.sleep(PAGE_DELAY)

        except requests.HTTPError as e:
            logger.error(f"    HTTP Fehler Seite {current_page}: {e}")
            break
        except Exception as e:
            logger.error(f"    Fehler Seite {current_page}: {e}")
            break

    return all_items


# =============================================================================
# STEP 2 – Details pro ID
# =============================================================================

def fetch_details(full_url_id: str) -> Optional[Dict[str, Any]]:
    """Ruft vollständige Daten für eine IRI ab."""
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
        resp = requests.get(
            f"{BASE_URL}/{local_id}",
            headers=headers,
            params=params,
            timeout=30,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return data[0] if isinstance(data, list) and data else data
    except Exception:
        return None


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    if not API_KEY:
        raise SystemExit("GNTB_API_KEY nicht gesetzt.")

    import pathlib
    out_dir = pathlib.Path(DATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILE

    all_details: List[Dict[str, Any]] = []
    seen_ids: set = set()

    for type_tuple in TYPES_TO_FETCH:
        query_type = type_tuple[0]
        logger.info(f"\n{'='*55}")
        logger.info(f"Typ: {query_type}")
        logger.info(f"{'='*55}")

        stubs = fetch_ids_for_type(type_tuple)
        logger.info(f"  {len(stubs)} IDs gefunden.")

        type_count = 0
        for idx, stub in enumerate(stubs, start=1):
            raw_id = stub.get("@id")
            if not raw_id or raw_id in seen_ids:
                continue
            seen_ids.add(raw_id)

            if idx % 50 == 0:
                logger.info(f"  [{idx}/{len(stubs)}] ...")

            detail = fetch_details(raw_id)
            if detail:
                all_details.append(detail)
                type_count += 1

            time.sleep(FETCH_DELAY)

        logger.info(f"  → {type_count} Objekte gespeichert.")

    # Speichern
    output = {"@graph": all_details}
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"\nFertig! {len(all_details)} Objekte gespeichert → {out_path}")
    logger.info("Weiter mit: python gntb_ingest.py")


if __name__ == "__main__":
    main()