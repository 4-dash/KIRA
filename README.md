
# Installing Dependencies
- Create virtual envitonment with `python -m venv .venv`

- First install uv for package management `pip install uv`

- Then install with `uv sync`

**DO NOT edit *uv.lock* manually!!!**

Use `uv lock` to change uv.lock automatically.

- In DEV mode:
    to start `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d`

    to stop `docker-compose -f docker-compose.yml -f docker-compose.dev.yml down`

    - To run your Fetch and Ingester (Base + Prod + Ingest Profile):
        `docker-compose -f docker-compose.yml -f docker-compose.dev.yml --profile ingest run --rm bayerncloud-fetch`

        `docker-compose -f docker-compose.yml -f docker-compose.dev.yml --profile ingest run --rm ingester python ingestor_v2.py`

- In PROD mode (on the VM):
    First, ensure you have nginx_proxy network: `docker network create nginx_proxy`

    to start `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d`

    to stop `docker-compose -f docker-compose.yml -f docker-compose.prod.yml down`

    - To run your Fetch and Ingester (Base + Prod + Ingest Profile):
        `docker-compose -f docker-compose.yml -f docker-compose.prod.yml --profile ingest run --rm bayerncloud-fetch`

        `docker-compose -f docker-compose.yml -f docker-compose.prod.yml --profile ingest run --rm ingester python ingestor_v2.py`
