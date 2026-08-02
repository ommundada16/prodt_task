"""
Adapter for the (fake) Nova Stays API. Converts Nova's data shapes (flat
fees instead of percentage tax, camelCase fields, nested availability)
into our shared HotelOffer schema.
"""

import httpx

from app.config import NOVA_API_BASE_URL
from app.schemas import AvailabilityStatus, HotelOffer, SearchRequest
from app.suppliers.base import SupplierAdapter

# Nova's booking-status wording -> our normalised booking status.
NOVA_BOOKING_STATUS_MAP = {
    "IN_PROGRESS": "pending",
    "CONFIRMED": "confirmed",
    "CANCELLED": "cancelled",
}


class NovaAdapter(SupplierAdapter):
    supplier_id = "nova"

    def __init__(self, base_url: str = NOVA_API_BASE_URL):
        self.base_url = base_url

    async def search_properties(self, request: SearchRequest) -> list[HotelOffer]:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            response = await client.post(
                "/nova/v2/properties/search",
                json={
                    "cityName": request.destination,
                    "checkInDate": request.check_in.isoformat(),
                    "checkOutDate": request.check_out.isoformat(),
                    "roomsRequested": request.rooms,
                },
            )
            response.raise_for_status()
            properties = response.json()

        return [self._to_hotel_offer(p, request) for p in properties]

    async def get_price_and_availability(self, property_id: str, request: SearchRequest) -> HotelOffer:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            response = await client.get(f"/nova/v2/properties/{property_id}/rate")
            response.raise_for_status()
            property_ = response.json()

        return self._to_hotel_offer(property_, request)

    async def create_reservation(
        self, property_id: str, request: SearchRequest, idempotency_key: str, simulate_failures: int = 0
    ) -> str:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            response = await client.post(
                "/nova/v2/bookings",
                json={
                    "propertyId": property_id,
                    "checkInDate": request.check_in.isoformat(),
                    "checkOutDate": request.check_out.isoformat(),
                    "roomsRequested": request.rooms,
                    "idempotencyKey": idempotency_key,
                    "simulateFailures": simulate_failures,
                },
            )
            response.raise_for_status()
            return response.json()["bookingRef"]

    async def get_reservation_status(self, reservation_reference: str) -> str:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            response = await client.get(f"/nova/v2/bookings/{reservation_reference}")
            response.raise_for_status()
            return response.json()["bookingStatus"]

    def normalize_reservation_status(self, raw_status: str) -> str:
        return NOVA_BOOKING_STATUS_MAP.get(raw_status, "failed")

    async def cancel_reservation(self, reservation_reference: str) -> bool:
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            response = await client.post(f"/nova/v2/bookings/{reservation_reference}/cancel")
            response.raise_for_status()
            return response.json()["bookingStatus"] == "CANCELLED"

    def _to_hotel_offer(self, property_: dict, request: SearchRequest) -> HotelOffer:
        nights = (request.check_out - request.check_in).days
        base_price = property_["nightlyRate"] * nights
        taxes_and_fees = property_["feesFlat"]  # Nova charges a flat fee, not a percentage

        return HotelOffer(
            supplier_id=self.supplier_id,
            supplier_property_id=property_["propertyId"],
            property_name=property_["propertyName"],
            location=property_["cityName"],
            room_type=property_["roomName"],
            check_in=request.check_in,
            check_out=request.check_out,
            currency=property_["currencyCode"],
            base_price=round(base_price, 2),
            taxes_and_fees=round(taxes_and_fees, 2),
            total_price=round(base_price + taxes_and_fees, 2),
            cancellation_policy=property_["cancellationTerms"],
            availability_status=self._map_availability(property_["availability"]),
        )

    @staticmethod
    def _map_availability(availability: dict) -> AvailabilityStatus:
        if availability["available"]:
            return AvailabilityStatus.AVAILABLE
        if availability["onRequest"]:
            return AvailabilityStatus.ON_REQUEST
        return AvailabilityStatus.SOLD_OUT
