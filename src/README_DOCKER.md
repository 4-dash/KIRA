# Monolith + OTP2 + OpenSearch (+ optional ingestion)

## Start stack
```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend WS: ws://localhost:8000/chat
- OpenSearch: http://localhost:9200
- OTP2 GraphQL: http://localhost:8080/otp/routers/default/index/graphql

## BayernCloud fetching (optional, but required if you want to ingest BayernCloud POIs)
This saves BayernCloud JSON into a shared volume mounted at `/data/bayerncloud`.

```bash
docker compose --profile ingest run --rm bayerncloud-fetch
```

## Ingest POIs into OpenSearch (manual)
Run the ingester script on demand (does **not** auto-run):

```bash
docker compose --profile ingest run --rm ingester python ingestor_v2.py
```

If `ingestor_v2.py` expects a file pattern, set:
- `BAYERNCLOUD_DATA_DIR`
- `BAYERNCLOUD_FILE_PATTERN`

in your `.env`.
