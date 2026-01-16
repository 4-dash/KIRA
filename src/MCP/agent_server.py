import os
from dotenv import load_dotenv
from fastmcp import FastMCP
from llama_index.core import VectorStoreIndex, Document, Settings
# CHANGE 1: Import Azure OpenAI
from llama_index.llms.azure_openai import AzureOpenAI
# CHANGE 2: Import Local Embeddings (avoids needing an Azure Embedding deployment)
from llama_index.embeddings.huggingface import HuggingFaceEmbedding

# Load environment variables
load_dotenv()

# Verify keys exist
if not os.getenv("AZURE_OPENAI_API_KEY"):
    raise ValueError("AZURE_OPENAI_API_KEY is missing in .env!")

# CHANGE 3: Configure LlamaIndex to use Azure GPT-4o
llm = AzureOpenAI(
    model="gpt-4o",
    deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME", "gpt-4o"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-05-01-preview"),
    temperature=0
)

# CHANGE 4: Use a local embedding model (runs on CPU, no API cost)
# This is required because GPT-4o cannot create embeddings itself.
embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-small-en-v1.5")

# Apply settings globally
Settings.llm = llm
Settings.embed_model = embed_model

# Prepare knowledge base
documents = [
    Document(text="""
      KIRA Travel Rules: 
      - The user prefers trains over buses.
      - Standard commute time is 7:30 AM for school.       
      - The main train line in Allgäu runs between Fischen and Sonthofen.
      - OTP (OpenTripPlanner) is used for routing calculations.
      - If no route is found, check if the calendar.txt file covers the date.            
     """)
]

# Create index (This will now use the local embed_model)
print("Creating Vector Index...")
index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()

# Initialize MCP Server 
mcp = FastMCP("KIRA-Agent-Server")

@mcp.tool()
def query_travel_knowledge(question: str) -> str:
    """
    Ask KIRA travel knowledge base questions.
    Use this to look up users preferences, system rules or debugging tips.
    """
    print(f"Agent asked: {question}")
    # This query will now use your Azure GPT-4o to synthesize the answer
    response = query_engine.query(question)
    return str(response)

if __name__ == "__main__":
    print("MCP Server running with Azure GPT-4o")
    mcp.run()