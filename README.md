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

(Setup instructions will be added here once the service is runnable end-to-end.)

## How AI Coding Assistants Were Used

This project was built with the help of Claude (Claude Code). Notes on which
parts were AI-assisted vs hand-reviewed/modified will be documented in
`docs/ai_usage.md`.
