import os
import json
import glob
import logging
from typing import Dict, Any, List

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
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_AUTH = None

INDEX_NAME = os.getenv("POI_INDEX", "tourism-data-v-working")

DATA_DIR = os.getenv("BAYERNCLOUD_DATA_DIR", "../api-gateway/bayerncloud-data")
FILE_PATTERN = os.getenv("BAYERNCLOUD_FILE_PATTERN", "bayerncloud*.json")

# Azure OpenAI Specifics
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "")

# text-embedding-3-large uses 3072 dimensions
EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- LlamaIndex Settings ---
logger.info(f"Lade Azure OpenAI Embedding Modell: {AZURE_DEPLOYMENT_NAME}...")
embed_model = AzureOpenAIEmbedding(
    model="text-embedding-3-large",
    deployment_name=AZURE_DEPLOYMENT_NAME,
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version=AZURE_API_VERSION,
)

Settings.embed_model = embed_model
Settings.llm = None 

# WICHTIG: Chunk Size erhöhen, damit alle Metadaten reinpassen!
Settings.chunk_size = 2048 
Settings.chunk_overlap = 50

# --- Helfer ---

def clean_html(text: str) -> str:
    if not text:
        return "" 
    try:
        soup = BeautifulSoup(text, "lxml") 
        return soup.get_text(separator=" ").strip()
    except Exception:
        return str(text)

def safe_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def derive_type_from_filename(filename: str) -> str:
    base = os.path.basename(filename)
    parts = os.path.splitext(base)[0].split('_')
    if parts:
        return parts[-1].capitalize()
    return "Unknown"

# --- Hauptklasse ---

class RichLlamaIngestor:
    def __init__(self):
        self.os_client = OpenSearch(
            hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
            http_auth=OPENSEARCH_AUTH,
            use_ssl=False, 
            verify_certs=False,
            connection_class=RequestsHttpConnection
        )

    def create_index_if_not_exists(self):
        """Erstellt den Index manuell mit FAISS und GEO-Support."""
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
                    
                    # --- GEO MAPPINGS ---
                    "location": {"type": "geo_point"},
                    
                    # NEW: Geo-Shape Mapping
                    # ignore_z_value=True ensures the "881.0" elevation data doesn't crash the index
                    "geo_line": {
                        "type": "geo_shape",
                        "ignore_z_value": True 
                    }
                    # --------------------
                }
            }
        }

        if not self.os_client.indices.exists(index=INDEX_NAME):
            self.os_client.indices.create(index=INDEX_NAME, body=index_body)
            logger.info(f"Index '{INDEX_NAME}' erstellt.")
        else:
            logger.info(f"Index '{INDEX_NAME}' existiert bereits.")

    def parse_to_document(self, raw_doc: Dict, filename: str) -> Document:
        # 1. Text Content
        raw_desc = raw_doc.get('description', '')
        text_content = clean_html(raw_desc)
        
        # 2. Metadaten Extrahieren
        metadata = {}
        
        metadata['source_id'] = raw_doc.get('@id')
        metadata['name'] = raw_doc.get('name', 'Unbekannt')
        metadata['type'] = derive_type_from_filename(filename)
        
        address = raw_doc.get('address', {})
        if address:
            metadata['street'] = address.get('streetAddress', '')
            metadata['postal_code'] = address.get('postalCode', '')
            metadata['city'] = address.get('addressLocality', '')
            metadata['country'] = address.get('addressCountry', '')
        
        metadata['website'] = raw_doc.get('url')
        metadata['telephone'] = raw_doc.get('telephone')

        if not text_content:
            text_content = f"{metadata['type']} namens {metadata['name']} in {metadata.get('city', 'Bayern')}."

        if raw_doc.get('startDate'): metadata['startDate'] = raw_doc.get('startDate')
        if raw_doc.get('endDate'): metadata['endDate'] = raw_doc.get('endDate')
        
        # --- GEO POINT (Standard logic) ---
        geo = raw_doc.get('geo', {})
        lat = safe_float(geo.get('latitude'))
        lon = safe_float(geo.get('longitude'))
        
        # Default assignment (can be overwritten below)
        if lat is not None and lon is not None:
            metadata['location'] = f"{lat},{lon}"

        # --- NEW: GEO LINE (Shape & Start Point Overwrite) ---
        wkt_string = geo.get('line')
        
        if wkt_string:
            try:
                # 1. Clean & Parse WKT
                clean_wkt = wkt_string.replace("MULTILINESTRING Z", "MULTILINESTRING")
                shape_obj = wkt.loads(clean_wkt)
                
                # 2. Convert to GeoJSON for the 'geo_line' field
                geojson = shape_mapping(shape_obj)
                metadata['geo_line'] = geojson

                # 3. OVERWRITE LOCATION with Start Point
                # Handle both LineString and MultiLineString
                first_geom = shape_obj.geoms[0] if hasattr(shape_obj, 'geoms') else shape_obj
                
                if first_geom.coords:
                    # coords[0] gives (lon, lat, z) or (lon, lat)
                    start_point = first_geom.coords[0]
                    start_lon = start_point[0]
                    start_lat = start_point[1]
                    
                    # Overwrite metadata location with "lat,lon"
                    metadata['location'] = f"{start_lat},{start_lon}"
                
            except Exception as e:
                logger.warning(f"Could not parse geo line/start point for {metadata['name']}: {e}")
        # -----------------------------------------------------

        ohs = raw_doc.get('openingHoursSpecification')
        if ohs:
            metadata['openingHoursSpecification'] = str(ohs)[:1000] 

        # 3. Document erstellen
        doc = Document(
            text=text_content,
            metadata=metadata,
            id_=metadata['source_id'] or None,
            excluded_embed_metadata_keys=[
                'source_id', 
                'website', 
                'telephone',
                'geo_line', 
                'location'
            ],
            
            excluded_llm_metadata_keys=[
                'source_id',
                'geo_line', 
                'location'
            ]
        )
        
        return doc

    def run(self):
        # 1. Index vorbereiten
        self.create_index_if_not_exists()
        
        # 2. LlamaIndex Client verbinden
        client_wrapper = OpensearchVectorClient(
            endpoint=f"http://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}",
            index=INDEX_NAME,
            dim=EMBED_DIM,
            embedding_field="embedding",
            text_field="description",
            method={"name": "hnsw", "engine": "faiss"},
            os_client=self.os_client
        )
        vector_store = OpensearchVectorStore(client_wrapper)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        
        # 3. Dateien einlesen
        file_path_pattern = os.path.join(DATA_DIR, FILE_PATTERN)
        files = glob.glob(file_path_pattern)
        logger.info(f"Gefunden: {len(files)} Dateien.")

        all_documents = []
        for file_path in files:
            try:
                logger.info(f"Verarbeite: {file_path}")
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                items = data.get('@graph', [data]) if isinstance(data, dict) else data
                if isinstance(items, list):
                    for item in items:
                        try:
                            doc = self.parse_to_document(item, file_path)
                            if doc.id_:
                                all_documents.append(doc)
                        except Exception:
                            continue
            except Exception as e:
                logger.error(f"Fehler in {file_path}: {e}")

        # 4. Ingestieren
        if all_documents:
            logger.info(f"Starte Ingestion von {len(all_documents)} Dokumenten...")
            splitter = SentenceSplitter(chunk_size=Settings.chunk_size, chunk_overlap=50)
            
            VectorStoreIndex.from_documents(
                all_documents,
                storage_context=storage_context,
                transformations=[splitter],
                show_progress=True
            )
            logger.info("Ingestion erfolgreich abgeschlossen!")
        else:
            logger.warning("Keine Dokumente gefunden.")

if __name__ == "__main__":
    ingestor = RichLlamaIngestor()
    ingestor.run()