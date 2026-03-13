"""
gntb_transform.py
-----------------
Liest gntb_raw*.json, entpackt JSON-LD und schreibt sauberes, OpenSearch-
und Ingestor-fertiges JSON.
"""

import glob
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

DATA_DIR = os.getenv("GNTB_DATA_DIR", ".")
INPUT_PATTERN = os.getenv("GNTB_INPUT_PATTERN", "gntb_raw*.json")
OUTPUT_FILE = os.getenv("GNTB_CLEAN_FILE", "gntb_clean.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _unwrap_one(value: Any) -> Any:
    if isinstance(value, list):
        for item in value:
            unwrapped = _unwrap_one(item)
            if unwrapped not in (None, "", []):
                return unwrapped
        return None
    if isinstance(value, dict):
        if "@value" in value:
            return value["@value"]
        if "@id" in value and len(value.keys()) == 1:
            return value["@id"]
        return value
    return value


def _unwrap_many(value: Any) -> List[Any]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    out: List[Any] = []
    for item in items:
        if isinstance(item, dict):
            if "@value" in item:
                out.append(item["@value"])
            elif "@id" in item and len(item.keys()) == 1:
                out.append(item["@id"])
            else:
                out.append(item)
        else:
            out.append(item)
    return out


def _find_prop_value(obj: Dict[str, Any], prop: str) -> Any:
    if prop in obj:
        return obj[prop]
    iri = f"https://schema.org/{prop}"
    if iri in obj:
        return obj[iri]
    for key, val in obj.items():
        if key.rstrip("/").split("/")[-1] == prop:
            return val
    return None


def _get(obj: Dict[str, Any], prop: str) -> Any:
    return _unwrap_one(_find_prop_value(obj, prop))


def _get_many(obj: Dict[str, Any], prop: str) -> List[Any]:
    return _unwrap_many(_find_prop_value(obj, prop))


def _get_nested(obj: Dict[str, Any], prop: str) -> Dict[str, Any]:
    raw = _find_prop_value(obj, prop)
    if raw is None:
        return {}
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and "@value" not in item:
                return item
        return {}
    if isinstance(raw, dict) and "@value" not in raw:
        return raw
    return {}


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


def normalize_type_name(value: Any) -> str:
    if value is None:
        return ""
    return str(value).rstrip("/").split("/")[-1]


def extract_types(raw: Dict[str, Any]) -> List[str]:
    values = _unwrap_many(raw.get("@type"))
    out: List[str] = []
    seen = set()
    for item in values:
        t = normalize_type_name(item)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def extract_images(raw: Dict[str, Any]) -> List[str]:
    candidates = _get_many(raw, "image")
    out: List[str] = []
    seen = set()
    for item in candidates:
        url = None
        if isinstance(item, str):
            url = item
        elif isinstance(item, dict):
            url = item.get("@id") or item.get("url") or item.get("contentUrl") or item.get("https://schema.org/url") or item.get("https://schema.org/contentUrl")
        if isinstance(url, str) and url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def build_address_label(street: str, postal_code: str, city: str, region: str) -> str:
    parts_line1 = [p for p in [street] if p]
    parts_line2 = [p for p in [postal_code, city] if p]
    parts = []
    if parts_line1:
        parts.append(", ".join(parts_line1))
    if parts_line2:
        parts.append(" ".join(parts_line2))
    if region and region not in " ".join(parts):
        parts.append(region)
    return ", ".join(parts)


def build_search_text(doc: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("name", "type", "description", "street", "postal_code", "city", "region", "country", "website", "telephone", "email"):
        value = doc.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    for key in ("types", "keywords"):
        values = doc.get(key, [])
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip():
                    parts.append(value.strip())
    seen = set()
    unique_parts = []
    for part in parts:
        if part not in seen:
            seen.add(part)
            unique_parts.append(part)
    return " | ".join(unique_parts)


def transform(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    source_id = raw.get("@id", "")
    if not source_id:
        return None

    address = _get_nested(raw, "address")
    geo = _get_nested(raw, "geo")

    name = str(_get(raw, "name") or "").strip() or "Unbekannt"
    description = clean_html(str(_get(raw, "description") or "")).strip()
    all_types = extract_types(raw)
    obj_type = all_types[-1] if all_types else "Unknown"

    street = str(_get(address, "streetAddress") or "").strip()
    postal_code = str(_get(address, "postalCode") or "").strip()
    city = str(_get(address, "addressLocality") or "").strip()
    region = str(_get(address, "addressRegion") or "").strip()
    country = str(_get(address, "addressCountry") or "").strip()
    address_label = build_address_label(street, postal_code, city, region)

    if not description:
        place = city or region or country or "Deutschland"
        description = f"{obj_type} namens {name} in {place}."
        if address_label:
            description += f" Adresse: {address_label}."

    lat = safe_float(_get(geo, "latitude"))
    lon = safe_float(_get(geo, "longitude"))

    website = _get(raw, "url")
    telephone = _get(raw, "telephone")
    email = _get(raw, "email")

    keywords: List[str] = []
    seen_keywords = set()
    for item in _get_many(raw, "keywords"):
        if isinstance(item, str):
            k = clean_html(item).strip()
            if k and k not in seen_keywords:
                seen_keywords.add(k)
                keywords.append(k)

    opening_hours_raw = _find_prop_value(raw, "openingHoursSpecification")

    doc: Dict[str, Any] = {
        "id": f"gntb:{source_id}",
        "source": "gntb",
        "source_id": source_id,
        "name": name,
        "type": obj_type,
        "types": all_types,
        "description": description,
        "street": street,
        "postal_code": postal_code,
        "city": city,
        "region": region,
        "country": country,
        "address_label": address_label,
        "website": website,
        "telephone": telephone,
        "email": email,
        "images": extract_images(raw),
        "keywords": keywords,
        "raw_types": _unwrap_many(raw.get("@type")),
    }

    if lat is not None and lon is not None:
        doc["lat"] = lat
        doc["lon"] = lon
        doc["location"] = {"lat": lat, "lon": lon}

    for field in ("startDate", "endDate"):
        val = _get(raw, field)
        if val not in (None, "", []):
            doc[field] = val

    if opening_hours_raw not in (None, "", []):
        doc["openingHoursSpecification"] = opening_hours_raw

    doc["raw"] = raw
    doc["search_text"] = build_search_text(doc)

    cleaned = {k: v for k, v in doc.items() if v not in (None, "", [])}
    if not cleaned.get("name") and not cleaned.get("address_label"):
        return None
    return cleaned


def main() -> None:
    out_dir = Path(DATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / OUTPUT_FILE

    pattern = str(Path(DATA_DIR) / INPUT_PATTERN)
    files = glob.glob(pattern)
    logger.info("Gefunden: %s Rohdatei(en) → %s", len(files), pattern)

    all_clean: List[Dict[str, Any]] = []
    skipped = 0
    seen_source_ids = set()

    for file_path in files:
        logger.info("Verarbeite: %s", file_path)
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            items = data.get("@graph", []) if isinstance(data, dict) else data
            if not isinstance(items, list):
                items = [items]

            file_count = 0
            dup_count = 0
            for item in items:
                try:
                    clean = transform(item)
                    if not clean:
                        skipped += 1
                        continue
                    source_id = clean.get("source_id")
                    if source_id in seen_source_ids:
                        dup_count += 1
                        continue
                    seen_source_ids.add(source_id)
                    all_clean.append(clean)
                    file_count += 1
                except Exception as e:
                    logger.debug("  Objekt übersprungen: %s", e)
                    skipped += 1

            logger.info("  → %s Objekte transformiert, %s Duplikate übersprungen.", file_count, dup_count)
        except Exception as e:
            logger.error("Fehler beim Lesen von %s: %s", file_path, e)

    logger.info("\nGesamt: %s Objekte, %s übersprungen.", len(all_clean), skipped)
    out_path.write_text(json.dumps(all_clean, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Gespeichert: %s", out_path)
    logger.info("Weiter mit: python gntb_ingest.py")


if __name__ == "__main__":
    main()
