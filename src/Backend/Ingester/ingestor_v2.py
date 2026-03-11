import os
import json
import glob
import logging
from typing import Dict, Any, List, Optional, Tuple

from bs4 import BeautifulSoup
from opensearchpy import OpenSearch, RequestsHttpConnection

from shapely import wkt
from shapely.geometry import mapping as shape_mapping

# LlamaIndex Imports
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient

# --- Konfiguration ---
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "opensearch")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_AUTH = None

# Vector / LLM index
INDEX_NAME = os.getenv("POI_INDEX", "tourism-data-v7")

# Dedicated raw map index
MAP_INDEX_NAME = os.getenv("POI_MAP_INDEX", "poi-data")

DATA_DIR = os.getenv("BAYERNCLOUD_DATA_DIR", "/data/bayerncloud")
FILE_PATTERN = os.getenv("BAYERNCLOUD_FILE_PATTERN", "bayerncloud*.json")

# Azure OpenAI Specifics
AZURE_OPENAI_KEY_EMB = os.getenv("AZURE_OPENAI_API_KEY_EMB", "")
AZURE_OPENAI_ENDPOINT_EMB = os.getenv("AZURE_OPENAI_ENDPOINT_EMB", "")
AZURE_DEPLOYMENT_NAME_EMB = os.getenv("AZURE_DEPLOYMENT_NAME_EMB", "")
AZURE_API_VERSION_EMB = os.getenv("AZURE_OPENAI_API_VERSION_EMB", "")

# text-embedding-3-large uses 3072 dimensions
EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- LlamaIndex Settings ---
logger.info(f"Lade Azure OpenAI Embedding Modell: {AZURE_DEPLOYMENT_NAME_EMB}...")
embed_model = AzureOpenAIEmbedding(
    model=AZURE_DEPLOYMENT_NAME_EMB,
    deployment_name=AZURE_DEPLOYMENT_NAME_EMB,
    api_key=AZURE_OPENAI_KEY_EMB,
    azure_endpoint=AZURE_OPENAI_ENDPOINT_EMB,
    api_version=AZURE_API_VERSION_EMB,
)

Settings.embed_model = embed_model
Settings.llm = None
Settings.chunk_size = 2048
Settings.chunk_overlap = 50


# --- Helfer ---
def format_opening_hours(ohs_data: Any) -> str:
    if not ohs_data:
        return ""

    if isinstance(ohs_data, dict):
        ohs_data = [ohs_data]

    structured_entries = []
    description_entries = []
    seen_entries = set()

    day_map = {
        "Monday": "Mo",
        "Tuesday": "Di",
        "Wednesday": "Mi",
        "Thursday": "Do",
        "Friday": "Fr",
        "Saturday": "Sa",
        "Sunday": "So",
    }

    for item in ohs_data:
        if item.get("opens") and item.get("closes"):
            try:
                start = str(item["opens"])[:5]
                end = str(item["closes"])[:5]

                raw_days = item.get("dayOfWeek", [])
                if isinstance(raw_days, str):
                    raw_days = [raw_days]

                clean_days = []
                for d in raw_days:
                    name = str(d).split("/")[-1]
                    clean_days.append(day_map.get(name, name))

                clean_days.sort()

                if len(clean_days) == 7:
                    day_str = "Täglich"
                elif not clean_days:
                    day_str = "Zeiten"
                else:
                    day_str = ", ".join(clean_days)

                entry = f"{day_str}: {start}-{end}"
                if entry not in seen_entries:
                    structured_entries.append(entry)
                    seen_entries.add(entry)
                continue
            except Exception:
                pass

        if item.get("description"):
            clean_text = clean_html(item["description"])
            if clean_text and clean_text not in description_entries:
                description_entries.append(clean_text)

    full_text = ""
    if structured_entries:
        full_text = " | ".join(structured_entries)
    elif description_entries:
        full_text = " | ".join(description_entries)

    if len(full_text) > 1000:
        return full_text[:997] + "..."

    return full_text


def clean_html(text: str) -> str:
    if not text:
        return ""
    try:
        soup = BeautifulSoup(text, "lxml")
        return soup.get_text(separator=" ").strip()
    except Exception:
        return str(text)


def safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def derive_type_from_filename(filename: str) -> str:
    base = os.path.basename(filename)
    parts = os.path.splitext(base)[0].split("_")
    if parts:
        return parts[-1].capitalize()
    return "Unknown"


def parse_location_string(value: Any) -> Tuple[Optional[float], Optional[float]]:
    if not value:
        return None, None
    if isinstance(value, str) and "," in value:
        parts = value.split(",")
        if len(parts) >= 2:
            lat = safe_float(parts[0].strip())
            lon = safe_float(parts[1].strip())
            return lat, lon
    return None, None


# --- Hauptklasse ---
class RichLlamaIngestor:
    def __init__(self):
        self.os_client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            http_auth=OPENSEARCH_AUTH,
            use_ssl=False,
            verify_certs=False,
            connection_class=RequestsHttpConnection,
        )

    def create_vector_index_if_not_exists(self):
        index_body = {
            "settings": {
                "index": {
                    "knn": True
                }
            },
            "mappings": {
                "properties": {
                    "description": {"type": "text"},
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": EMBED_DIM,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss"
                        }
                    },
                    "source_id": {"type": "keyword"},
                    "city": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    "postal_code": {"type": "keyword"},
                    "location": {"type": "geo_point"},
                    "geo_line": {
                        "type": "geo_shape",
                        "ignore_z_value": True
                    },
                }
            }
        }

        if not self.os_client.indices.exists(index=INDEX_NAME):
            self.os_client.indices.create(index=INDEX_NAME, body=index_body)
            logger.info(f"Vector-Index '{INDEX_NAME}' erstellt.")
        else:
            logger.info(f"Vector-Index '{INDEX_NAME}' existiert bereits.")

    def create_map_index_if_not_exists(self):
        index_body = {
            "mappings": {
                "properties": {
                    "source_id": {"type": "keyword"},
                    "name": {
                        "type": "text",
                        "fields": {"keyword": {"type": "keyword", "ignore_above": 256}},
                    },
                    "type": {"type": "keyword"},
                    "description": {"type": "text"},
                    "city": {"type": "keyword"},
                    "street": {"type": "text"},
                    "postal_code": {"type": "keyword"},
                    "country": {"type": "keyword"},
                    "website": {"type": "keyword", "ignore_above": 2048},
                    "telephone": {"type": "keyword"},
                    "openingHoursSpecification": {"type": "text"},
                    "location": {"type": "geo_point"},
                    "lat": {"type": "float"},
                    "lon": {"type": "float"},
                    "geo_line": {
                        "type": "geo_shape",
                        "ignore_z_value": True
                    },
                }
            }
        }

        if not self.os_client.indices.exists(index=MAP_INDEX_NAME):
            self.os_client.indices.create(index=MAP_INDEX_NAME, body=index_body)
            logger.info(f"Map-Index '{MAP_INDEX_NAME}' erstellt.")
        else:
            logger.info(f"Map-Index '{MAP_INDEX_NAME}' existiert bereits.")

    def extract_geo_fields(self, raw_doc: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[Dict[str, Any]]]:
        geo = raw_doc.get("geo", {})
        lat = safe_float(geo.get("latitude"))
        lon = safe_float(geo.get("longitude"))
        geo_line = None

        wkt_string = geo.get("line")
        if wkt_string:
            try:
                clean_wkt = wkt_string.replace("MULTILINESTRING Z", "MULTILINESTRING")
                shape_obj = wkt.loads(clean_wkt)
                geo_line = shape_mapping(shape_obj)

                first_geom = shape_obj.geoms[0] if hasattr(shape_obj, "geoms") else shape_obj
                if getattr(first_geom, "coords", None):
                    start_point = first_geom.coords[0]
                    start_lon = safe_float(start_point[0])
                    start_lat = safe_float(start_point[1])
                    if start_lat is not None and start_lon is not None:
                        lat = start_lat
                        lon = start_lon
            except Exception as e:
                logger.warning(f"Could not parse geo line/start point: {e}")

        return lat, lon, geo_line

    def build_metadata_and_text(self, raw_doc: Dict[str, Any], filename: str) -> Tuple[Dict[str, Any], str]:
        raw_desc = raw_doc.get("description", "")
        text_content = clean_html(raw_desc)

        metadata: Dict[str, Any] = {}
        metadata["source_id"] = raw_doc.get("@id")
        metadata["name"] = raw_doc.get("name", "Unbekannt")
        metadata["type"] = derive_type_from_filename(filename)

        address = raw_doc.get("address", {})
        if address:
            metadata["street"] = address.get("streetAddress", "")
            metadata["postal_code"] = address.get("postalCode", "")
            metadata["city"] = address.get("addressLocality", "")
            metadata["country"] = address.get("addressCountry", "")

        metadata["website"] = raw_doc.get("url") or raw_doc.get("address", {}).get("url")
        metadata["telephone"] = raw_doc.get("telephone") or raw_doc.get("address", {}).get("telephone")

        if not text_content:
            text_content = f"{metadata['type']} namens {metadata['name']} in {metadata.get('city', 'Bayern')}."

        if raw_doc.get("startDate"):
            metadata["startDate"] = raw_doc.get("startDate")
        if raw_doc.get("endDate"):
            metadata["endDate"] = raw_doc.get("endDate")

        ohs = raw_doc.get("openingHoursSpecification")
        metadata["openingHoursSpecification"] = format_opening_hours(ohs)

        lat, lon, geo_line = self.extract_geo_fields(raw_doc)

        # Keep legacy value for existing trip parsing logic
        if lat is not None and lon is not None:
            metadata["location"] = f"{lat},{lon}"

        if geo_line:
            metadata["geo_line"] = geo_line

        return metadata, text_content

    def build_llama_document(self, metadata: Dict[str, Any], text_content: str) -> Document:
        return Document(
            text=text_content,
            metadata=metadata,
            id_=metadata.get("source_id") or None,
            excluded_embed_metadata_keys=[
                "source_id",
                "website",
                "telephone",
                "geo_line",
                "location",
                "openingHoursSpecification",
            ],
            excluded_llm_metadata_keys=[
                "source_id",
                "geo_line",
                "location",
            ],
        )

    def build_map_document(self, metadata: Dict[str, Any], text_content: str) -> Optional[Dict[str, Any]]:
        lat, lon = parse_location_string(metadata.get("location"))
        if lat is None or lon is None:
            return None

        return {
            "source_id": metadata.get("source_id"),
            "name": metadata.get("name"),
            "type": metadata.get("type"),
            "description": text_content,
            "city": metadata.get("city"),
            "street": metadata.get("street"),
            "postal_code": metadata.get("postal_code"),
            "country": metadata.get("country"),
            "website": metadata.get("website"),
            "telephone": metadata.get("telephone"),
            "openingHoursSpecification": metadata.get("openingHoursSpecification"),
            "location": {
                "lat": lat,
                "lon": lon,
            },
            "lat": lat,
            "lon": lon,
            "geo_line": metadata.get("geo_line"),
        }

    def index_map_document(self, map_doc: Dict[str, Any]) -> None:
        source_id = map_doc.get("source_id")
        if not source_id:
            return

        self.os_client.index(
            index=MAP_INDEX_NAME,
            id=source_id,
            body=map_doc,
            refresh=False,
        )

    def run(self):
        # 1. Indizes vorbereiten
        self.create_vector_index_if_not_exists()
        self.create_map_index_if_not_exists()

        # 2. LlamaIndex Client verbinden
        client_wrapper = OpensearchVectorClient(
            endpoint=f"http://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}",
            index=INDEX_NAME,
            dim=EMBED_DIM,
            embedding_field="embedding",
            text_field="description",
            method={"name": "hnsw", "engine": "faiss"},
            os_client=self.os_client,
        )
        vector_store = OpensearchVectorStore(client_wrapper)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)

        # 3. Dateien einlesen
        file_path_pattern = os.path.join(DATA_DIR, FILE_PATTERN)
        files = glob.glob(file_path_pattern)
        logger.info(f"Gefunden: {len(files)} Dateien.")

        all_documents: List[Document] = []
        map_doc_count = 0

        for file_path in files:
            try:
                logger.info(f"Verarbeite: {file_path}")
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                items = data.get("@graph", [data]) if isinstance(data, dict) else data
                if isinstance(items, list):
                    for item in items:
                        try:
                            metadata, text_content = self.build_metadata_and_text(item, file_path)

                            doc = self.build_llama_document(metadata, text_content)
                            if doc.id_:
                                all_documents.append(doc)

                            map_doc = self.build_map_document(metadata, text_content)
                            if map_doc:
                                self.index_map_document(map_doc)
                                map_doc_count += 1

                        except Exception as inner_e:
                            logger.warning(f"Dokument konnte nicht verarbeitet werden: {inner_e}")
                            continue

            except Exception as e:
                logger.error(f"Fehler in {file_path}: {e}")

        # 4. Vector-Ingestion
        if all_documents:
            logger.info(f"Starte Vector-Ingestion von {len(all_documents)} Dokumenten...")
            splitter = SentenceSplitter(chunk_size=Settings.chunk_size, chunk_overlap=50)

            VectorStoreIndex.from_documents(
                all_documents,
                storage_context=storage_context,
                transformations=[splitter],
                show_progress=True,
            )
            logger.info("Vector-Ingestion erfolgreich abgeschlossen!")
        else:
            logger.warning("Keine Vector-Dokumente gefunden.")

        self.os_client.indices.refresh(index=MAP_INDEX_NAME)
        logger.info(f"Map-Dokumente indexiert: {map_doc_count}")


if __name__ == "__main__":
    ingestor = RichLlamaIngestor()
    ingestor.run()