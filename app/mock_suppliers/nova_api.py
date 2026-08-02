"""
Fake Nova Stays API.

Deliberately shaped differently from Atlas: flat currency fees instead of
a tax percentage, camelCase field names, a nested availability object, and
its own booking status wording. The Nova adapter is what reconciles this
with our internal schema.

Run standalone with: uvicorn app.mock_suppliers.nova_api:app --port 9002
"""

from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Nova Stays API (mock)")

NOVA_PROPERTIES = [
    {
        "propertyId": "NOVA-500",
        "propertyName": "Nova Central Hotel",
        "cityName": "Mumbai",
        "roomName": "Classic Room",
        "nightlyRate": 3900.0,
        "feesFlat": 450.0,
        "currencyCode": "INR",
        "availability": {"available": True, "onRequest": False},
        "cancellationTerms": "Free cancellation up to 24 hours before check-in",
    },
    {
        "propertyId": "NOVA-501",
        "propertyName": "Nova Skyline Residency",
        "cityName": "Mumbai",
        "roomName": "Premium Room",
        "nightlyRate": 7100.0,
        "feesFlat": 600.0,
        "currencyCode": "INR",
        "availability": {"available": False, "onRequest": True},
        "cancellationTerms": "Non-refundable",
    },
    {
        "propertyId": "NOVA-502",
        "propertyName": "Nova Green Stay",
        "cityName": "Pune",
        "roomName": "Standard Room",
        "nightlyRate": 2200.0,
        "feesFlat": 300.0,
        "currencyCode": "INR",
        "availability": {"available": True, "onRequest": False},
        "cancellationTerms": "Free cancellation up to 48 hours before check-in",
    },
]

NOVA_BOOKINGS: dict[str, dict] = {}
# Maps idempotencyKey -> bookingRef, so a retried booking request returns
# the existing booking instead of creating a second one.
NOVA_IDEMPOTENCY_INDEX: dict[str, str] = {}
# Remaining forced-failure count per idempotencyKey, used to simulate a
# flaky supplier for testing retry behaviour.
NOVA_REMAINING_FAILURES: dict[str, int] = {}
_next_booking_number = 1


class NovaSearchRequest(BaseModel):
    cityName: str
    checkInDate: date
    checkOutDate: date
    roomsRequested: int


class NovaBookingRequest(BaseModel):
    propertyId: str
    checkInDate: date
    checkOutDate: date
    roomsRequested: int
    idempotencyKey: str
    simulateFailures: int = 0


@app.post("/nova/v2/properties/search")
def search(req: NovaSearchRequest):
    return [p for p in NOVA_PROPERTIES if p["cityName"].lower() == req.cityName.lower()]


@app.get("/nova/v2/properties/{property_id}/rate")
def get_rate(property_id: str):
    return _find_property(property_id)


@app.post("/nova/v2/bookings")
def create_booking(req: NovaBookingRequest):
    global _next_booking_number

    existing_ref = NOVA_IDEMPOTENCY_INDEX.get(req.idempotencyKey)
    if existing_ref:
        return NOVA_BOOKINGS[existing_ref]

    remaining_failures = NOVA_REMAINING_FAILURES.setdefault(req.idempotencyKey, req.simulateFailures)
    if remaining_failures > 0:
        NOVA_REMAINING_FAILURES[req.idempotencyKey] -= 1
        raise HTTPException(status_code=503, detail="Nova is temporarily unavailable")

    property_ = _find_property(req.propertyId)
    if not property_["availability"]["available"]:
        raise HTTPException(status_code=409, detail="Property not bookable")

    booking_ref = f"NOVA-BK-{_next_booking_number:04d}"
    _next_booking_number += 1
    NOVA_BOOKINGS[booking_ref] = {
        "bookingRef": booking_ref,
        "propertyId": req.propertyId,
        # Starts IN_PROGRESS and flips to CONFIRMED after a couple of
        # status checks, mirroring how a real supplier would take a
        # moment to confirm rather than doing it synchronously.
        "bookingStatus": "IN_PROGRESS",
        "statusChecks": 0,
    }
    NOVA_IDEMPOTENCY_INDEX[req.idempotencyKey] = booking_ref
    return NOVA_BOOKINGS[booking_ref]


@app.get("/nova/v2/bookings/{booking_ref}")
def get_booking(booking_ref: str):
    booking = NOVA_BOOKINGS.get(booking_ref)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking["bookingStatus"] == "IN_PROGRESS":
        booking["statusChecks"] += 1
        if booking["statusChecks"] >= 2:
            booking["bookingStatus"] = "CONFIRMED"

    return booking


@app.post("/nova/v2/bookings/{booking_ref}/cancel")
def cancel_booking(booking_ref: str):
    booking = NOVA_BOOKINGS.get(booking_ref)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    booking["bookingStatus"] = "CANCELLED"
    return booking


def _find_property(property_id: str) -> dict:
    for p in NOVA_PROPERTIES:
        if p["propertyId"] == property_id:
            return p
    raise HTTPException(status_code=404, detail="Property not found")
