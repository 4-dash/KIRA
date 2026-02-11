import os
import logging
from opensearchpy import OpenSearch, RequestsHttpConnection

# LlamaIndex Imports
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.vector_stores import MetadataFilters, MetadataFilter
# --- NECESSARY CHANGE: Use AzureOpenAI ---
from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient

# --- Configuration ---
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
INDEX_NAME = os.getenv("POI_INDEX", "tourism-data-v9") 

# Azure Specifics (Must match Ingestion)
AZURE_OPENAI_KEY = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_DEPLOYMENT_NAME = os.getenv("AZURE_DEPLOYMENT_NAME", "")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION", "")

# text-embedding-3-large uses 3072 dimensions
EMBED_DIM = int(os.getenv("EMBED_DIM", "3072"))

logging.basicConfig(level=logging.ERROR)

# --- 1. Initialize Azure Model ---
print(f"⏳ Loading Azure Embedding Model: {AZURE_DEPLOYMENT_NAME}...")
embed_model = AzureOpenAIEmbedding(
    model="text-embedding-3-large",
    deployment_name=AZURE_DEPLOYMENT_NAME,
    api_key=AZURE_OPENAI_KEY,
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    api_version=AZURE_API_VERSION,
)
Settings.embed_model = embed_model
Settings.llm = None 

# --- 2. Connect to OpenSearch ---
print(f"🔌 Connecting to Index: {INDEX_NAME}...")
os_client = OpenSearch(
    hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
    http_auth=None,
    use_ssl=False, 
    verify_certs=False, 
    connection_class=RequestsHttpConnection
)

client_wrapper = OpensearchVectorClient(
    endpoint=f"http://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}",
    index=INDEX_NAME,
    dim=EMBED_DIM,
    embedding_field="embedding",
    text_field="description",
    os_client=os_client
)

vector_store = OpensearchVectorStore(client_wrapper)
index = VectorStoreIndex.from_vector_store(vector_store=vector_store)

# --- 3. Retrieval Function ---
def test_query(query_str, city_filter=None, top_k=3):
    print(f"\n🔎 TEST QUERY: '{query_str}' | 🌍 FILTER: {city_filter if city_filter else 'None'}")
    print("=" * 60)
    
    filters = None
    if city_filter:
        filters = MetadataFilters(
            filters=[MetadataFilter(key="city", value=city_filter)]
        )
    
    retriever = index.as_retriever(
        similarity_top_k=top_k,
        filters=filters 
    )
    
    nodes = retriever.retrieve(query_str)
    
    if not nodes:
        print(f"❌ No results found.")
        return

    for i, node in enumerate(nodes, 1):
        meta = node.metadata
        print(f"{i}. [Score: {node.score:.4f}] {meta.get('name', 'Unknown')}")
        print(f"   📍 {meta.get('city', 'Unknown City')} ({meta.get('type', 'Unknown')})")
        print(f"   📄 Content: {node.get_content()[:100]}...") 
        print("-" * 30)

# --- 4. Run the Tests ---
if __name__ == "__main__":
    # Test 1: Explicit Filter
    test_query("Italienisches Essen Pizza", city_filter="Fischen")

    # Test 2: Another City
    test_query("Wandern und Berge", city_filter="Oberstdorf")

    # Test 3: No Filter
    test_query("Schwimmbad und Sauna in Kempten")

    test_query("Quad und Wasseraktivität in Allgäu")