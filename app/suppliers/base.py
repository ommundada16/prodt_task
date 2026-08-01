"""
Every supplier adapter must implement this interface. The search service
and booking workflow only ever talk to adapters through these methods, so
a new supplier can be added by writing one new adapter class - no changes
needed to search or booking logic.
"""

from abc import ABC, abstractmethod

from app.schemas import HotelOffer, SearchRequest


class SupplierAdapter(ABC):
    supplier_id: str

    @abstractmethod
    async def search_properties(self, request: SearchRequest) -> list[HotelOffer]:
        """Search available properties and return them in the shared HotelOffer format."""
        raise NotImplementedError

    @abstractmethod
    async def get_price_and_availability(self, property_id: str, request: SearchRequest) -> HotelOffer:
        """Re-check current price and availability for one property, right before booking."""
        raise NotImplementedError

    @abstractmethod
    async def create_reservation(self, property_id: str, request: SearchRequest) -> str:
        """Create a reservation with the supplier. Returns the supplier's reservation reference."""
        raise NotImplementedError

    @abstractmethod
    async def get_reservation_status(self, reservation_reference: str) -> str:
        """Look up the current status of a reservation at the supplier."""
        raise NotImplementedError

    @abstractmethod
    async def cancel_reservation(self, reservation_reference: str) -> bool:
        """Cancel a reservation at the supplier. Returns True if cancellation succeeded."""
        raise NotImplementedError
