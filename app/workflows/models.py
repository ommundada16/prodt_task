"""
Data passed into/out of the Temporal workflow and its activities.

Plain dataclasses rather than the Pydantic models used elsewhere in the
app, because that's what Temporal's default data converter serialises
most easily, and workflow inputs/outputs must be serialisable.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class BookingRequestInput:
    idempotency_key: str
    supplier_id: str
    supplier_property_id: str
    destination: str
    check_in: str  # ISO date string, e.g. "2026-09-10"
    check_out: str
    guests: int
    rooms: int
    expected_total_price: float
    max_price_increase_pct: float = 5.0
    simulate_supplier_failures: int = 0


@dataclass
class BookingResult:
    booking_id: Optional[int]
    status: str  # confirmed | failed | cancelled | manual_review
    supplier_reservation_reference: Optional[str]
    reason: Optional[str] = None
