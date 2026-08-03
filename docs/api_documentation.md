# API Documentation & Usage Reference

The Travel Supplier Aggregator provides standardized HTTP REST endpoints for searching supplier inventories and orchestrating resilient hotel bookings.

---

## Base URL
- Local Dev Server: `http://localhost:8000`
- Interactive OpenAPI Docs: `http://localhost:8000/docs`

---

## Endpoints Summary

| Method | Path | Description |
| :--- | :--- | :--- |
| `POST` | `/search/hotels` | Search, normalize, deduplicate, and rank hotel offers across suppliers |
| `POST` | `/bookings` | Start a new resilient booking workflow |
| `GET` | `/bookings/{workflow_id}/status` | Query current high-level status of a booking workflow |
| `GET` | `/bookings/{workflow_id}/result` | Query detailed results/state of a booking workflow |
| `POST` | `/bookings/{workflow_id}/cancel` | Send cancellation signal to an active or confirmed booking workflow |

---

## Endpoint Details & Example Requests/Responses

### 1. Unified Hotel Search

**`POST /search/hotels`**

Searches all registered suppliers concurrently, normalizes data into a common schema, filters unavailable rooms, deduplicates duplicate listings, ranks results, and stores search history in the database.

#### Request Headers
```
Content-Type: application/json
```

#### Request Body Schema
```json
{
  "destination": "Mumbai",
  "check_in": "2026-09-10",
  "check_out": "2026-09-12",
  "guests": 2,
  "rooms": 1
}
```

#### Example Response (`200 OK`)

Captured from an actual run against the mock suppliers (destination "Mumbai"):

```json
[
  {
    "supplier_id": "nova",
    "supplier_property_id": "NOVA-500",
    "property_name": "Nova Central Hotel",
    "location": "Mumbai",
    "room_type": "Classic Room",
    "check_in": "2026-09-10",
    "check_out": "2026-09-12",
    "currency": "INR",
    "base_price": 7800.0,
    "taxes_and_fees": 450.0,
    "total_price": 8250.0,
    "cancellation_policy": "Free cancellation up to 24 hours before check-in",
    "availability_status": "available"
  },
  {
    "supplier_id": "atlas",
    "supplier_property_id": "ATL-100",
    "property_name": "Atlas Grand Palace",
    "location": "Mumbai",
    "room_type": "Deluxe Room",
    "check_in": "2026-09-10",
    "check_out": "2026-09-12",
    "currency": "INR",
    "base_price": 8400.0,
    "taxes_and_fees": 1008.0,
    "total_price": 9408.0,
    "cancellation_policy": "Free cancellation up to 2 day(s) before check-in",
    "availability_status": "available"
  },
  {
    "supplier_id": "atlas",
    "supplier_property_id": "ATL-101",
    "property_name": "Atlas Beacon Suites",
    "location": "Mumbai",
    "room_type": "Executive Suite",
    "check_in": "2026-09-10",
    "check_out": "2026-09-12",
    "currency": "INR",
    "base_price": 13600.0,
    "taxes_and_fees": 1632.0,
    "total_price": 15232.0,
    "cancellation_policy": "Non-refundable",
    "availability_status": "on_request"
  }
]
```

---

### 2. Create Booking

**`POST /bookings`**

Initiates a Temporal booking workflow for a chosen offer. Enforces duplicate booking prevention using `idempotency_key`.

#### Request Body Schema
```json
{
  "idempotency_key": "booking-req-uuid-12345",
  "supplier_id": "atlas",
  "supplier_property_id": "ATL-100",
  "destination": "Mumbai",
  "check_in": "2026-09-10",
  "check_out": "2026-09-12",
  "guests": 2,
  "rooms": 1,
  "expected_total_price": 9408.0,
  "max_price_increase_pct": 5.0,
  "simulate_supplier_failures": 0
}
```

#### Example Response (`200 OK`)
```json
{
  "workflow_id": "booking-booking-req-uuid-12345"
}
```

---

### 3. Check Booking Status

**`GET /bookings/{workflow_id}/status`**

#### Example Response (`200 OK`)
```json
{
  "workflow_id": "booking-booking-req-uuid-12345",
  "status": "confirmed"
}
```

---

### 4. Query Booking Details

**`GET /bookings/{workflow_id}/result`**

#### Example Response (`200 OK`)
```json
{
  "booking_id": 1,
  "status": "confirmed",
  "supplier_reservation_reference": "ATL-CONF-0001",
  "reason": null
}
```

---

### 5. Cancel Booking

**`POST /bookings/{workflow_id}/cancel`**

Sends a cancellation signal to the workflow. The workflow will execute supplier cancellation and update DB status accordingly.

#### Example Response (`200 OK`)
```json
{
  "workflow_id": "booking-booking-req-uuid-12345",
  "cancel_requested": true
}
```
