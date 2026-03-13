# KIRA - AI-Assisted Trip Planner Documentation

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Technology Stack](#technology-stack)
4. [Directory Structure](#directory-structure)
5. [Components Overview](#components-overview)
6. [Setup & Installation](#setup--installation)
7. [Configuration](#configuration)
8. [Running the Application](#running-the-application)
9. [API Endpoints](#api-endpoints)
10. [Data Flow & Integration](#data-flow--integration)
11. [Development Guide](#development-guide)
12. [Docker Setup](#docker-setup)
13. [Testing](#testing)
14. [Troubleshooting](#troubleshooting)
15. [Deployment](#deployment)

---

## Project Overview

**KIRA** is an AI-assisted trip planner specifically designed for the Allgäu region in Bavaria, Germany. It combines modern web technologies with artificial intelligence to help users plan personalized itineraries, discover tourist attractions, and find optimal transportation routes.

### Key Features

- **AI-Powered Chat Interface**: Natural language interaction with Azure OpenAI LLM
- **Intelligent Trip Planning**: Generate multi-day itineraries with activities
- **Smart Route Planning**: Integration with Open Trip Planner (OTP) for public transport optimization
- **POI Discovery**: Vector-based search for Points of Interest (tourism data)
- **Multi-modal Transportation**: Support for various transport modes (bus, train, walking, etc.)
- **Session-Based State Management**: Persistent user journey tracking
- **Docker-Based Deployment**: Fully containerized microservices architecture

### Project Metadata

```
Name: kira
Version: 1.0.0
Description: AI-assisted trip planner
Python Version: >=3.14
License: See LICENSE file
```

---

## Architecture

KIRA uses a **microservices architecture** with the following main components:

```
┌─────────────────────────────────────────────────────────────┐
│                      Frontend (React)                        │
│                    (Vite + Tailwind CSS)                    │
└────────────────┬────────────────────────────────────────────┘
                 │
                 │ HTTP/WebSocket
                 ▼
┌─────────────────────────────────────────────────────────────┐
│                  Backend API (FastAPI)                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │  Trip Routes │ │ POI Search   │ │  Session Mgmt│         │
│  └──────────────┘ └──────────────┘ └──────────────┘         │
└────┬──────────────┬──────────────┬──────────────────────────┘
     │              │              │
┌────▼────┐  ┌─────▼────┐   ┌──────▼──────┐
│   MCP   │  │ OpenSearch│  │   OTP 2.0   │
│ Agent   │  │ (Vector   │  │  (Routing)  │
│ Server  │  │ Database) │  │             │
└─────────┘  └───────────┘  └─────────────┘
     │
┌────▼────────────────────────────────────┐
│  Azure OpenAI (gpt-4o, Embeddings)     │
└─────────────────────────────────────────┘
```

### Component Interaction Flow

1. **Frontend** sends user queries via HTTP/WebSocket to Backend
2. **Backend API** receives requests and manages sessions
3. **MCP Agent Server** processes queries using Azure OpenAI LLM
4. **OpenSearch** provides vector similarity search for POIs
5. **OTP Server** calculates optimal routes and transport options
6. **Backend** aggregates results and returns to Frontend

---

## Technology Stack

### Backend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Framework | FastAPI | 0.128.0 | Web API framework |
| Server | Uvicorn | 0.40.0 | ASGI server |
| LLM Integration | Azure OpenAI | Latest | AI/LLM capabilities |
| Vector Store | OpenSearch | 2.11.1 | Vector database for embeddings |
| Embeddings | LlamaIndex + Azure OpenAI | Latest | Text embeddings for similarity search |
| Data Indexing | LlamaIndex | >=0.14.13 | Document indexing framework |
| HTTP Client | httpx | 0.28.1 | Async HTTP requests |
| Validation | Pydantic | 2.12.5 | Data validation |
| Environment | python-dotenv | >=1.2.1 | Configuration management |

### Frontend

| Component | Technology | Version | Purpose |
|-----------|-----------|---------|---------|
| Framework | React | 18.2.0 | UI framework |
| Build Tool | Vite | 5.0.0 | Fast build tool |
| Styling | Tailwind CSS | 4.0.0 | Utility-first CSS |
| Icons | Lucide React | 0.300.0 | React icon library |
| Dev Tools | npm | Latest | Package management |

### Infrastructure

| Service | Technology | Version | Purpose |
|---------|-----------|---------|---------|
| Router | OTP (Open Trip Planner) | 2.8.1 | Route planning & transit data |
| Database | OpenSearch | 2.11.1 | Vector & search database |
| Dashboard | OpenSearch Dashboards | 2.11.1 | Data visualization |
| Proxy | Nginx | Latest | Reverse proxy & load balancing |
| Container | Docker | Latest | Containerization |
| Orchestration | Docker Compose | Latest | Service orchestration |

### AI/ML Services

| Service | Purpose | Configuration |
|---------|---------|---------------|
| Azure OpenAI | LLM (gpt-4o) | Deployment-based, API key required |
| Azure Embeddings | Text embeddings (text-embedding-3-large) | 3072-dimensional vectors |
| HuggingFace | Alternative embeddings | Optional fallback |

---

## Directory Structure

```
KIRA (root)
├── LICENSE                          # Project license
├── README.md                        # Setup instructions
├── CODEBASE_DOCUMENTATION.md        # This file
├── pyproject.toml                   # Python project configuration (uv + pytest)
├── src/                             # Source code root
│   ├── __init__.py
│   ├── .env                         # Environment variables (DO NOT COMMIT)
│   ├── .env.example                 # Example environment template
│   ├── requirements.txt             # Root level dependencies
│   ├── docker-compose.yml           # Base docker-compose config
│   ├── docker-compose.dev.yml       # Development overlay
│   ├── docker-compose.prod.yml      # Production overlay
│   ├── Backend/                     # FastAPI backend application
│   │   ├── __init__.py
│   │   ├── api.py                   # Main FastAPI application & routes
│   │   ├── Dockerfile              # Backend container definition
│   │   ├── api_gateway/             # API gateway placeholder
│   │   ├── Ingester/                # Data ingestion pipeline
│   │   │   ├── __init__.py
│   │   │   ├── Dockerfile          # Ingester container
│   │   │   ├── requirements.txt      # Ingester dependencies
│   │   │   ├── ingestor_v2.py       # Main ingestion script
│   │   │   ├── bayerncloud_fetch.py # BayernCloud data fetcher
│   │   │   ├── gntb_fetch_allgaeu.py# GNTB/DZT data fetcher
│   │   │   ├── gntb_transform.py    # GNTB data transformer
│   │   │   ├── emb_test.py          # Embedding testing utility
│   │   │   ├── ingest_with_llamaindex.py  # LlamaIndex ingestion
│   │   │   └── sync_gtfs_stops.py   # GTFS stop synchronization
│   │   └── trip_planner/            # Trip planning logic (placeholder)
│   ├── Frontend/                    # React frontend application
│   │   ├── App.jsx                  # Main React component
│   │   ├── main.jsx                 # Entry point
│   │   ├── App.css                  # App styles
│   │   ├── index.css                # Global styles
│   │   ├── index.html               # HTML template
│   │   ├── Dockerfile              # Frontend container
│   │   ├── nginx.conf               # Nginx configuration
│   │   ├── vite.config.js           # Vite configuration
│   │   ├── tailwind.config.js       # Tailwind CSS config
│   │   ├── package.json             # Frontend dependencies
│   │   ├── .dockerignore            # Docker ignore patterns
│   │   └── assets/                  # Static assets
│   ├── MCP/                         # Model Context Protocol servers
│   │   ├── __init__.py
│   │   ├── agent_server.py          # MCP agent with FastMCP
│   │   ├── backend_api.py           # MCP backend API client
│   │   ├── find_kempten.py          # OTP connectivity test utility
│   │   └── mcp_azure_host.py        # Azure hosting configuration
│   ├── Opensearch/                  # OpenSearch utilities
│   │   ├── plan_trip_robust.py      # Trip planning with OpenSearch
│   │   ├── sync_gtfs_stops.py       # GTFS stop syncing
│   │   ├── upload_infrastructure.py # Infrastructure data uploader
│   │   └── upload_plan.py           # Trip plan uploader
│   ├── otp-data/                    # OTP server data
│   │   ├── router-config.json       # OTP router configuration
│   │   └── .gitkeep
│   ├── nginx/                       # Nginx configuration
│   │   └── conf.d/
│   │       └── default.conf         # Default nginx config
│   ├── Docker/                      # Docker compose files (root level)
│   │   └── docker-compose.yml       # Additional compose config
│   └── README_DOCKER.md             # Docker usage guide
├── tests/                           # Test suite
│   ├── conftest.py                  # Pytest configuration & fixtures
│   ├── backend/                     # Backend tests
│   │   ├── __init__.py
│   │   ├── api_gateway/
│   │   │   ├── __init__.py
│   │   │   └── test_api_gateway.py  # API gateway tests
│   │   ├── Ingester/                # Ingester tests
│   │   ├── opensearch/              # OpenSearch tests
│   │   └── trip_planner/            # Trip planner tests
│   ├── integration/                 # Integration tests
│   └── MCP/                         # MCP tests
└── docs/                            # Additional documentation (if exists)
```

---

## Components Overview

### 1. Backend API (`src/Backend/api.py`)

**Purpose**: FastAPI application serving as the main backend service

#### Key Features:
- **Session Management**: Manages user sessions with state tracking
- **POI Search**: Geographic-based search for Points of Interest
- **Trip Planning**: Orchestrates trip planning through MCP agent
- **WebSocket Support**: Real-time communication with frontend
- **CORS**: Cross-Origin Resource Sharing for frontend communication

#### Key Models:
```python
class PoiSearchRequest(BaseModel):
    north: float           # Bounding box north latitude
    south: float           # Bounding box south latitude
    east: float            # Bounding box east longitude
    west: float            # Bounding box west longitude
    limit: int = 300       # Max results (1-500)
    category: Optional[str]  # POI category filter
    exclude_names: List[str] # Exclude specific POIs
    include_names: List[str] # Include specific POIs
    trip_mode: str         # Trip planning mode

class AddPoiRequest(BaseModel):
    session_id: Optional[str]  # User session ID
    poi: Dict[str, Any]        # POI data
    day_index: Optional[int]   # Day in itinerary
```

#### Main Routes:
- POI search and filtering
- Trip planning initiation
- Session state management
- Activity planning
- Journey route calculation

#### Integration Points:
- **MCP Agent Server**: For LLM-powered planning
- **OpenSearch**: For POI retrieval
- **OTP Server**: For route planning
- **Azure OpenAI**: For embeddings and LLM

#### Configuration:
```python
OPENSEARCH_HOST = "opensearch"  # OpenSearch hostname
OPENSEARCH_PORT = 9200          # OpenSearch port
OTP_URL = "http://otp:8080/otp/routers/default/index/graphql"
POI_INDEX = "tourism-data-v7"   # Vector index name
```

### 2. Frontend (`src/Frontend/`)

**Purpose**: React-based user interface for KIRA

#### Architecture:
- **Single Page Application (SPA)** using Vite
- **Component-Based UI** with React hooks
- **Tailwind CSS** for responsive styling
- **Lucide Icons** for UI elements
- **WebSocket** integration for real-time updates

#### Key Features:
- **Chat Interface**: Interactive conversation with AI
- **Trip Visualization**: Display itineraries with activities
- **Map Integration**: Geographic POI display
- **Activity Management**: Add/edit/remove activities
- **JSON Import/Export**: Save and load trips

#### Main Component Hierarchy:
```
App.jsx (Main Component)
├── Chat Interface
├── Trip Display
├── Activity Panel
├── Map View
└── Control Panel
```

#### State Management:
- Sessions stored in browser
- WebSocket connection to backend for real-time updates
- Message history and trip state

#### Key Functions:
```javascript
// URL detection for backend
getBackendBaseUrl()

// JSON parsing helper
safeJsonParse(value)

// WebSocket communication
handleWebSocketMessage()
```

#### Styling:
- Tailwind CSS utility classes
- Custom CSS in `App.css` and `index.css`
- Responsive design for mobile/desktop
- Dark mode support (configurable)

### 3. MCP Agent Server (`src/MCP/agent_server.py`)

**Purpose**: Model Context Protocol server implementing trip planning logic

#### Framework: **FastMCP** (Fast Model Context Protocol)

#### Key Functions:

1. **find_best_city_logic()**
   - Determines optimal city based on user preferences
   - Uses LLM reasoning with geography constraints
   - Returns city coordinates and metadata

2. **plan_activities_logic()**
   - Generates activity suggestions using LLM
   - Filters by location, time, category
   - Returns time-optimized activity list

3. **plan_journey_logic()**
   - Plans single-leg transportation routes
   - Uses OTP GraphQL API for routing
   - Considers departure times and transport modes

4. **plan_multiday_trip_logic()**
   - Creates multi-day itineraries
   - Integrates activities with journeys
   - Returns complete day-by-day plans

5. **plan_complete_trip_logic()**
   - Orchestrates entire trip planning
   - Combines city selection, activities, and journeys
   - Returns end-to-end iterary

#### Configuration:
```python
OTP_URL = "http://otp:8080/otp/routers/default/index/graphql"
OPENSEARCH_HOST = "opensearch"
OPENSEARCH_PORT = 9200
INDEX_NAME = "tourism-data-v7"
```

#### LLM Setup:
```python
llm = AzureOpenAI(
    model="gpt-4o",
    deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version="2024-05-01-preview",
    temperature=0  # Deterministic responses
)
```

### 4. Data Ingester (`src/Backend/Ingester/`)

**Purpose**: Multi-source data ingestion pipeline for tourism data

#### Main Script: `ingestor_v2.py`

**Functionality**:
- Loads tourism data into OpenSearch vector index
- Supports multiple data sources:
  - **BayernCloud**: Bavaria tourism database
  - **GNTB**: German National Tourism Board data
- Creates embeddings using Azure OpenAI
- Handles document chunking and indexing

#### Source-Specific Fetchers:

**1. BayernCloud (`bayerncloud_fetch.py`)**
- Fetches data via BayernCloud API
- Endpoint IDs configuration
- Supports pagination and filtering
- Extracts and transforms POI data

**2. GNTB (`gntb_fetch_allgaeu.py`)**
- Fetches DZT Knowledge Graph objects
- Geographic filtering (Allgäu region)
- Supports proxy-based access
- Configurable page size and delays

**3. GNTB Transform (`gntb_transform.py`)**
- Transforms GNTB JSON-LD format
- Extracts name, description, location
- Normalizes data structure

#### Embedding Configuration:
```python
embed_model = AzureOpenAIEmbedding(
    model="text-embedding-3-large",
    deployment_name=os.getenv("AZURE_DEPLOYMENT_NAME_EMB"),
    api_key=os.getenv("AZURE_OPENAI_API_KEY_EMB"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT_EMB"),
    api_version=os.getenv("AZURE_API_VERSION_EMB"),
)

Settings.embed_model = embed_model
Settings.chunk_size = 2048
Settings.chunk_overlap = 50
```

#### Index Management:
- Vector index: `tourism-data-v7`
- Map index: `poi-data`
- Metadata: Category, location, description, images

### 5. OpenSearch Integration (`src/Opensearch/`)

**Purpose**: Vector database utilities and data management

#### Key Scripts:

1. **plan_trip_robust.py**
   - Robust trip planning with error handling
   - Pydantic models for data validation
   - Trip structure:
     ```
     Trip
     ├── Trip ID and Metadata
     ├── Multi-Day Structure
     │   └── Day
     │       ├── Activities
     │       └── Legs (Transportation)
     └── Duration and Travelers
     ```

2. **sync_gtfs_stops.py**
   - Synchronizes GTFS (General Transit Feed Specification) stops
   - Updates stop database from GTFS feeds
   - Ensures transport network is current

3. **upload_infrastructure.py**
   - Uploads infrastructure data to OpenSearch
   - Handles transportation network data

4. **upload_plan.py**
   - Saves generated trip plans to OpenSearch
   - Enables plan persistence and retrieval

### 6. Docker Configuration

#### Main Compose File: `docker-compose.yml`

**Services**:

**OTP Server**
```yaml
- Image: opentripplanner/opentripplanner:2.8.1
- Port: 8080
- Purpose: Route planning and public transport data
- Memory: 10GB allocated
```

**OpenSearch**
```yaml
- Image: opensearchproject/opensearch:2.11.1
- Port: 9200
- Purpose: Vector/search database
- Security: Disabled (dev mode)
- Memory: 512MB-1GB
```

**OpenSearch Dashboards**
```yaml
- Image: opensearchproject/opensearch-dashboards:2.11.1
- Port: 5601
- Purpose: Data visualization and management
```

**Backend (FastAPI)**
```yaml
- Build: ./Backend/Dockerfile
- Port: 8000
- Depends: OTP, OpenSearch
- Environment: URLs for coordinating services
```

**Frontend (React)**
```yaml
- Build: ./Frontend/Dockerfile
- Port: 5173 (dev) or 80 (prod)
- Depends: Backend
```

**Ingester**
```yaml
- Profile: ingest
- Purpose: Data loading (not auto-run)
- Manual invocation via docker-compose
```

#### Development Overlay: `docker-compose.dev.yml`

Adds:
- Port exposure for all services
- Shared volume for code (hot reload capability)
- Development-specific environment variables
- Ingester profile enabled

#### Production Overlay: `docker-compose.prod.yml`

Adds:
- Nginx proxy integration
- Environment-specific secrets
- Resource limits
- Health checks
- No port exposure for internal services

---

## Setup & Installation

### Prerequisites

- **Python**: 3.14 or higher
- **Node.js**: 16+ (for frontend)
- **Docker**: Latest version
- **Docker Compose**: 2.0+
- **uv**: Package manager
- **Git**: Version control

### Step 1: Clone Repository

```bash
git clone <repository-url>
cd KIRA
```

### Step 2: Create Python Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### Step 3: Install uv Package Manager

```bash
pip install uv
```

### Step 4: Install Dependencies

```bash
uv sync
```

**Important**: Do not manually edit `uv.lock` file. Use `uv lock` command to update:
```bash
uv lock      # Update dependencies
uv sync      # Sync with lock file
```

### Step 5: Environment Configuration

```bash
cp .env.example .env
# Edit .env with your configuration (see Configuration section)
```

### Step 6: Verify Installation

```bash
# Test Python environment
python --version

# Test uv
uv --version

# Test Docker
docker --version
docker-compose --version
```

---

## Configuration

### Environment Variables

Create `.env` file in `src/` directory based on `.env.example`:

#### Azure OpenAI Configuration
```env
# LLM Configuration (gpt-4o)
AZURE_OPENAI_ENDPOINT=https://<resource-name>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_API_VERSION=2024-05-01-preview
AZURE_DEPLOYMENT_NAME=gpt-4o

# Embedding Configuration
AZURE_EMBED_ENDPOINT=https://<resource-name>.openai.azure.com/
AZURE_DEPLOYMENT_NAME_EMBED=text-embedding-3-large
AZURE_API_VERSION_EMBED=2024-02-01
EMBED_DIM=3072
```

#### OpenSearch Configuration
```env
OPENSEARCH_HOST=opensearch      # Use service name in Docker
OPENSEARCH_PORT=9200
POI_INDEX=tourism-data-v7       # Vector index name
POI_MAP_INDEX=poi-data          # Map index name
```

#### OTP (Open Trip Planner) Configuration
```env
OTP_URL=http://otp:8080/otp/routers/default/index/graphql
```

#### Data Source Configuration

**BayernCloud**:
```env
BAYERNCLOUD_API_KEY=<your-api-key>
BAYERNCLOUD_API_BASE_URL=https://...
BAYERNCLOUD_DATA_DIR=/data/bayerncloud
BAYERNCLOUD_FILE_PATTERN=*.json
BAYERNCLOUD_PAGE_SIZE=100
```

**GNTB (DZT)**:
```env
GNTB_API_KEY=<your-api-key>
GNTB_BASE_URL=https://proxy.opendatagermany.io/api/ts/v2/kg/things
GNTB_DATA_DIR=/data/gntb
GNTB_GEO_LAT=47.7264          # Allgäu center latitude
GNTB_GEO_LON=10.3175          # Allgäu center longitude
GNTB_GEO_DISTANCE=60           # Search radius in km
GNTB_PAGE_SIZE=50
GNTB_FETCH_DELAY=0.15
GNTB_PAGE_DELAY=0.5
```

#### Ingestion Configuration
```env
INGEST_SOURCES=bayerncloud,gntb  # Comma-separated sources
```

### Docker Network

For production, ensure nginx_proxy network exists:
```bash
docker network create nginx_proxy
```

---

## Running the Application

### Development Mode

#### Step 1: Start Docker Services

```bash
cd src/
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

This starts:
- OTP Server (port 8080)
- OpenSearch (port 9200)
- OpenSearch Dashboards (port 5601)
- Backend API (port 8000)
- Frontend (port 5173)

#### Step 2: Verify Services

```bash
# Check container status
docker-compose ps

# Check OpenSearch health
curl http://localhost:9200/_cluster/health

# Check OTP availability
curl http://localhost:8080/otp/routers/default/index

# Backend API
curl http://localhost:8000/docs  # Swagger UI
```

#### Step 3: Access Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **OpenSearch Dashboards**: http://localhost:5601

#### Step 4: Stop Services

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml down
```

### Running Data Ingestion

**Load BayernCloud Data**:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml \
  --profile ingest run --rm bayerncloud-fetch
```

**Ingest Data into OpenSearch**:
```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml \
  --profile ingest run --rm ingester python ingestor_v2.py
```

### Production Mode

#### Step 1: Prepare Environment

```bash
cd src/
docker network create nginx_proxy  # If not exists
```

#### Step 2: Start Services

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

#### Step 3: Check Status

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

#### Step 4: Stop Services

```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml down
```

---

## API Endpoints

### Core Endpoints

#### 1. POI Search

**Endpoint**: `POST /poi/search`

**Request**:
```json
{
  "north": 48.5,
  "south": 47.0,
  "east": 11.0,
  "west": 9.5,
  "limit": 50,
  "category": "museum",
  "exclude_names": [],
  "include_names": [],
  "trip_mode": "all"
}
```

**Response**:
```json
{
  "pois": [
    {
      "id": "poi-123",
      "name": "Museum Name",
      "category": "museum",
      "lat": 47.73,
      "lon": 10.31,
      "description": "...",
      "rating": 4.5
    }
  ],
  "total": 42
}
```

**Status Codes**:
- `200`: Success
- `400`: Invalid bounding box
- `500`: Server error

#### 2. Add POI to Session

**Endpoint**: `POST /add-poi`

**Request**:
```json
{
  "session_id": "session-123",
  "poi": {
    "id": "poi-456",
    "name": "Activity",
    "lat": 47.73,
    "lon": 10.31
  },
  "day_index": 0
}
```

**Response**:
```json
{
  "success": true,
  "message": "POI added to day 0"
}
```

#### 3. Plan Complete Trip

**Endpoint**: `POST /plan-complete-trip`

**Request**:
```json
{
  "session_id": "session-123",
  "preferences": {
    "start_city": "Kempten",
    "duration_days": 3,
    "activities": ["hiking", "culture"],
    "budget": "moderate"
  }
}
```

**Response**:
```json
{
  "trip_id": "trip-789",
  "days": [
    {
      "date": "2025-03-14",
      "activities": [...],
      "journeys": [...]
    }
  ]
}
```

#### 4. WebSocket Connection

**Endpoint**: `WebSocket /ws/{session_id}`

Real-time communication for:
- Live trip updates
- Progress tracking
- Error notifications

**Message Format**:
```json
{
  "type": "message|update|error",
  "content": "...",
  "session_id": "session-123"
}
```

#### 5. Session Management

**Create Session**: `POST /session/create`
**Get Session**: `GET /session/{session_id}`
**Update Session**: `POST /session/{session_id}/update`

### Documentation

Access interactive API documentation:
```
http://localhost:8000/docs  # Swagger UI
http://localhost:8000/redoc # ReDoc UI
```

---

## Data Flow & Integration

### 1. User Query Flow

```
User Input (Chat)
    ↓
Frontend WebSocket
    ↓
Backend Session Handler
    ↓
MCP Agent Server (FastMCP)
    ↓
Azure OpenAI LLM Analysis
    ↓
Backend Logic Functions
    ├─ find_best_city_logic()
    ├─ plan_activities_logic()
    ├─ plan_journey_logic()
    └─ plan_multiday_trip_logic()
    ↓
OpenSearch & OTP Integration
    ├─ Vector Search (POI)
    ├─ GraphQL Route Planning
    └─ GTFS Data Retrieval
    ↓
Data Aggregation
    ↓
Frontend Display
```

### 2. Data Ingestion Pipeline

```
External Data Sources
    ├─ BayernCloud API
    ├─ GNTB/DZT API
    └─ GTFS Feeds
    ↓
Fetcher Scripts
    ├─ bayerncloud_fetch.py
    ├─ gntb_fetch_allgaeu.py
    └─ sync_gtfs_stops.py
    ↓
Data Transformation
    ├─ gntb_transform.py
    ├─ Normalization
    └─ Validation
    ↓
LlamaIndex Processing
    ├─ Document Creation
    ├─ Text Chunking
    └─ Embedding Generation
    ↓
OpenSearch Indexing
    ├─ Vector Store
    ├─ Metadata Storage
    └─ Index Optimization
```

### 3. Trip Planning Orchestration

```
Chat Query Input
    ↓
Session State Initialization
    ↓
LLM Intent Recognition
    ↓
Place Selection (best_city_logic)
    ├─ Query OpenSearch for cities
    └─ LLM ranking
    ↓
Activity Planning (plan_activities_logic)
    ├─ POI Search by category
    ├─ Location filtering
    └─ LLM ranking
    ↓
Journey Planning (plan_journey_logic)
    ├─ OTP GraphQL queries
    ├─ Connection optimization
    └─ Timetable data
    ↓
Itinerary Assembly (plan_multiday_trip_logic)
    ├─ Time block allocation
    ├─ Travel time inclusion
    └─ Schedule optimization
    ↓
Response Generation
    └─ Frontend Rendering
```

### 4. Vector Search Process

```
User Query Text
    ↓
Azure OpenAI Embeddings
    └─ Generate 3072-dim vector
    ↓
OpenSearch Vector Search
    ├─ Similarity calculation
    └─ Top-k retrieval
    ↓
Metadata Filtering
    ├─ Category match
    ├─ Geographic bounds
    └─ Exclusion list
    ↓
Ranked Results
    ├─ Distance score
    ├─ Relevance ranking
    └─ Category weighting
```

---

## Development Guide

### Project Structure for Developers

#### Backend Development

1. **Adding New Routes** (`src/Backend/api.py`):
```python
@app.post("/new-endpoint")
async def new_endpoint(request: RequestModel):
    """Docstring with route description"""
    # Implementation
    return response
```

2. **Adding New Models** (Pydantic):
```python
from pydantic import BaseModel, Field

class NewModel(BaseModel):
    field1: str
    field2: int = Field(default=10, ge=0, le=100)
    field3: Optional[str] = None
```

3. **Error Handling**:
```python
from fastapi import HTTPException

raise HTTPException(
    status_code=400,
    detail="Error message"
)
```

#### Frontend Development

1. **Creating Components**:
```jsx
import React, { useState } from 'react';

export function MyComponent() {
  const [state, setState] = useState(initialValue);

  return (
    <div className="tailwind-classes">
      {/* JSX content */}
    </div>
  );
}
```

2. **API Integration**:
```javascript
async function fetchData(endpoint) {
  const baseUrl = getBackendBaseUrl();
  const response = await fetch(`${baseUrl}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  return response.json();
}
```

3. **WebSocket Communication**:
```javascript
const ws = new WebSocket(`${wsUrl}/ws/${sessionId}`);
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  handleMessage(message);
};
```

#### MCP Agent Development

1. **Adding Tools**:
```python
@mcp.tool()
def tool_name(param1: str, param2: int) -> str:
    """Tool description for Claude"""
    # Implementation
    return result
```

2. **Using LlamaIndex**:
```python
from llama_index.core import VectorStoreIndex
from llama_index.vector_stores.opensearch import OpensearchVectorStore

index = VectorStoreIndex.from_documents(
    documents,
    vector_store=vector_store
)
query_engine = index.as_query_engine()
```

### Testing

#### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/backend/api_gateway/test_api_gateway.py

# Run with coverage
pytest --cov=src tests/

# Run with verbose output
pytest -v tests/
```

#### Writing Tests

```python
import pytest

@pytest.mark.asyncio
async def test_endpoint(gateway_client):
    response = await gateway_client.get("/endpoint")
    assert response.status_code == 200
    assert response.json()["key"] == "value"
```

#### Test Fixtures (conftest.py)

```python
@pytest.fixture
async def gateway_client():
    # Create client
    async with AsyncClient(app=app) as client:
        yield client
```

### Code Quality

#### Import Organization

```python
# Standard library
import os
import sys
from datetime import datetime

# Third-party
import fastapi
from pydantic import BaseModel

# Local
from Backend.api import app
```

#### Type Hints

```python
from typing import List, Optional, Dict, Any

def function(param1: str, param2: int) -> Dict[str, Any]:
    """Implementation"""
    pass
```

#### Documentation

```python
def function_name(param: str) -> str:
    """
    Brief description.
    
    Longer description if needed.
    
    Args:
        param: Description of param
        
    Returns:
        Description of return value
        
    Raises:
        ValueError: When... condition
    """
    pass
```

### Git Workflow

```bash
# Create feature branch
git checkout -b feature/feature-name

# Make changes and commit
git add .
git commit -m "feat: Add new feature"

# Update lock file before pushing
uv lock

# Push to remote
git push origin feature/feature-name
```

---

## Docker Setup

### Docker Compose Structure

#### Base Configuration (`docker-compose.yml`)
- Core services definitions
- Common settings
- Volume definitions
- Network configuration

#### Development Configuration (`docker-compose.dev.yml`)
```yaml
services:
  # Expose all ports for development
  backend:
    ports:
      - "8000:8000"
  
  frontend:
    environment:
      - VITE_RUNNING_COMP=DEV  # Enables dev features
    ports:
      - "5173:80"
```

#### Production Configuration (`docker-compose.prod.yml`)
- Nginx integration
- Resource constraints
- Health checks
- Environment secrets
- No exposed ports for internal services

### Building Images

#### Build All Services

```bash
cd src/
docker-compose build
```

#### Build Specific Service

```bash
docker-compose build backend
docker-compose build frontend
docker-compose build ingester
```

#### Build with Cache Bypass

```bash
docker-compose build --no-cache backend
```

### Volume Management

#### Create Volume

```bash
docker volume create opensearch-data
```

#### List Volumes

```bash
docker volume ls
```

#### Inspect Volume

```bash
docker volume inspect opensearch-data
```

#### Clean Unused Volumes

```bash
docker volume prune
```

### Container Logs

#### View Logs

```bash
# All services
docker-compose logs

# Specific service
docker-compose logs backend

# Follow logs (tail -f)
docker-compose logs -f backend

# Last 100 lines
docker-compose logs --tail=100 backend
```

### Container Shell Access

```bash
# Execute bash in container
docker-compose exec backend bash

# Run command in container
docker-compose exec backend python -c "import sys; print(sys.version)"
```

---

## Testing

### Test Structure

```
tests/
├── conftest.py              # Pytest configuration
├── backend/                 # Backend tests
│   ├── __init__.py
│   ├── api_gateway/
│   │   └── test_api_gateway.py
│   ├── Ingester/
│   ├── opensearch/
│   └── trip_planner/
├── integration/             # Integration tests
└── MCP/                     # MCP tests
```

### Running Tests

#### Development Environment

```bash
# Ensure virtual environment is active
source .venv/bin/activate

# Run pytest
pytest

# Run with options
pytest -v tests/backend/
```

#### Docker Environment

```bash
# Run tests in container
docker-compose exec backend pytest

# Run with coverage
docker-compose exec backend pytest --cov=Backend tests/
```

### Test Configuration (conftest.py)

```python
[tool.pytest.ini_options]
pythonpath = ["src"]         # Add src to path
testpaths = ["tests"]        # Test discovery location
asyncio_mode = "auto"        # Auto async mode
```

### Sample Test

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_health_check(gateway_client):
    """Test health endpoint"""
    response = await gateway_client.get("/health")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
```

### Async Testing

Tests with `@pytest.mark.asyncio` automatically handle async/await:

```python
@pytest.mark.asyncio
async def test_async_endpoint():
    response = await client.post("/endpoint", json={"key": "value"})
    assert response.status_code == 200
```

---

## Troubleshooting

### Common Issues

#### 1. OpenSearch Connection Errors

**Problem**: `opensearch: no such host`

**Solutions**:
```bash
# Ensure Docker Compose is running
docker-compose up -d

# Check OpenSearch status
curl http://localhost:9200/_cluster/health

# View logs
docker-compose logs opensearch
```

#### 2. Backend Can't Connect to OpenSearch

**Problem**: Backend container exits immediately

**Solutions**:
```bash
# Check environment variables
docker-compose exec backend env | grep OPENSEARCH

# Verify network connectivity
docker-compose exec backend curl http://opensearch:9200

# View backend logs
docker-compose logs backend
```

#### 3. Frontend Won't Load

**Problem**: Blank page or 404 errors

**Solutions**:
```bash
# Check frontend buildprocess
docker-compose logs frontend

# Verify backend accessibility
curl http://localhost:8000/health

# Check CORS configuration in backend
```

#### 4. OTP Server Not Responding

**Problem**: `Failed to connect to OTP`

**Solutions**:
```bash
# Verify OTP is running
curl http://localhost:8080/otp/routers/default/index

# Check OTP logs
docker-compose logs otp

# Verify graph file exists
docker-compose exec otp ls /var/opentripplanner/
```

#### 5. Azure OpenAI API Errors

**Problem**: `AZURE_OPENAI_API_KEY not set` or authentication fails

**Solutions**:
```bash
# Verify .env file exists
cat src/.env | grep AZURE_OPENAI

# Check API key validity
# Ensure Azure resource is deployed and accessible
# Verify API version compatibility (2024-05-01-preview)

# Test connectivity
python -c "import os; from openai import AzureOpenAI; print('OK' if os.getenv('AZURE_OPENAI_API_KEY') else 'Missing key')"
```

#### 6. uv Lock Issues

**Problem**: `uv.lock conflicts or sync failures`

**Solutions**:
```bash
# Never edit uv.lock manually!
# Use uv commands only

# Update dependencies
uv lock

# Sync with lock file
uv sync

# Clear cache if issues persist
uv cache clean
```

### Debugging

#### Enable Debug Logging

Add to `.env`:
```env
LOG_LEVEL=DEBUG
DEBUG=True
```

#### View Process Logs

```bash
# Terminal 1: Activate venv and run backend
source .venv/bin/activate
cd src/Backend
python api.py

# Terminal 2: View service logs
docker-compose logs -f
```

#### Database Inspection

```bash
# Access OpenSearch directly
curl http://localhost:9200/_cat/indices

# Query specific index
curl http://localhost:9200/tourism-data-v7/_search?q=museum

# View Dashboards UI
# Open browser: http://localhost:5601
```

#### Network Debugging

```bash
# Check connectivity between containers
docker-compose exec backend ping opensearch

# View network details
docker network inspect kira_default

# Test API endpoint
docker-compose exec backend curl http://backend:8000/health
```

---

## Deployment

### Pre-Deployment Checklist

- [ ] All tests passing: `pytest`
- [ ] Dependencies locked: `uv lock` committed
- [ ] Environment variables configured in `.env`
- [ ] Azure OpenAI resources created and accessible
- [ ] Docker images built and tested
- [ ] Security: API keys never committed
- [ ] HTTPS certificates ready for production
- [ ] Domain/hostname configured
- [ ] Database backups configured
- [ ] Monitoring and logging setup

### Production Deployment Steps

#### 1. Prepare Server

```bash
# SSH into production server
ssh user@production-server

# Clone repository
git clone <repo-url>
cd KIRA

# Create network for nginx proxy
docker network create nginx_proxy

# Pull latest images
docker-compose -f docker-compose.yml -f docker-compose.prod.yml pull
```

#### 2. Configure Environment

```bash
# Copy production .env
cp .env.example .env

# Edit with production values
nano .env

# Set restrictive permissions
chmod 600 .env
```

#### 3. Start Services

```bash
cd src/
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# Verify all services running
docker-compose ps
```

#### 4. Verify Deployment

```bash
# Check API health
curl https://yourdomain.com/health

# View logs
docker-compose logs backend
docker-compose logs frontend

# Test key endpoints
curl https://yourdomain.com/docs
```

#### 5. Configure Nginx

**Nginx Configuration** (`src/nginx/conf.d/default.conf`):

```nginx
upstream backend {
    server backend:8000;
}

server {
    listen 80;
    server_name yourdomain.com;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name yourdomain.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    # Frontend
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
    
    # Backend API
    location /api/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    # WebSocket
    location /ws/ {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

#### 6. Set Up Monitoring

```bash
# Configure health checks
docker-compose exec backend curl http://localhost:8000/health

# Set up log aggregation
# Configure backup strategy
```

#### 7. Data Ingestion

```bash
# Run initial data load
docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
  --profile ingest run --rm ingester python ingestor_v2.py

# Schedule periodic updates (cron)
0 2 * * * cd /path/to/KIRA && docker-compose ... --profile ingest run --rm ingester
```

### Scaling Considerations

#### Database Scaling
- OpenSearch cluster configuration
- Multiple node setup for high availability
- Shard and replica configuration

#### Application Scaling
- Multiple backend instances
- Load balancing with Nginx
- Session affinity configuration

#### Caching Strategy
- Redis for session caching
- Frontend asset caching
- API response caching

### Backup Strategy

```bash
# Backup OpenSearch data
docker-compose exec opensearch bash -c \
  "tar czf /backup/opensearch-$(date +%Y%m%d).tar.gz /usr/share/opensearch/data"

# Backup application data
docker volume inspect opensearch-data
```

### Monitoring & Maintenance

#### Health Checks

```bash
# Regular health monitoring
*/5 * * * * curl http://localhost:8000/health >> /var/log/kira-health.log 2>&1

# Log rotation
/var/log/kira-*.log {
    daily
    rotate 7
    compress
    delaycompress
}
```

#### Update Procedures

```bash
# Pull latest code
git pull origin main

# Update dependencies
uv lock
uv sync

# Rebuild images
docker-compose build

# Rolling restart
docker-compose up -d
```

---

## Additional Resources

### Documentation Files

- [README.md](./README.md) - Quick start guide
- [README_DOCKER.md](./src/README_DOCKER.md) - Docker-specific documentation
- [LICENSE](./LICENSE) - Project license

### External Services

- **Azure OpenAI**: https://azure.microsoft.com/en-us/services/openai/
- **OpenSearch**: https://opensearch.org/docs/
- **Open Trip Planner**: https://www.opentripplanner.org/
- **FastAPI**: https://fastapi.tiangolo.com/
- **React**: https://react.dev/
- **Docker**: https://docs.docker.com/

### API Documentation

- **FastAPI Docs**: Available at `/docs` endpoint (Swagger)
- **OpenAPI Schema**: Available at `/openapi.json`

### Performance Tips

1. **Vector Search Optimization**:
   - Index only necessary fields
   - Use appropriate chunk sizes (2048 recommended)
   - Batch embeddings generation

2. **Route Optimization**:
   - Cache OTP responses when possible
   - Pre-calculate common routes
   - Use connection monitoring

3. **Frontend Performance**:
   - Lazy load components
   - Optimize bundle size
   - Use code splitting with Vite

4. **Backend Performance**:
   - Connection pooling to OpenSearch
   - Async request handling
   - Response caching with Redis

---

## Contributing Guidelines

### Code Style

- **Python**: PEP 8 compliance (use `black` for formatting)
- **JavaScript**: ESLint configuration provided
- **Commit Messages**: Conventional commits format (`feat:`, `fix:`, `docs:`, etc.)

### Pull Request Process

1. Create feature branch from `main`
2. Make changes with descriptive commits
3. Update tests and documentation
4. Ensure all tests pass: `pytest`
5. Submit PR with clear description
6. Request review from team members
7. Address feedback and merge

### Reporting Issues

Include:
- Clear problem description
- Steps to reproduce
- Expected vs actual behavior
- System information (OS, Python version, Docker version)
- Relevant logs or error messages

---

## Project Information

- **Project Name**: KIRA
- **Version**: 1.0.0
- **Description**: AI-assisted trip planner for Allgäu region
- **License**: See LICENSE file
- **Repository**: [Repository URL]
- **Documentation Last Updated**: March 13, 2025

---

## Glossary

| Term | Definition |
|------|-----------|
| **MCP** | Model Context Protocol - protocol for AI-host communication |
| **OTP** | Open Trip Planner - routing and transit planning engine |
| **POI** | Point of Interest - tourism/activity locations |
| **GTFS** | General Transit Feed Specification - transit data format |
| **UTF-8** | Character encoding standard used throughout |
| **LLM** | Large Language Model (GPT-4o) |
| **Embeddings** | Vector representations of text (3072-dim for text-embedding-3-large) |
| **Vector Store** | Database optimized for similarity search (OpenSearch) |
| **CORS** | Cross-Origin Resource Sharing - enables frontend-backend communication |
| **GraphQL** | Query language used by OTP for data requests |
| **JWT** | JSON Web Tokens - session authentication (if implemented) |

---

**End of Documentation**

For questions or clarifications, please refer to the main README.md or consult the development team.
