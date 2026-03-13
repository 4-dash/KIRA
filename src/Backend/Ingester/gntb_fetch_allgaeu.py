"""
gntb_fetch_allgaeu.py
---------------------
Holt GNTB/DZT-Knowledge-Graph-Objekte für das Allgäu und speichert Rohdaten als
{"@graph": [...]}.

Nutzung:
    GNTB_API_KEY=... python gntb_fetch_allgaeu.py
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import requests

load_dotenv()

API_KEY = os.getenv("GNTB_API_KEY", "")
BASE_URL = os.getenv("GNTB_BASE_URL", "https://proxy.opendatagermany.io/api/ts/v2/kg/things")
DATA_DIR = os.getenv("GNTB_DATA_DIR", ".")
OUTPUT_FILE = os.getenv("GNTB_RAW_FILE", "gntb_raw_allgaeu.json")

PAGE_SIZE = int(os.getenv("GNTB_PAGE_SIZE", "50"))
FETCH_DELAY = float(os.getenv("GNTB_FETCH_DELAY", "0.15"))
PAGE_DELAY = float(os.getenv("GNTB_PAGE_DELAY", "0.5"))

GEO_LAT = os.getenv("GNTB_GEO_LAT", "47.7264")
GEO_LON = os.getenv("GNTB_GEO_LON", "10.3175")
GEO_DISTANCE = os.getenv("GNTB_GEO_DISTANCE", "60")
FILTER_DS_LIST = os.getenv("GNTB_FILTER_DS_LIST", "https://semantify.it/list/CRkyvcqGqeUu")
PROJECTION_DS = os.getenv("GNTB_PROJECTION_DS", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

CONTEXT = {
    "ds": "https://vocab.sti2.at/ds/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "schema": "https://schema.org/",
    "sh": "http://www.w3.org/ns/shacl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "odta": "https://odta.io/voc/",
    "sq": "http://www.onlim.com/shapequery/",
    "@vocab": "http://www.onlim.com/shapequery/",
}


def build_payload() -> Dict[str, Any]:
    return {
        "@context": CONTEXT,
        "sq:query": [
            {
                "schema:address": {
                    "schema:addressLocality": {"sq:value": "Allgäu", "sq:op": "iContains"}
                }
            },
            {
                "schema:address": {
                    "schema:addressRegion": {"sq:value": "Allgäu", "sq:op": "iContains"}
                }
            },
            {
                "schema:geo": {
                    "sq:nearby": {
                        "sq:latitude": GEO_LAT,
                        "sq:longitude": GEO_LON,
                        "sq:distance": GEO_DISTANCE,
                    }
                }
            },
        ],
    }


def fetch_all_ids() -> List[Dict[str, Any]]:
    payload = build_payload()
    search_url = f"{BASE_URL}?filterDsList={FILTER_DS_LIST}&lang=de"
    all_items: List[Dict[str, Any]] = []
    current_page = 1

    logger.info("Step 1: IDs sammeln ...")
    logger.info("  Geo-Filter: %s,%s Radius %skm", GEO_LAT, GEO_LON, GEO_DISTANCE)
    logger.info("  Adress-Filter: iContains 'Allgäu'")

    while True:
        headers = {
            "x-api-key": API_KEY,
            "Content-Type": "application/ld+json",
            "Accept": "application/json",
            "page-size": str(PAGE_SIZE),
            "page": str(current_page),
        }
        try:
            resp = requests.post(search_url, headers=headers, json=payload, timeout=100)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            total = data.get("metaData", {}).get("total", 0)

            if not items:
                logger.info("  Keine weiteren Ergebnisse.")
                break

            all_items.extend(items)
            logger.info("  Seite %s: %s IDs (%s/%s)", current_page, len(items), len(all_items), total)

            if total and len(all_items) >= total:
                break

            current_page += 1
            time.sleep(PAGE_DELAY)
        except requests.HTTPError as e:
            logger.error("  HTTP Fehler Seite %s: %s", current_page, e)
            break
        except Exception as e:
            logger.error("  Fehler: %s", e)
            break

    logger.info("Gesamt IDs: %s", len(all_items))
    return all_items


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

    if PROJECTION_DS:
        params["projectionDs"] = PROJECTION_DS

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

    out_path = Path(DATA_DIR) / OUTPUT_FILE
    out_path.parent.mkdir(parents=True, exist_ok=True)

    stubs = fetch_all_ids()
    if not stubs:
        logger.warning("Keine Objekte gefunden.")
        out_path.write_text(json.dumps({"@graph": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    logger.info("\nStep 2: Details für %s Objekte ...", len(stubs))
    all_details: List[Dict[str, Any]] = []
    seen_ids = set()

    for idx, stub in enumerate(stubs, start=1):
        raw_id = stub.get("@id")
        if not raw_id or raw_id in seen_ids:
            continue
        seen_ids.add(raw_id)

        if idx % 50 == 0:
            logger.info("  [%s/%s] ...", idx, len(stubs))

        detail = fetch_details(raw_id)
        if detail:
            all_details.append(detail)
        time.sleep(FETCH_DELAY)

    out_path.write_text(json.dumps({"@graph": all_details}, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("\nFertig! %s Objekte → %s", len(all_details), out_path)
    logger.info("Weiter mit: python gntb_transform.py")


if __name__ == "__main__":
    main()
