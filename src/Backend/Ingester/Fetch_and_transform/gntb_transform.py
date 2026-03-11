"""
gntb_transform.py
-----------------
Liest gntb_raw.json (erzeugt von gntb_fetch.py),
entpackt JSON-LD und schreibt sauberes, OpenSearch-fertiges JSON.

Ablauf:
    gntb_fetch.py  →  gntb_raw.json
    gntb_transform.py  →  gntb_clean.json      ← dieses Script
    gntb_ingest.py  →  OpenSearch

Usage:
    python gntb_transform.py

Output: /data/gntb-data/gntb_clean.json
"""

import glob
import json
import logging
import os
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

# =============================================================================
# CONFIGURATION
# =============================================================================
DATA_DIR      = os.getenv("GNTB_DATA_DIR", ".")          # Standard: aktueller Ordner
INPUT_PATTERN = os.getenv("GNTB_INPUT_PATTERN", "gntb_raw*.json")   # alle gntb_raw*.json
OUTPUT_FILE   = os.getenv("GNTB_CLEAN_FILE", "gntb_clean.json")

# =============================================================================
# LOGGING
# =============================================================================
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# =============================================================================
# JSON-LD HELPERS
# =============================================================================

def _unwrap(value: Any) -> Any:
    """Entpackt JSON-LD Wert-Container."""
    if isinstance(value, list):
        return _unwrap(value[0]) if value else None
    if isinstance(value, dict):
        return value.get("@value") or value.get("@id") or value
    return value

def _get(obj: Dict[str, Any], prop: str) -> Any:
    """Liest eine Eigenschaft – egal ob short-key oder volle IRI."""
    if prop in obj:
        return _unwrap(obj[prop])
    iri = f"https://schema.org/{prop}"
    if iri in obj:
        return _unwrap(obj[iri])
    for key, val in obj.items():
        if key.rstrip("/").split("/")[-1] == prop:
            return _unwrap(val)
    return None

def _get_nested(obj: Dict[str, Any], prop: str) -> Dict[str, Any]:
    """Liest ein verschachteltes Objekt (address, geo)."""
    raw = None
    if prop in obj:
        raw = obj[prop]
    else:
        iri = f"https://schema.org/{prop}"
        raw = obj.get(iri)
        if raw is None:
            for key, val in obj.items():
                if key.rstrip("/").split("/")[-1] == prop:
                    raw = val
                    break
    if raw is None:
        return {}
    if isinstance(raw, list):
        raw = raw[0] if raw else {}
    if isinstance(raw, dict) and "@value" not in raw:
        return raw
    return {}


# =============================================================================
# UTILITIES
# =============================================================================

def clean_html(text: str) -> str:
    if not text:
        return ""
    try:
        return BeautifulSoup(str(text), "lxml").get_text(separator=" ").strip()
    except Exception:
        return str(text)

def safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def type_from_raw(raw: Dict) -> str:
    t = raw.get("@type", "")
    if isinstance(t, list):
        t = t[-1] if t else ""
    return str(t).rstrip("/").split("/")[-1] if t else "Unknown"


# =============================================================================
# TRANSFORM: JSON-LD → sauberes Dict
# =============================================================================

def transform(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Wandelt ein rohes JSON-LD Objekt in ein sauberes, flaches Dict um
    das OpenSearch und der Ingestor direkt verarbeiten können.
    """
    source_id = raw.get("@id", "")
    if not source_id:
        return None

    address = _get_nested(raw, "address")
    geo     = _get_nested(raw, "geo")

    description = clean_html(str(_get(raw, "description") or ""))
    name        = str(_get(raw, "name") or "Unbekannt")
    obj_type    = type_from_raw(raw)
    city        = str(_get(address, "addressLocality") or "")
    region      = str(_get(address, "addressRegion") or "")

    # Fallback-Text wenn keine Beschreibung vorhanden
    if not description:
        description = (
            f"{obj_type} namens {name} "
            f"in {city or region or 'Deutschland'}."
        )

    doc: Dict[str, Any] = {
        "source_id":   source_id,
        "name":        name,
        "type":        obj_type,
        "description": description,

        # Adresse
        "street":      str(_get(address, "streetAddress") or ""),
        "postal_code": str(_get(address, "postalCode") or ""),
        "city":        city,
        "region":      region,
        "country":     str(_get(address, "addressCountry") or ""),

        # Kontakt
        "website":     _get(raw, "url"),
        "telephone":   _get(raw, "telephone"),
        "email":       _get(raw, "email"),
    }

    # Geo – OpenSearch geo_point Format: "lat,lon"
    lat = safe_float(_get(geo, "latitude"))
    lon = safe_float(_get(geo, "longitude"))
    if lat is not None and lon is not None:
        doc["location"] = f"{lat},{lon}"

    # Daten (relevant für Events)
    for field in ("startDate", "endDate"):
        val = _get(raw, field)
        if val:
            doc[field] = val

    # Öffnungszeiten
    ohs = _get(raw, "openingHoursSpecification")
    if ohs:
        ohs_str = str(ohs)
        doc["openingHoursSpecification"] = (
            ohs_str[:997] + "..." if len(ohs_str) > 1000 else ohs_str
        )

    # Leere Felder entfernen
    return {k: v for k, v in doc.items() if v not in (None, "", [])}


# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    import pathlib

    out_dir = pathlib.Path(DATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILE

    # Alle passenden Input-Dateien einlesen
    pattern = str(pathlib.Path(DATA_DIR) / INPUT_PATTERN)
    files = glob.glob(pattern)
    logger.info(f"Gefunden: {len(files)} Rohdatei(en) → {pattern}")

    all_clean: List[Dict[str, Any]] = []
    skipped = 0

    for file_path in files:
        logger.info(f"Verarbeite: {file_path}")
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            items = data.get("@graph", []) if isinstance(data, dict) else data
            if not isinstance(items, list):
                items = [items]

            file_count = 0
            for item in items:
                try:
                    clean = transform(item)
                    if clean:
                        all_clean.append(clean)
                        file_count += 1
                    else:
                        skipped += 1
                except Exception as e:
                    logger.debug(f"  Objekt übersprungen: {e}")
                    skipped += 1

            logger.info(f"  → {file_count} Objekte transformiert.")

        except Exception as e:
            logger.error(f"Fehler beim Lesen von {file_path}: {e}")

    logger.info(f"\nGesamt: {len(all_clean)} Objekte, {skipped} übersprungen.")

    # Speichern
    out_path.write_text(
        json.dumps(all_clean, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"Gespeichert: {out_path}")
    logger.info("Weiter mit: python gntb_ingest.py")


if __name__ == "__main__":
    main()