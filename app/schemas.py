"""
Shared internal data models.

Every supplier returns data in its own format. Each supplier adapter is
responsible for converting that supplier's response into these shared
models, so the rest of the application (search, ranking, booking) never
has to know which supplier a result came from.
"""

from datetime import date
from enum import Enum

from pydantic import BaseModel


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    SOLD_OUT = "sold_out"
    ON_REQUEST = "on_request"  # supplier needs to confirm before it's guaranteed


class HotelOffer(BaseModel):
    """
    A single bookable room offer, normalised into a common format
    regardless of which supplier it came from.
    """

    supplier_id: str            # e.g. "atlas" or "nova"
    supplier_property_id: str   # the supplier's own ID for this property
    property_name: str
    location: str
    room_type: str
    check_in: date
    check_out: date
    currency: str
    base_price: float
    taxes_and_fees: float
    total_price: float
    cancellation_policy: str
    availability_status: AvailabilityStatus


class SearchRequest(BaseModel):
    destination: str
    check_in: date
    check_out: date
    guests: int
    rooms: int
