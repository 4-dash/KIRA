# Opensearch/sync_gtfs_stops.py
import os
import requests
from opensearchpy import OpenSearch, helpers

# --- Configuration (Docker-friendly) ---
INDEX_NAME = os.getenv("GTFS_STOPS_INDEX", "gtfs-stops")

OTP_URL = os.getenv(
    "OTP_URL",
    "http://otp:8080/otp/routers/default/index/graphql",  # Docker default
)

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "opensearch")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))

client = OpenSearch(
    hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
    use_ssl=False,
    verify_certs=False,
)

# Create Index with Geo-Mapping
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
                        "geo": {"type": "geo_point"},
                    }
                },
            }
        }
    }
    client.indices.create(index=INDEX_NAME, body=mapping)
    print(f"Created index: {INDEX_NAME}")

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
try:
    print(f"Fetching stops from OTP2: {OTP_URL}")
    response = requests.post(OTP_URL, json={"query": query}, timeout=60)
    response.raise_for_status()

    data = response.json()
    stops = data["data"]["stops"]
    print(f"Found {len(stops)} stops. Indexing to OpenSearch...")

    actions = []
    for stop in stops:
        actions.append(
            {
                "_index": INDEX_NAME,
                "_id": stop["gtfsId"],
                "_source": {
                    "name": stop["name"],
                    "code": stop["code"],
                    "location": {
                        "latitude": stop["lat"],
                        "longitude": stop["lon"],
                        "geo": f'{stop["lat"]},{stop["lon"]}',
                    },
                },
            }
        )

    success, failed = helpers.bulk(client, actions)
    print(f"Success! Indexed {success} stops.")

except Exception as e:
    print(f"Connection Error: {e}")
    print("Ensure SSH Tunnel is running for ports 8080 and 9200.")