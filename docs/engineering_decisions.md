# Engineering Decisions, Assumptions & Limitations

## Key Engineering Decisions

### 1. Adapter Pattern for Supplier Extensibility
- **Decision**: All supplier interactions are mediated through an abstract `SupplierAdapter` class (`app/suppliers/base.py`). Each adapter converts raw supplier formats into a common `HotelOffer` schema.
- **Rationale**: Isolates supplier-specific variations (such as Atlas's percentage-based tax calculation vs. Nova's flat fee model) behind a standard contract.
- **Impact**: Adding a new supplier requires creating a single python class implementing `SupplierAdapter` and adding it to `SUPPLIER_ADAPTERS`. No modifications are needed in search aggregation, ranking, or booking workflow logic.

### 2. Temporal for Resilient Booking Workflow Orchestration
- **Decision**: The entire booking lifecycle is implemented as a Temporal workflow (`app/workflows/booking_workflow.py`) with activities (`app/workflows/activities.py`) handling I/O operations.
- **Rationale**: Travel booking processes involve asynchronous polling, external supplier retries, state persistence, and compensation logic. Hardcoding this in a standard background task framework (e.g. Celery or FastAPI background tasks) leads to fragile state management during worker restarts.
- **Impact**:
  - Automatic exponential retries for transient supplier network errors.
  - Safe worker crashes/restarts—the Temporal server maintains state and resumes execution seamlessly.
  - Signal support (`cancel_booking`) allowing post-confirmation cancellations without blocking active HTTP worker connections.

### 3. Strict Idempotency and Duplicate Booking Prevention
- **Decision**:
  - The client provides an `idempotency_key` (e.g. UUID).
  - The API derives the Temporal workflow ID as `booking-{idempotency_key}`.
  - Temporal's platform-level constraint prevents launching multiple active workflows with the exact same ID (`WorkflowAlreadyStartedError`).
  - Database table `bookings` enforces `idempotency_key` as a `UNIQUE` column constraint.
- **Rationale**: Prevents double-clicks or retried network requests from creating duplicate supplier reservations or double billing.

### 4. Compensation Logic (Saga Pattern Light)
- **Decision**: If creating a supplier reservation succeeds, but saving the internal database booking record fails even after activity retries, an automatic compensation activity `cancel_supplier_reservation` is executed, and the booking status is set to `manual_review`.
- **Rationale**: Avoids orphaned supplier reservations that cost money without internal traceability.

### 5. One-command startup via a single Docker Compose stack
- **Decision**: `docker-compose.yml` builds one image (`Dockerfile`) reused across five services - the two mock suppliers, the main API, the worker, plus Temporal and Postgres - each just overriding the container's start command. `docker compose up -d --build` is the entire setup.
- **Rationale**: The assignment asks for the prototype to run "locally using one documented command." Running five processes across separate terminals works for local development but isn't a one-command experience for someone evaluating the repo cold.
- **Impact**: App data (SQLite) lives in a named Docker volume (`app_data`) shared by the main API and worker containers, rather than a bind-mounted host path, so it isn't affected by host-OS file-locking quirks. Verified by stopping every locally-running process and bringing the whole stack up fresh, then re-running the search -> book -> confirm flow purely against the containerized services.

---

## Assumptions & Known Limitations

1. **Property Deduplication Heuristic**:
   - *Assumption*: Properties are deduplicated based on normalized `(property_name, location, room_type)`.
   - *Limitation*: In a real production system, supplier property names can differ slightly (e.g., "Grand Hotel" vs "Grand Hotel & Suites"). Production integration would require geo-coordinate matching or a Master Property Database (GIATA ID).

2. **Currency Standardization**:
   - *Assumption*: Mock suppliers currently return pricing in INR or standard local currency for the destination.
   - *Limitation*: Multi-currency conversion services are not currently integrated into search aggregation.

3. **Temporal Polling Window**:
   - *Assumption*: Supplier reservation confirmation occurs within 10 polling attempts (20 seconds total window in test/demo config).
   - *Limitation*: If a supplier requires hours for manual confirmation, Temporal timers/cron or webhook callbacks would be utilized instead of short polling loops.

4. **Cold-start race on a fresh Docker stack**:
   - *Observation*: On the very first `docker compose up` (or after `-v`), the Temporal auto-setup container can accept connections slightly before its `default` namespace finishes being registered, so `main-api`/`worker` briefly fail with "Namespace default is not found."
   - *Mitigation*: `restart: on-failure` on both services recovers automatically within ~20 seconds. A proper fix would add a Temporal healthcheck and `depends_on: condition: service_healthy`, which wasn't pursued given the time budget - documenting the transient behavior was the pragmatic tradeoff.
