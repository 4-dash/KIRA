## WORKS

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
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient

# --- Konfiguration ---
OPENSEARCH_HOST = 'localhost'
OPENSEARCH_PORT = 9200
OPENSEARCH_AUTH = None 
INDEX_NAME = 'tourism-data-v6' # Neue Version V5
DATA_DIR = 'trip-planner'
FILE_PATTERN = 'bayerncloud*.json'
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- LlamaIndex Settings ---
logger.info(f"Lade Embedding Modell: {EMBEDDING_MODEL_NAME}...")
embed_model = HuggingFaceEmbedding(model_name=f"sentence-transformers/{EMBEDDING_MODEL_NAME}")
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
        """Erstellt den Index manuell mit FAISS, bevor LlamaIndex ihn berührt."""
        index_body = {
            "settings": {
                "index": {
                    "knn": True
                }
            },
            "mappings": {
                "properties": {
                    "description": {"type": "text"}, # Content Feld
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 384,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss"
                        }
                    },
                    # Wir mappen wichtige Metadaten explizit für Filterung
                    "source_id": {"type": "keyword"},
                    "city": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    "postal_code": {"type": "keyword"},
                    "location": {"type": "geo_point"}
                }
            }
        }

        if not self.os_client.indices.exists(index=INDEX_NAME):
            self.os_client.indices.create(index=INDEX_NAME, body=index_body)
            logger.info(f"Index '{INDEX_NAME}' erstellt.")
        else:
            logger.info(f"Index '{INDEX_NAME}' existiert bereits.")

    def parse_to_document(self, raw_doc: Dict, filename: str) -> Document:
        # 1. Text Content (Beschreibung)
        raw_desc = raw_doc.get('description', '')
        text_content = clean_html(raw_desc)
        
        # 2. Metadaten Extrahieren
        metadata = {}
        
        # Basis Infos
        metadata['source_id'] = raw_doc.get('@id')
        metadata['name'] = raw_doc.get('name', 'Unbekannt')
        metadata['type'] = derive_type_from_filename(filename)
        
        # Adresse (WICHTIG für Embedding)
        address = raw_doc.get('address', {})
        if address:
            metadata['street'] = address.get('streetAddress', '')
            metadata['postal_code'] = address.get('postalCode', '')
            metadata['city'] = address.get('addressLocality', '')
            metadata['country'] = address.get('addressCountry', '')
        
        # Kontakt (Wichtig für Agenten, aber vielleicht nicht fürs Embedding-Vektor?)
        # Wir nehmen es mit rein, falls jemand nach "Telefonnummer von X" sucht.
        metadata['website'] = raw_doc.get('url')
        metadata['telephone'] = raw_doc.get('telephone')

        # Fallback für Text: Wenn keine Beschreibung da ist, nutzen wir Name + Stadt + Typ
        if not text_content:
            text_content = f"{metadata['type']} namens {metadata['name']} in {metadata.get('city', 'Bayern')}."

        # Spezifikationen (Events, Touren etc.)
        if raw_doc.get('startDate'): metadata['startDate'] = raw_doc.get('startDate')
        if raw_doc.get('endDate'): metadata['endDate'] = raw_doc.get('endDate')
        
        # Geo Location (Für Map-Filter, nicht unbedingt fürs Embedding wichtig)
        geo = raw_doc.get('geo', {})
        lat = safe_float(geo.get('latitude'))
        lon = safe_float(geo.get('longitude'))
        if lat is not None and lon is not None:
            metadata['location'] = f"{lat},{lon}"

        # Öffnungszeiten (Stringifizieren)
        ohs = raw_doc.get('openingHoursSpecification')
        if ohs:
            # Wir kürzen es etwas, falls es extrem lang ist, oder speichern es als String
            metadata['openingHoursSpecification'] = str(ohs)[:1000] 

        # 3. Document erstellen
        # HIER PASSIERT DIE MAGIE:
        # Wir definieren NICHT 'street' oder 'city' in 'excluded_embed_metadata_keys'.
        # Das heißt: LlamaIndex schreibt "City: Oberstdorf" MIT in den Vektor!
        
        doc = Document(
            text=text_content,
            metadata=metadata,
            id_=metadata['source_id'] or None,
            
            # Was soll NICHT in den Vektor (weil es den Kontext verwässert)?
            excluded_embed_metadata_keys=[
                'source_id', 
                #'location', # Koordinaten als Zahlen verwirren das Sprachmodell oft
                'website', 
                #'openingHoursSpecification', # Zu komplexes JSON für Vektorsuche, aber gut für LLM Kontext
                'telephone' 
            ],
            
            # Was soll der LLM (GPT-4) NICHT sehen (um Token zu sparen)?
            excluded_llm_metadata_keys=[
                'source_id' 
                #'location' # Der Agent braucht meist nur den Stadtnamen, selten GPS Koordinaten
            ]
        )
        
        # Optional: Template definieren, wie der Embedding-Text aussehen soll
        # Standard ist "{key}: {value}". Wir lassen das so, das funktioniert gut.
        
        return doc

    def run(self):
        # 1. Index vorbereiten (FAISS + Mappings)
        self.create_index_if_not_exists()
        
        # 2. LlamaIndex Client verbinden
        client_wrapper = OpensearchVectorClient(
            endpoint=f"http://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}",
            index=INDEX_NAME,
            dim=384,
            embedding_field="embedding",
            text_field="description",
            method={"name": "hnsw", "engine": "faiss"}, # Wichtig!
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

        # 4. Ingestieren mit Splitter (gegen Chunk-Size Fehler)
        if all_documents:
            logger.info(f"Starte Ingestion von {len(all_documents)} Dokumenten...")
            
            # Wir nutzen einen Splitter, um sicherzugehen, dass riesige Metadaten nicht crashen
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
    # Löschen des alten Index für sauberen Start (Optional)
    # import requests
    # requests.delete(f"http://localhost:9200/{INDEX_NAME}")
    
    ingestor = RichLlamaIngestor()
    ingestor.run()