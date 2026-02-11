import os
import json
import glob
import logging
from typing import Dict, Any, List

from bs4 import BeautifulSoup
from opensearchpy import OpenSearch, RequestsHttpConnection

# LlamaIndex Imports
from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.core.node_parser import SentenceSplitter
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient

# --- Konfiguration ---
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_AUTH = None

INDEX_NAME = os.getenv("POI_INDEX", "tourism-data-v9")

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
        # 1. Low-Level Client
        self.os_client = OpenSearch(
            hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
            http_auth=OPENSEARCH_AUTH,
            use_ssl=False, 
            verify_certs=False,
            connection_class=RequestsHttpConnection
        )

    def create_index_if_not_exists(self):
        """
        Erstellt den Index manuell mit FAISS und expliziten Mappings 
        für Geometrie-Typen und technische Metadaten.
        """
        index_body = {
            "settings": {
                "index": {
                    "knn": True,
                    "refresh_interval": "1s"
                }
            },
            "mappings": {
                "properties": {
                    # LlamaIndex Standard Content Feld
                    "description": {"type": "text"}, 
                    
                    # Vektor-Feld für die semantische Suche
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": EMBED_DIM,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss",
                            "space_type": "l2"
                        }
                    },
                    
                    # --- GEOMETRIE ---
                    "location": {"type": "geo_point"},
                    "geo_line": {"type": "geo_shape"},
                    
                    # --- FILTERBARE METADATEN ---
                    "source_id": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    "city": {"type": "keyword"},
                    "postal_code": {"type": "keyword"},
                    "slug": {"type": "keyword"},
                    
                    # --- TOUR STATISTIKEN ---
                    "ascent": {"type": "integer"},
                    "descent": {"type": "integer"},
                    "length_m": {"type": "integer"},
                    "duration_min": {"type": "integer"},
                    "max_altitude": {"type": "integer"},
                    
                    # --- LODGING / UNTERKUNFT ---
                    "beds": {"type": "integer"},
                    "price_range": {"type": "keyword"},
                    
                    # --- EVENTS ---
                    "startDate": {"type": "date"},
                    "endDate": {"type": "date"}
                }
            }
        }

        if not self.os_client.indices.exists(index=INDEX_NAME):
            try:
                self.os_client.indices.create(index=INDEX_NAME, body=index_body)
                logger.info(f"Index '{INDEX_NAME}' mit Geo-Mappings erfolgreich erstellt.")
            except Exception as e:
                logger.error(f"Fehler beim Erstellen des Index: {e}")
        else:
            logger.info(f"Index '{INDEX_NAME}' existiert bereits. Überspringe Erstellung.")

    def parse_to_document(self, raw_doc: Dict, filename: str) -> Document:
        # 1. Text Content
        raw_desc = raw_doc.get('description', '')
        text_content = clean_html(raw_desc)
        
        # 2. Metadaten Extrahieren
        metadata = {}
        
        # Basis & IDs
        metadata['source_id'] = raw_doc.get('id') or raw_doc.get('@id')
        metadata['name'] = raw_doc.get('name', 'Unbekannt')
        metadata['type'] = derive_type_from_filename(filename)
        metadata['slug'] = raw_doc.get('slug')
        metadata['copyright'] = raw_doc.get('copyrightNotice')

        # --- ADDRESS ---
        address = raw_doc.get('address', {})
        if isinstance(address, dict):
            metadata['street'] = address.get('streetAddress', '')
            metadata['postal_code'] = address.get('postalCode', '')
            metadata['city'] = address.get('addressLocality', '')
            metadata['country'] = address.get('addressCountry', '')

        # --- GEO & LINE ---
        geo = raw_doc.get('geo', {})
        if isinstance(geo, dict):
            if geo.get('type') == 'GeoCoordinates':
                lat = safe_float(geo.get('latitude'))
                lon = safe_float(geo.get('longitude'))
                if lat is not None and lon is not None:
                    metadata['location'] = f"{lat},{lon}"
            
            elif geo.get('type') == 'GeoShape':
                metadata['geo_line'] = geo.get('line')
                metadata['geo_id'] = geo.get('id')

        loc_field = raw_doc.get('location')
        if isinstance(loc_field, str) and "POINT" in loc_field:
            try:
                coords = loc_field.replace("POINT (", "").replace(")", "").split()
                if len(coords) >= 2:
                    metadata['location'] = f"{coords[1]},{coords[0]}"
            except: pass

        # --- TOUR SPECIFICS ---
        metadata['ascent'] = raw_doc.get('dc:ascent')
        metadata['descent'] = raw_doc.get('dc:descent')
        metadata['min_altitude'] = raw_doc.get('dc:minAltitude')
        metadata['max_altitude'] = raw_doc.get('dc:maxAltitude')
        metadata['length_m'] = raw_doc.get('dc:length')
        metadata['duration_min'] = raw_doc.get('dc:duration')

        # --- ACCOMMODATION & EVENTS ---
        metadata['beds'] = raw_doc.get('dc:totalNumberOfBeds')
        metadata['price_range'] = raw_doc.get('priceRange')
        metadata['startDate'] = raw_doc.get('startDate')
        metadata['endDate'] = raw_doc.get('endDate')

        # Fallback Text
        if not text_content:
            text_content = f"{metadata['name']} ({metadata['type']}) in {metadata.get('city', 'Bayern')}."

        # 3. Document erstellen
        doc = Document(
            text=text_content,
            metadata=metadata,
            id_=metadata['source_id'] or None,
            excluded_embed_metadata_keys=[
                'source_id', 'geo_line', 'geo_id', 'slug', 'copyright',
                'ascent', 'descent', 'min_altitude', 'max_altitude', 
                'length_m', 'duration_min', 'beds'
            ],
            excluded_llm_metadata_keys=['source_id']
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