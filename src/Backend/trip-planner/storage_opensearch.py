import os
from typing import Optional
from opensearchpy import OpenSearch

from models import Trip


OPENSEARCH_ENABLED = os.getenv("OPENSEARCH_ENABLED", "true").lower() == "true"
OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", "9200"))
OPENSEARCH_INDEX = os.getenv("OPENSEARCH_INDEX", "travel-plans")


def get_client() -> Optional[OpenSearch]:
    if not OPENSEARCH_ENABLED:
        return None

    try:
        client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            use_ssl=False,
            verify_certs=False,
        )
        return client if client.ping() else None
    except Exception:
        return None


def store_trip(trip: Trip) -> Optional[str]:
    client = get_client()
    if client is None:
        return None

    if not client.indices.exists(index=OPENSEARCH_INDEX):
        client.indices.create(index=OPENSEARCH_INDEX)

    doc_id = f"{trip.trip_id}_v{trip.version}"
    client.index(
        index=OPENSEARCH_INDEX,
        id=doc_id,
        body=trip.model_dump(mode="json"),
        refresh=True,
    )
    return doc_id
