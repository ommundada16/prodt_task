# System Architecture & Flow

This document details the architecture of the Travel Supplier Aggregator service, including component roles, request flows, search aggregation strategy, and the Temporal workflow design for reliable booking management.

---

## 1. System Overview Diagram

```mermaid
graph TD
    Client[Client / Web UI / Mobile]

    subgraph FastAPI Application Layer
        API[FastAPI Main Server :8000]
        SearchService[Search Aggregation & Ranking Service]
        TemporalClient[Temporal Client]
    end

    subgraph Supplier Layer
        AtlasAdapter[Atlas Supplier Adapter]
        NovaAdapter[Nova Supplier Adapter]
        AtlasAPI[Mock Atlas API :9001]
        NovaAPI[Mock Nova API :9002]
    end

    subgraph Workflow Engine & Persistence
        TemporalServer[Temporal Cluster :7233]
        TemporalWorker[Temporal Python Worker]
        DB[(SQLite / PostgreSQL DB)]
    end

    Client -->|1. POST /search/hotels| API
    API --> SearchService
    SearchService -->|Concurrent HTTP| AtlasAdapter
    SearchService -->|Concurrent HTTP| NovaAdapter
    AtlasAdapter --> AtlasAPI
    NovaAdapter --> NovaAPI
    SearchService -->|Store Search & Offers| DB

    Client -->|2. POST /bookings| API
    API --> TemporalClient
    TemporalClient -->|Start Workflow: booking-IDEMPOTENCY_KEY| TemporalServer

    TemporalWorker -->|Poll Task Queue| TemporalServer
    TemporalWorker -->|Execute Activities| AtlasAdapter
    TemporalWorker -->|Execute Activities| NovaAdapter
    TemporalWorker -->|Read/Write Bookings & History| DB
```

---

## 2. Component Breakdown

### A. FastAPI Service (`app/api/main.py`)
- Provides standardized REST endpoints for search and booking execution.
- Generates and injects a unique `X-Request-ID` via middleware for tracing requests end-to-end.
- Enforces duplicate booking prevention at the entry point by deriving Temporal workflow IDs from the client's `idempotency_key`.

### B. Supplier Integration Layer (`app/suppliers/`)
- **`SupplierAdapter` (Abstract Base Class)**: Defines contract for `search_properties`, `get_price_and_availability`, `create_reservation`, `get_reservation_status`, `normalize_reservation_status`, and `cancel_reservation`.
- **`AtlasAdapter` & `NovaAdapter`**: Translate supplier-specific payloads into/from the shared `HotelOffer` schema. Handle supplier-specific pricing rules (e.g. Atlas percentage tax vs Nova flat fees) and availability status mappings.

### C. Search Aggregation & Ranking (`app/services/search_service.py`)
- **Concurrent Execution**: Searches all configured supplier adapters concurrently via `asyncio.gather` with a per-supplier timeout (5 seconds).
- **Fault Tolerance**: Supplier errors or timeouts are caught gracefully without failing the request (returns partial results).
- **Filtering**: Automatically excludes `SOLD_OUT` inventory.
- **Deduplication**: Identifies duplicate listings across suppliers based on normalized property name, location, and room type, retaining the cheapest offer.
- **Ranking Engine**: Ranks offers based on normalized price, availability type, and supplier confidence weighting:
  ```
  score = supplier_confidence - (total_price / max_price_in_result_set) - availability_penalty
  ```
  Higher score ranks first. See `app/services/search_service.py::_rank` for the exact implementation.

### D. Booking Lifecycle & Temporal Workflows (`app/workflows/`)
- **`BookingWorkflow`**: State machine driving the booking lifecycle:
  1. Offer price revalidation.
  2. Threshold check (`max_price_increase_pct`).
  3. Supplier reservation creation.
  4. Internal database record persistence.
  5. Asynchronous polling for supplier confirmation.
  6. Final state recording (`confirmed`, `failed`, `cancelled`, or `manual_review`).
  7. Long-polling state for post-confirmation cancellation requests via Temporal signals.
- **Compensation & Recovery**: If supplier reservation succeeds but internal DB persistence fails, compensation triggers automatically to cancel the supplier reservation and flag the booking for `manual_review`.

---

## 3. Data Flow Diagrams

### Search Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as FastAPI Main API
    participant Search as Search Service
    participant Atlas as Atlas Adapter
    participant Nova as Nova Adapter
    participant DB as Database

    Client->>API: POST /search/hotels
    API->>Search: search_all_suppliers(adapters, request)
    par Concurrent Supplier Calls
        Search->>Atlas: search_properties(request)
        Atlas-->>Search: [Atlas Hotel Offers]
    and
        Search->>Nova: search_properties(request)
        Nova-->>Search: [Nova Hotel Offers]
    end
    Search->>Search: Filter SOLD_OUT offers
    Search->>Search: Deduplicate matching properties (keep cheapest)
    Search->>Search: Rank results by formula
    API->>DB: Save search request & normalized offers
    API-->>Client: 200 OK [Ranked Hotel Offers]
```

### Booking Flow

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant API as FastAPI Main API
    participant Temporal as Temporal Cluster
    participant Worker as Temporal Worker
    participant Supplier as Supplier API
    participant DB as Database

    Client->>API: POST /bookings (with idempotency_key)
    API->>Temporal: start_workflow, id = booking-IDEMPOTENCY_KEY
    API-->>Client: 200 OK, workflow_id = booking-IDEMPOTENCY_KEY

    Worker->>Temporal: Poll Task Queue
    Worker->>Supplier: Activity: revalidate_offer
    Supplier-->>Worker: Current Price
    Worker->>Worker: Check price increase vs threshold

    Worker->>Supplier: Activity: create_supplier_reservation
    Supplier-->>Worker: Supplier Confirmation Code

    Worker->>DB: Activity: save_booking_record
    DB-->>Worker: Booking ID

    loop Poll Supplier Status
        Worker->>Supplier: Activity: check_supplier_reservation_status
        Supplier-->>Worker: Status ("CONFIRMED")
    end

    Worker->>DB: Activity: update_booking_status ("confirmed")
    Worker->>Temporal: Wait for cancellation signal
```
