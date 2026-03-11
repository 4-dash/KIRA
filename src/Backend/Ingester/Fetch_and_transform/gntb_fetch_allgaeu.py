"""
gntb_fetch_allgaeu.py
---------------------
Holt alle Objekte aus dem Allgäu vom DZT/GNTB Knowledge Graph.

Strategie: OR-Query mit zwei Bedingungen (laut Shape Query API Doku):
    1. schema:address.addressLocality iContains "Allgäu"  (z.B. "Oberallgäu", "Ostallgäu")
    2. sq:nearby  – Umkreis 60km um Mittelpunkt Allgäu (Kempten)

Alle Typen werden in einem einzigen Query abgefragt (kein separater Loop nötig),
da die filterDsList den Scope bereits einschränkt.

Output: gntb_raw_allgaeu.json  →  {"@graph": [...]}

Usage:
    GNTB_API_KEY=xxx python gntb_fetch_allgaeu.py
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
OUTPUT_FILE = "gntb_raw_allgaeu.json"

PAGE_SIZE   = int(os.getenv("GNTB_PAGE_SIZE", "50"))
FETCH_DELAY = float(os.getenv("GNTB_FETCH_DELAY", "0.15"))
PAGE_DELAY  = float(os.getenv("GNTB_PAGE_DELAY", "0.5"))

# Allgäu: Mittelpunkt Kempten, Radius 60km
# Passt auf: Oberallgäu, Ostallgäu, Unterallgäu, Kaufbeuren, Memmingen
GEO_LAT      = os.getenv("GNTB_GEO_LAT",      "47.7264")
GEO_LON      = os.getenv("GNTB_GEO_LON",      "10.3175")
GEO_DISTANCE = os.getenv("GNTB_GEO_DISTANCE", "60")

# DS-Filterliste – verhindert Timeout (laut Doku empfohlen)
FILTER_DS_LIST = "https://semantify.it/list/CRkyvcqGqeUu"

# =============================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# PAYLOAD  – OR: Adresse enthält "Allgäu"  ODER  Objekt liegt im Umkreis
# =============================================================================

# Vollständiger Context laut API-Dokumentation
CONTEXT = {
    "ds":     "https://vocab.sti2.at/ds/",
    "rdf":    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs":   "http://www.w3.org/2000/01/rdf-schema#",
    "schema": "https://schema.org/",
    "sh":     "http://www.w3.org/ns/shacl#",
    "xsd":    "http://www.w3.org/2001/XMLSchema#",
    "odta":   "https://odta.io/voc/",
    "sq":     "http://www.onlim.com/shapequery/",
    "@vocab": "http://www.onlim.com/shapequery/"
}

def build_payload() -> Dict[str, Any]:
    """
    OR-Query:
      Bedingung 1: addressRegion oder addressLocality enthält "Allgäu"
      Bedingung 2: Objekt liegt innerhalb GEO_DISTANCE km um Kempten

    Mehrere Objekte im sq:query Array = OR (laut Doku).
    Mehrere Properties im selben Objekt = AND.
    """
    return {
        "@context": CONTEXT,
        "sq:query": [
            # Bedingung 1a: addressLocality enthält "Allgäu" (z.B. "Sonthofen im Allgäu")
            {
                "schema:address": {
                    "schema:addressLocality": {
                        "sq:value": "Allgäu",
                        "sq:op": "iContains"
                    }
                }
            },
            # Bedingung 1b: addressRegion enthält "Allgäu" (z.B. "Oberallgäu")
            {
                "schema:address": {
                    "schema:addressRegion": {
                        "sq:value": "Allgäu",
                        "sq:op": "iContains"
                    }
                }
            },
            # Bedingung 2: Geo-Nähe zu Kempten
            {
                "schema:geo": {
                    "sq:nearby": {
                        "sq:latitude":  GEO_LAT,
                        "sq:longitude": GEO_LON,
                        "sq:distance":  GEO_DISTANCE
                    }
                }
            }
        ]
    }


# =============================================================================
# STEP 1 – Alle IDs paginiert sammeln
# =============================================================================

def fetch_all_ids() -> List[Dict[str, Any]]:
    payload = build_payload()
    # filterDsList verhindert Timeout (laut Doku empfohlen)
    search_url = f"{BASE_URL}?filterDsList={FILTER_DS_LIST}&lang=de"

    all_items: List[Dict[str, Any]] = []
    current_page = 1

    logger.info("Step 1: IDs sammeln ...")
    logger.info(f"  Geo-Filter: {GEO_LAT},{GEO_LON} Radius {GEO_DISTANCE}km")
    logger.info(f"  Adress-Filter: iContains 'Allgäu'")

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
            logger.info(f"  Seite {current_page}: {len(items)} IDs ({len(all_items)}/{total})")

            if len(all_items) >= total:
                break

            current_page += 1
            time.sleep(PAGE_DELAY)

        except requests.HTTPError as e:
            logger.error(f"  HTTP Fehler Seite {current_page}: {e}")
            break
        except Exception as e:
            logger.error(f"  Fehler: {e}")
            break

    logger.info(f"Gesamt IDs: {len(all_items)}")
    return all_items


# =============================================================================
# STEP 2 – Details pro ID
# =============================================================================

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
        resp = requests.get(
            f"{BASE_URL}/{local_id}",
            headers=headers,
            params=params,
            timeout=30
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
    out_path = pathlib.Path(DATA_DIR) / OUTPUT_FILE

    # Step 1 – IDs
    stubs = fetch_all_ids()
    if not stubs:
        logger.warning("Keine Objekte gefunden.")
        return

    # Step 2 – Details
    logger.info(f"\nStep 2: Details für {len(stubs)} Objekte ...")
    all_details: List[Dict[str, Any]] = []
    seen_ids: set = set()

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

        time.sleep(FETCH_DELAY)

    # Speichern
    out_path.write_text(
        json.dumps({"@graph": all_details}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    logger.info(f"\nFertig! {len(all_details)} Objekte → {out_path}")
    logger.info("Weiter mit: python gntb_transform.py")


if __name__ == "__main__":
    main()
