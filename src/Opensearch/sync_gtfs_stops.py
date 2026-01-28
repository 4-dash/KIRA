import requests
from opensearchpy import OpenSearch, helpers

# --- Configuration ---
OTP_URL = "http://localhost:8080/otp/routers/default/index/graphql"
INDEX_NAME = "gtfs-stops"

client = OpenSearch(
    hosts=[{'host': 'localhost', 'port': 9200}],
    use_ssl=False,
    verify_certs=False
)

# Create Index with Geo-Mapping (Same as upload_infrastructure.py) 
if not client.indices.exists(index=INDEX_NAME):
    mapping = {
        "mappings": {
            "properties": {
                "name": {"type": "text", "analyzer": "standard"},
                "code": {"type": "keyword"},
                "location": {
                    "properties": {
                        "latitude": {"type": "float"},
                        "longitude": {"type": "float"},
                        "geo": {"type": "geo_point"} # Crucial for Maps
                    }
                }
            }
        }
    }
    client.indices.create(index=INDEX_NAME, body=mapping)
    print(f"Created index: {INDEX_NAME}")

#  Fetch Data from OTP2 (GraphQL) 
query = """
{
  stops {
    gtfsId
    name
    code
    lat
    lon
  }
}
"""

print("Fetching stops from OTP2...")
try:
    response = requests.post(OTP_URL, json={'query': query})
    if response.status_code != 200:
        raise Exception(f"OTP Error: {response.text}")
    
    stops = response.json()['data']['stops']
    print(f"Found {len(stops)} stops. Indexing to OpenSearch...")

    # Prepare Bulk Upload 
    actions = []
    for stop in stops:
        # Construct the document to match your Infrastructure style
        doc = {
            "_index": INDEX_NAME,
            "_id": stop['gtfsId'],
            "_source": {
                "name": stop['name'],
                "code": stop['code'],
                "location": {
                    "latitude": stop['lat'],
                    "longitude": stop['lon'],
                    # The specific format your frontend/maps expect:
                    "geo": f"{stop['lat']},{stop['lon']}"
                }
            }
        }
        actions.append(doc)

    #  Upload
    success, failed = helpers.bulk(client, actions)
    print(f"Success! Indexed {success} stops.")

except Exception as e:
    print(f"Connection Error: {e}")
    print("Ensure SSH Tunnel is running for ports 8080 and 9200.")