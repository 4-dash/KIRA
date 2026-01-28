import os
import json
import glob
import logging
from typing import Dict, Any, List

from bs4 import BeautifulSoup
from opensearchpy import OpenSearch, helpers, RequestsHttpConnection
from sentence_transformers import SentenceTransformer

# --- Configuration ---
OPENSEARCH_HOST = 'localhost'
OPENSEARCH_PORT = 9200
OPENSEARCH_AUTH = None  # No auth needed for your Docker setup
INDEX_NAME = 'tourism-data-v2'
DATA_DIR = 'trip-planner'
FILE_PATTERN = 'bayerncloud*.json'
EMBEDDING_MODEL_NAME = 'all-MiniLM-L6-v2'

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def clean_html(text: str) -> str:
    """Strips HTML tags and converts entities."""
    if not text:
        return None
    try:
        soup = BeautifulSoup(text, "lxml") 
        return soup.get_text(separator=" ").strip()
    except Exception:
        return text

def safe_float(value):
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def derive_type_from_filename(filename: str) -> str:
    """
    Converts 'bayerncloud_list_attractions.json' -> 'Attractions'
    Converts 'bayerncloud_list_food.json' -> 'Food'
    """
    base = os.path.basename(filename)
    name_without_ext = os.path.splitext(base)[0] # bayerncloud_list_attractions
    
    # Split by underscore and grab the last part
    parts = name_without_ext.split('_')
    if parts:
        return parts[-1].capitalize() # "Attractions"
    return "Unknown"

# --- Main Ingestion Class ---

class TourismIngestor:
    def __init__(self):
        # Initialize OpenSearch Client (HTTP, No Auth)
        self.client = OpenSearch(
            hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
            http_auth=OPENSEARCH_AUTH,
            use_ssl=False, 
            verify_certs=False,
            connection_class=RequestsHttpConnection
        )
        
        # Initialize Embedding Model
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}...")
        self.model = SentenceTransformer(EMBEDDING_MODEL_NAME)
        
    def create_index_if_not_exists(self):
        """Creates the OpenSearch index with Faiss engine."""
        index_body = {
            "settings": {
                "index": {
                    "knn": True
                }
            },
            "mappings": {
                "properties": {
                    "source_id": {"type": "keyword"},
                    "type": {"type": "keyword"}, # Now holds 'Attractions', 'Events', etc.
                    "name": {"type": "text"},
                    "description": {"type": "text"},
                    "slug": {"type": "keyword"},
                    "location": {"type": "geo_point"},
                    "route_geometry": {"type": "geo_shape"},
                    "startDate": {"type": "date"},
                    "endDate": {"type": "date"},
                    # Vector Field
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": 384,
                        "method": {
                            "name": "hnsw",
                            "engine": "faiss" # Fixed for OS 2.12+ / 3.x
                        }
                    }
                }
            }
        }

        if not self.client.indices.exists(index=INDEX_NAME):
            self.client.indices.create(index=INDEX_NAME, body=index_body)
            logger.info(f"Index '{INDEX_NAME}' created.")
        else:
            logger.info(f"Index '{INDEX_NAME}' already exists.")

    def transform_document(self, raw_doc: Dict, filename: str) -> Dict:
        """Maps raw JSON-LD fields to the OpenSearch schema."""
        
        mapped = {}
        
        # 1. Type Mapping (Based on Filename)
        mapped['type'] = derive_type_from_filename(filename)

        # 2. Core Fields
        mapped['source_id'] = raw_doc.get('@id')
        mapped['name'] = raw_doc.get('name')
        
        # Clean HTML from description
        raw_desc = raw_doc.get('description', '')
        mapped['description'] = clean_html(raw_desc)
        
        mapped['slug'] = raw_doc.get('dc:slug')
        mapped['classification'] = raw_doc.get('classification')
        mapped['is_multilingual'] = raw_doc.get('multilingual')

        # Content Score
        content_scores = raw_doc.get('dc:contentScore')
        if isinstance(content_scores, list) and content_scores:
             mapped['quality_score'] = safe_float(content_scores[0].get('value'))
        elif isinstance(content_scores, dict):
             mapped['quality_score'] = safe_float(content_scores.get('value'))
        else:
             mapped['quality_score'] = None

        # 3. Contact & Address
        address = raw_doc.get('address', {})
        if address:
            mapped['street'] = address.get('streetAddress')
            mapped['postal_code'] = address.get('postalCode')
            mapped['city'] = address.get('addressLocality')
            mapped['country'] = address.get('addressCountry')
        else:
            mapped['street'] = mapped['postal_code'] = mapped['city'] = mapped['country'] = None

        mapped['telephone'] = raw_doc.get('telephone')
        mapped['email'] = raw_doc.get('email')
        mapped['website'] = raw_doc.get('url')

        # 4. Geo-Spatial
        geo = raw_doc.get('geo', {})
        lat = safe_float(geo.get('latitude'))
        lon = safe_float(geo.get('longitude'))
        
        if lat is not None and lon is not None:
            mapped['location'] = {'lat': lat, 'lon': lon}
        else:
            mapped['location'] = None
            
        mapped['elevation'] = safe_float(raw_doc.get('elevation'))

        # Route Geometry
        raw_line = raw_doc.get('line')
        if raw_line and isinstance(raw_line, dict) and 'type' in raw_line:
             mapped['route_geometry'] = raw_line
        else:
            mapped['route_geometry'] = None

        # 5. Type-Specific Details
        mapped['startDate'] = raw_doc.get('startDate')
        mapped['endDate'] = raw_doc.get('endDate')
        mapped['eventSchedule'] = raw_doc.get('eventSchedule')
        mapped['organizer'] = raw_doc.get('organizer')
        
        # Tours/Tracks
        mapped['length'] = safe_float(raw_doc.get('length'))
        mapped['ascent'] = safe_float(raw_doc.get('ascent'))
        mapped['descent'] = safe_float(raw_doc.get('descent'))
        mapped['minAltitude'] = safe_float(raw_doc.get('minAltitude'))
        mapped['maxAltitude'] = safe_float(raw_doc.get('maxAltitude'))
        mapped['duration'] = safe_float(raw_doc.get('duration'))
        mapped['instructions'] = clean_html(raw_doc.get('instructions'))
        mapped['safetyInstructions'] = clean_html(raw_doc.get('safetyInstructions'))
        mapped['equipment'] = clean_html(raw_doc.get('equipment'))
        mapped['aggregateRating'] = raw_doc.get('aggregateRating')

        # Ski/Infra
        mapped['seasonStart'] = raw_doc.get('seasonStart')
        mapped['seasonEnd'] = raw_doc.get('seasonEnd')
        mapped['openingStatus'] = raw_doc.get('openingStatus')

        # Business
        ohs = raw_doc.get('openingHoursSpecification')
        mapped['openingHoursSpecification'] = str(ohs) if ohs else None
        
        # --- REMOVED FIELDS: logo, potentialAction ---

        # 6. Generate Embedding
        text_content = f"{mapped['name'] or ''} {mapped['description'] or ''}".strip()
        if text_content:
            embedding = self.model.encode(text_content)
            mapped['embedding'] = embedding.tolist()
        else:
            mapped['embedding'] = None

        return mapped

    def run(self):
        self.create_index_if_not_exists()
        
        file_path_pattern = os.path.join(DATA_DIR, FILE_PATTERN)
        files = glob.glob(file_path_pattern)
        
        if not files:
            logger.warning(f"No files found matching {file_path_pattern}")
            return

        logger.info(f"Found {len(files)} files to process.")

        for file_path in files:
            try:
                logger.info(f"Processing file: {file_path}")
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                items = []
                if isinstance(data, dict):
                    if '@graph' in data:
                        items = data['@graph']
                    else:
                        items = [data]
                elif isinstance(data, list):
                    items = data

                actions = []
                for item in items:
                    try:
                        # PASSING FILENAME HERE TO EXTRACT TYPE
                        doc = self.transform_document(item, file_path)
                        
                        if doc['source_id']:
                            action = {
                                "_index": INDEX_NAME,
                                "_id": doc['source_id'], 
                                "_source": doc
                            }
                            actions.append(action)
                    except Exception as e:
                        logger.error(f"Error transforming item in {file_path}: {e}")
                        continue

                if actions:
                    success, failed = helpers.bulk(self.client, actions, stats_only=True)
                    logger.info(f"Ingested {success} documents. Failed: {failed}")
                else:
                    logger.info(f"No valid documents found in {file_path}")

            except json.JSONDecodeError:
                logger.error(f"File {file_path} is not valid JSON. Skipping.")
            except Exception as e:
                logger.error(f"Critical error processing {file_path}: {e}")

if __name__ == "__main__":
    ingestor = TourismIngestor()
    ingestor.run()