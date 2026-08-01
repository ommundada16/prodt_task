"""
Fake Atlas Hotels API.

This simulates a real third-party supplier so the rest of the project has
something concrete to integrate against. Field names and formats here
(percentage-based tax, "OPEN"/"SOLD_OUT"/"REQUEST" status codes) are
deliberately different from Nova Stays and from our own internal schema -
that mismatch is exactly what the Atlas adapter exists to handle.

Run standalone with: uvicorn app.mock_suppliers.atlas_api:app --port 9001
"""

from datetime import date

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Atlas Hotels API (mock)")

# In-memory "database" of properties Atlas has on offer.
ATLAS_PROPERTIES = [
    {
        "hotel_id": "ATL-100",
        "hotel_name": "Atlas Grand Palace",
        "city": "Mumbai",
        "room_category": "Deluxe Room",
        "price_per_night": 4200.0,
        "tax_percentage": 12.0,
        "currency": "INR",
        "status": "OPEN",
        "free_cancellation_before_days": 2,
    },
    {
        "hotel_id": "ATL-101",
        "hotel_name": "Atlas Beacon Suites",
        "city": "Mumbai",
        "room_category": "Executive Suite",
        "price_per_night": 6800.0,
        "tax_percentage": 12.0,
        "currency": "INR",
        "status": "REQUEST",
        "free_cancellation_before_days": 0,
    },
    {
        "hotel_id": "ATL-102",
        "hotel_name": "Atlas Riverside Inn",
        "city": "Pune",
        "room_category": "Standard Room",
        "price_per_night": 2500.0,
        "tax_percentage": 12.0,
        "currency": "INR",
        "status": "SOLD_OUT",
        "free_cancellation_before_days": 1,
    },
]

# In-memory reservations, keyed by confirmation code.
ATLAS_RESERVATIONS: dict[str, dict] = {}
_next_reservation_number = 1


class AtlasSearchRequest(BaseModel):
    city: str
    check_in: date
    check_out: date
    num_rooms: int


class AtlasBookingRequest(BaseModel):
    hotel_id: str
    check_in: date
    check_out: date
    num_rooms: int


@app.post("/atlas/v1/search")
def search(req: AtlasSearchRequest):
    return [p for p in ATLAS_PROPERTIES if p["city"].lower() == req.city.lower()]


@app.get("/atlas/v1/hotels/{hotel_id}/price")
def get_price(hotel_id: str):
    return _find_hotel(hotel_id)


@app.post("/atlas/v1/reservations")
def create_reservation(req: AtlasBookingRequest):
    global _next_reservation_number
    hotel = _find_hotel(req.hotel_id)
    if hotel["status"] == "SOLD_OUT":
        raise HTTPException(status_code=409, detail="Room no longer available")

    confirmation_code = f"ATL-CONF-{_next_reservation_number:04d}"
    _next_reservation_number += 1
    ATLAS_RESERVATIONS[confirmation_code] = {
        "confirmation_code": confirmation_code,
        "hotel_id": req.hotel_id,
        "state": "CONFIRMED",
    }
    return ATLAS_RESERVATIONS[confirmation_code]


@app.get("/atlas/v1/reservations/{confirmation_code}")
def get_reservation(confirmation_code: str):
    reservation = ATLAS_RESERVATIONS.get(confirmation_code)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return reservation


@app.post("/atlas/v1/reservations/{confirmation_code}/cancel")
def cancel_reservation(confirmation_code: str):
    reservation = ATLAS_RESERVATIONS.get(confirmation_code)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    reservation["state"] = "CANCELLED"
    return reservation


def _find_hotel(hotel_id: str) -> dict:
    for p in ATLAS_PROPERTIES:
        if p["hotel_id"] == hotel_id:
            return p
    raise HTTPException(status_code=404, detail="Hotel not found")
