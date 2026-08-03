# Travel Supplier Aggregator Service

A standardized, highly available Python service that integrates multiple hotel travel suppliers behind a single unified API. It searches supplier inventories concurrently, normalizes inconsistent responses, ranks results using a multi-factor formula, and orchestrates reliable booking lifecycles with Temporal workflows.

---

## Key Features

- **Supplier Integration Layer**: Modular Python adapters (`AtlasAdapter`, `NovaAdapter`) converting disparate supplier structures, currencies, and tax models into a shared `HotelOffer` schema.
- **Unified Concurrent Search**: `POST /search/hotels` endpoint searching suppliers simultaneously with per-supplier timeouts and partial result tolerance.
- **Deduplication & Ranking**: Automatically filters sold-out offers, merges duplicate property listings across suppliers (keeping the lowest price), and ranks offers by price, availability, and supplier confidence.
- **Temporal Booking Workflow**: End-to-end booking state machine managing price revalidation, price threshold enforcement, activity retries, timeouts, cancellation signals, and compensation logic.
- **Duplicate Booking Prevention**: Strict idempotency key enforcement at API and workflow levels (`booking-{idempotency_key}`).
- **Persistence & Observability**: Complete audit tracking of search requests, normalized offers, booking state transitions, and structured logging with `X-Request-ID` tracing.

---

## Technology Stack

- **Language:** Python 3.11+
- **API Framework:** FastAPI & Pydantic v2
- **Workflow Engine:** Temporal Python SDK
- **Database:** SQLite via SQLAlchemy for app data (search requests, offers, bookings) - in a Docker named volume when run via Compose, a local file otherwise. PostgreSQL is also in the stack, backing Temporal's own internal storage (not app data).
- **Testing:** Pytest & `pytest-asyncio` (using Temporal's time-skipping test server)
- **Containerization:** Docker & Docker Compose

---

## Project Structure

```
├── app/
│   ├── api/             # FastAPI main application and endpoint routes
│   ├── db/              # SQLAlchemy database models, session management, repository logic
│   ├── mock_suppliers/  # Mock Atlas Hotels and Nova Stays APIs for local development
│   ├── services/        # Search aggregation, deduplication, filtering, and ranking logic
│   ├── suppliers/       # Supplier adapter interface and concrete supplier implementations
│   ├── workflows/       # Temporal booking workflow, activities, worker, and data models
│   ├── config.py        # Environment configuration
│   ├── logging_config.py# Structured logging configuration
│   └── schemas.py       # Shared internal Pydantic data models
├── docs/                # Comprehensive architectural and system documentation
│   ├── ai_usage.md
│   ├── api_documentation.md
│   ├── architecture.md
│   ├── database_schema.md
│   └── engineering_decisions.md
├── tests/               # Automated unit and integration test suite
│   ├── conftest.py
│   ├── test_booking_workflow.py
│   ├── test_search_service.py
│   └── test_supplier_adapters.py
├── Dockerfile           # Image used to build every app service (mocks, main API, worker)
├── docker-compose.yml   # Full stack: Temporal, Postgres, both mock suppliers, main API, worker
├── pytest.ini
├── requirements.txt
└── README.md
```

`app/static/index.html` is a small, non-technical-friendly demo page (search a
destination, see ranked results, click "Book Now" and watch it move through
the booking lifecycle) served at `/` by the main API - `/docs` remains the
technical Swagger reference for developers.

---

## Quick Start & Running Locally

### Option A: One-command Docker setup (Recommended)

Requires Docker and Docker Compose. This builds and starts everything -
Postgres, the Temporal server + Web UI, both mock supplier APIs, the main
API, and the Temporal worker - as one stack:

```bash
docker compose up -d --build
```

Once it's up:
- Main API + demo page: http://localhost:8000/ (Swagger docs at `/docs`)
- Temporal Web UI: http://localhost:8080

Search and booking are both fully live at this point - no other setup
needed. Stop everything with `docker compose down`.

> **Note:** on a completely fresh start (first run, or after `docker compose
> down -v`), `main-api`/`worker` may log a "Namespace default is not found"
> error once or twice before Temporal finishes its own startup setup. This
> is expected - `restart: on-failure` recovers automatically within about
> 20 seconds, with no action needed.

---

### Option B: Running the automated test suite

Requires Python 3.11+. The suite runs all 23 tests, including full
Temporal workflow scenarios, using Temporal's in-memory time-skipping
test server - no Docker needed for this:

```bash
python -m venv .venv
.venv\Scripts\activate        # on Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
pytest
```

---

### Option C: Running services individually (for local development/debugging)

Start Temporal + Postgres via Docker, then run each app service directly
so you can edit code and restart just the one process you're working on:

```bash
docker compose up -d postgresql temporal temporal-ui
```

Then, in separate terminals (with `.venv` activated as in Option B):

```bash
uvicorn app.mock_suppliers.atlas_api:app --port 9001
uvicorn app.mock_suppliers.nova_api:app --port 9002
python -m app.workflows.worker
uvicorn app.api.main:app --port 8000
```

---

## Quick API Test Example

### 1. Perform Search
```bash
curl -X POST http://127.0.0.1:8000/search/hotels \
  -H "Content-Type: application/json" \
  -d '{
    "destination": "Mumbai",
    "check_in": "2026-09-10",
    "check_out": "2026-09-12",
    "guests": 2,
    "rooms": 1
  }'
```

### 2. Initiate Booking
```bash
curl -X POST http://127.0.0.1:8000/bookings \
  -H "Content-Type: application/json" \
  -d '{
    "idempotency_key": "my-unique-key-100",
    "supplier_id": "atlas",
    "supplier_property_id": "ATL-100",
    "destination": "Mumbai",
    "check_in": "2026-09-10",
    "check_out": "2026-09-12",
    "guests": 2,
    "rooms": 1,
    "expected_total_price": 9408.0,
    "max_price_increase_pct": 5.0
  }'
```

### 3. Check Booking Status
```bash
curl http://127.0.0.1:8000/bookings/booking-my-unique-key-100/status
```

---

## System Documentation & Engineering Decisions

For full technical specifications, architecture diagrams, database schemas, and AI tool usage notes, see the [`docs/`](docs/) folder:
- [System Architecture & Flow Diagrams](docs/architecture.md)
- [API Specification & Payloads](docs/api_documentation.md)
- [Database Schema & Entity Models](docs/database_schema.md)
- [Engineering Decisions, Assumptions & Limitations](docs/engineering_decisions.md)
- [AI Coding Assistant Usage Documentation](docs/ai_usage.md)
