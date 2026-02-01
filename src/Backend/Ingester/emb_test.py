import logging
from opensearchpy import OpenSearch, RequestsHttpConnection

# LlamaIndex Imports
from llama_index.core import VectorStoreIndex, Settings
from llama_index.core.vector_stores import MetadataFilters, MetadataFilter # <--- The missing import
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.vector_stores.opensearch import OpensearchVectorStore, OpensearchVectorClient

# --- Configuration ---
OPENSEARCH_HOST = "localhost"
OPENSEARCH_PORT = 9200
INDEX_NAME = "tourism-data-v7"  # Make sure this matches your ingestion index
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2" # Must match ingestion model

# Setup Logging (Set to INFO or ERROR to reduce noise)
logging.basicConfig(level=logging.ERROR)

# --- 1. Initialize Model ---
print(f"⏳ Loading Embedding Model: {EMBEDDING_MODEL}...")
embed_model = HuggingFaceEmbedding(model_name=f"sentence-transformers/{EMBEDDING_MODEL}")
Settings.embed_model = embed_model
Settings.llm = None  # We are only testing retrieval, no generation needed

# --- 2. Connect to OpenSearch ---
print(f"🔌 Connecting to Index: {INDEX_NAME}...")
os_client = OpenSearch(
    hosts=[{'host': OPENSEARCH_HOST, 'port': OPENSEARCH_PORT}],
    http_auth=None,
    use_ssl=False, 
    verify_certs=False, 
    connection_class=RequestsHttpConnection
)

# Connect LlamaIndex to the existing vector store
client_wrapper = OpensearchVectorClient(
    endpoint=f"http://{OPENSEARCH_HOST}:{OPENSEARCH_PORT}",
    index=INDEX_NAME,
    dim=384,  # Dimension for MiniLM-L12-v2
    embedding_field="embedding",
    text_field="description",
    os_client=os_client
)

vector_store = OpensearchVectorStore(client_wrapper)

# We load the index from the store (read-only mode)
index = VectorStoreIndex.from_vector_store(vector_store=vector_store)

# --- 3. Retrieval Function with Manual Filter ---
def test_query(query_str, city_filter=None, top_k=3):
    print(f"\n🔎 TEST QUERY: '{query_str}' | 🌍 FILTER: {city_filter if city_filter else 'None'}")
    print("=" * 60)
    
    # A. Build the Filter (if a city is provided)
    filters = None
    if city_filter:
        filters = MetadataFilters(
            filters=[
                # This checks for exact match on the "city" metadata field
                MetadataFilter(key="city", value=city_filter)
            ]
        )
    
    # B. Create Retriever
    # We pass the 'filters' object directly to the retriever configuration
    retriever = index.as_retriever(
        similarity_top_k=top_k,
        filters=filters 
    )
    
    # C. Retrieve Nodes
    nodes = retriever.retrieve(query_str)
    
    if not nodes:
        print(f"❌ No results found in {city_filter or 'any city'}.")
        return

    # D. Print Results
    for i, node in enumerate(nodes, 1):
        meta = node.metadata
        score = node.score
        
        name = meta.get('name', 'Unknown Name')
        city = meta.get('city', 'Unknown City')
        street = meta.get('street', '')
        doc_type = meta.get('type', 'Unknown Type')
        
        print(f"{i}. [Score: {score:.4f}] {name}")
        print(f"   📍 {street}, {city} ({doc_type})")
        # Show a snippet of the text content to verify why it matched
        print(f"   📄 Content: {node.get_content()[:100]}...") 
        print("-" * 30)

# --- 4. Run the Tests ---
if __name__ == "__main__":
    
    # Test 1: Explicit Filter (Correct usage)
    # The Vector Search looks for "Italian Pizza"
    # The Filter strictly restricts results to "Fischen"
    test_query("Italienisches Essen Pizza", city_filter="Fischen")

    # Test 2: Another City (Optional)
    # test_query("Wandern und Berge", city_filter="Oberstdorf")

    # Test 3: No Filter (Searches everywhere)
    # test_query("Schwimmbad und Sauna")