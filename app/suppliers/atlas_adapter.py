"""
Adapter for the (fake) Atlas Hotels API. Converts Atlas's data shapes into
our shared HotelOffer schema, and translates our shared method calls into
the specific HTTP calls Atlas expects.
"""

from typing import Optional

import httpx

from app.config import ATLAS_API_BASE_URL
from app.schemas import AvailabilityStatus, HotelOffer, SearchRequest
from app.suppliers.base import SupplierAdapter

ATLAS_STATUS_MAP = {
    "OPEN": AvailabilityStatus.AVAILABLE,
    "SOLD_OUT": AvailabilityStatus.SOLD_OUT,
    "REQUEST": AvailabilityStatus.ON_REQUEST,
}

# Atlas's reservation-state wording -> our normalised booking status.
ATLAS_RESERVATION_STATUS_MAP = {
    "PENDING": "pending",
    "CONFIRMED": "confirmed",
    "CANCELLED": "cancelled",
}


class AtlasAdapter(SupplierAdapter):
    supplier_id = "atlas"

    def __init__(self, base_url: str = ATLAS_API_BASE_URL, transport: Optional[httpx.BaseTransport] = None):
        self.base_url = base_url
        # transport lets tests point this adapter at the mock Atlas app
        # in-process (via httpx.ASGITransport) instead of real HTTP.
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base_url, transport=self.transport)

    async def search_properties(self, request: SearchRequest) -> list[HotelOffer]:
        async with self._client() as client:
            response = await client.post(
                "/atlas/v1/search",
                json={
                    "city": request.destination,
                    "check_in": request.check_in.isoformat(),
                    "check_out": request.check_out.isoformat(),
                    "num_rooms": request.rooms,
                },
            )
            response.raise_for_status()
            hotels = response.json()

        return [self._to_hotel_offer(hotel, request) for hotel in hotels]

    async def get_price_and_availability(self, property_id: str, request: SearchRequest) -> HotelOffer:
        async with self._client() as client:
            response = await client.get(f"/atlas/v1/hotels/{property_id}/price")
            response.raise_for_status()
            hotel = response.json()

        return self._to_hotel_offer(hotel, request)

    async def create_reservation(
        self, property_id: str, request: SearchRequest, idempotency_key: str, simulate_failures: int = 0
    ) -> str:
        async with self._client() as client:
            response = await client.post(
                "/atlas/v1/reservations",
                json={
                    "hotel_id": property_id,
                    "check_in": request.check_in.isoformat(),
                    "check_out": request.check_out.isoformat(),
                    "num_rooms": request.rooms,
                    "idempotency_key": idempotency_key,
                    "simulate_failures": simulate_failures,
                },
            )
            response.raise_for_status()
            return response.json()["confirmation_code"]

    async def get_reservation_status(self, reservation_reference: str) -> str:
        async with self._client() as client:
            response = await client.get(f"/atlas/v1/reservations/{reservation_reference}")
            response.raise_for_status()
            return response.json()["state"]

    def normalize_reservation_status(self, raw_status: str) -> str:
        return ATLAS_RESERVATION_STATUS_MAP.get(raw_status, "failed")

    async def cancel_reservation(self, reservation_reference: str) -> bool:
        async with self._client() as client:
            response = await client.post(f"/atlas/v1/reservations/{reservation_reference}/cancel")
            response.raise_for_status()
            return response.json()["state"] == "CANCELLED"

    def _to_hotel_offer(self, hotel: dict, request: SearchRequest) -> HotelOffer:
        nights = (request.check_out - request.check_in).days
        base_price = hotel["price_per_night"] * nights
        taxes_and_fees = base_price * (hotel["tax_percentage"] / 100)

        return HotelOffer(
            supplier_id=self.supplier_id,
            supplier_property_id=hotel["hotel_id"],
            property_name=hotel["hotel_name"],
            location=hotel["city"],
            room_type=hotel["room_category"],
            check_in=request.check_in,
            check_out=request.check_out,
            currency=hotel["currency"],
            base_price=round(base_price, 2),
            taxes_and_fees=round(taxes_and_fees, 2),
            total_price=round(base_price + taxes_and_fees, 2),
            cancellation_policy=self._describe_cancellation_policy(hotel["free_cancellation_before_days"]),
            availability_status=ATLAS_STATUS_MAP[hotel["status"]],
        )

    @staticmethod
    def _describe_cancellation_policy(free_cancellation_before_days: int) -> str:
        if free_cancellation_before_days <= 0:
            return "Non-refundable"
        return f"Free cancellation up to {free_cancellation_before_days} day(s) before check-in"
