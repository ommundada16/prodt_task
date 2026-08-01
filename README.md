# Travel Supplier Aggregator (Prototype)

A Python service that integrates multiple hotel suppliers behind one standardised
API. It searches supplier inventory, normalises inconsistent responses, ranks
results, and manages the booking lifecycle reliably using Temporal.

This is a prototype built for a take-home assignment. It is being developed in
small, incremental steps — each step is its own git commit so the history shows
how the system was built up.

## Status

Work in progress. See commit history for progress. Sections below will be
filled in as each part is built.

## Tech Stack

- **Language:** Python 3.11+
- **API:** FastAPI
- **Data validation:** Pydantic
- **Workflow engine:** Temporal (Python SDK)
- **Database:** SQLite (dev) via SQLAlchemy
- **Testing:** Pytest
- **Containers:** Docker / Docker Compose (for Temporal server)

## Project Layout

```
app/
  schemas.py          # Shared internal data models (the common hotel offer format)
  suppliers/           # One adapter per supplier, converting supplier data -> shared schema
  mock_suppliers/       # Fake Atlas Hotels / Nova Stays APIs used for local dev + tests
  services/             # Search aggregation, ranking
  api/                   # FastAPI app and routes
  db/                     # SQLAlchemy models and session setup
  workflows/               # Temporal workflows and activities (booking lifecycle)
tests/
docs/                       # Architecture notes, decisions, assumptions
```

## Running Locally

Requires Python 3.11+.

```bash
python -m venv .venv
.venv/Scripts/activate        # on Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
```

Run the two mock suppliers and the main API (three separate terminals):

```bash
uvicorn app.mock_suppliers.atlas_api:app --port 9001
uvicorn app.mock_suppliers.nova_api:app --port 9002
uvicorn app.api.main:app --port 8000
```

Try a search:

```bash
curl -X POST http://127.0.0.1:8000/search/hotels \
  -H "Content-Type: application/json" \
  -d '{"destination": "Mumbai", "check_in": "2026-09-10", "check_out": "2026-09-12", "guests": 2, "rooms": 1}'
```

Booking (Temporal workflow), full docker-compose setup, and automated
tests are still being built - see commit history for current progress.

## How AI Coding Assistants Were Used

This project was built with the help of Claude (Claude Code). Notes on which
parts were AI-assisted vs hand-reviewed/modified will be documented in
`docs/ai_usage.md`.
