"""
Tests for the search aggregation service in isolation: filtering,
deduplication, ranking, and graceful handling of a failing, slow, or
malformed supplier. Uses a minimal fake adapter rather than the mock
suppliers, so these tests exercise search_service.py's own logic only.
"""

import asyncio
from datetime import date

import pytest

from app.schemas import AvailabilityStatus, HotelOffer, SearchRequest
from app.services import search_service
from app.services.search_service import search_all_suppliers
from app.suppliers.base import SupplierAdapter

SEARCH_REQUEST = SearchRequest(
    destination="Mumbai", check_in=date(2026, 9, 10), check_out=date(2026, 9, 12), guests=2, rooms=1
)


def make_offer(
    supplier_id="atlas",
    property_name="Test Hotel",
    location="Mumbai",
    room_type="Standard",
    total_price=1000.0,
    status=AvailabilityStatus.AVAILABLE,
):
    return HotelOffer(
        supplier_id=supplier_id,
        supplier_property_id=f"{supplier_id}-1",
        property_name=property_name,
        location=location,
        room_type=room_type,
        check_in=date(2026, 9, 10),
        check_out=date(2026, 9, 12),
        currency="INR",
        base_price=total_price * 0.9,
        taxes_and_fees=total_price * 0.1,
        total_price=total_price,
        cancellation_policy="Free cancellation",
        availability_status=status,
    )


class FakeAdapter(SupplierAdapter):
    """A minimal stand-in supplier for testing the search service without
    real HTTP or the mock supplier apps."""

    def __init__(self, supplier_id, offers=None, error=None, delay=0):
        self.supplier_id = supplier_id
        self._offers = offers or []
        self._error = error
        self._delay = delay

    async def search_properties(self, request):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error:
            raise self._error
        return self._offers

    async def get_price_and_availability(self, property_id, request):
        raise NotImplementedError

    async def create_reservation(self, property_id, request, idempotency_key, simulate_failures=0):
        raise NotImplementedError

    async def get_reservation_status(self, reservation_reference):
        raise NotImplementedError

    def normalize_reservation_status(self, raw_status):
        raise NotImplementedError

    async def cancel_reservation(self, reservation_reference):
        raise NotImplementedError


async def test_sold_out_offers_are_filtered_out():
    adapter = FakeAdapter("atlas", offers=[make_offer(status=AvailabilityStatus.SOLD_OUT)])
    results = await search_all_suppliers([adapter], SEARCH_REQUEST)
    assert results == []


async def test_cheaper_offer_wins_when_two_suppliers_list_the_same_room():
    cheap = make_offer(supplier_id="nova", property_name="Same Hotel", room_type="Standard", total_price=1000.0)
    expensive = make_offer(supplier_id="atlas", property_name="Same Hotel", room_type="Standard", total_price=1500.0)
    atlas = FakeAdapter("atlas", offers=[expensive])
    nova = FakeAdapter("nova", offers=[cheap])

    results = await search_all_suppliers([atlas, nova], SEARCH_REQUEST)

    assert len(results) == 1
    assert results[0].supplier_id == "nova"
    assert results[0].total_price == 1000.0


async def test_cheaper_offer_ranked_first():
    cheap = make_offer(property_name="A", total_price=1000.0)
    expensive = make_offer(property_name="B", total_price=5000.0)
    adapter = FakeAdapter("atlas", offers=[expensive, cheap])

    results = await search_all_suppliers([adapter], SEARCH_REQUEST)

    assert [o.property_name for o in results] == ["A", "B"]


async def test_one_supplier_failing_still_returns_the_others_results():
    working = FakeAdapter("atlas", offers=[make_offer(property_name="Still Here")])
    broken = FakeAdapter("nova", error=Exception("supplier is down"))

    results = await search_all_suppliers([working, broken], SEARCH_REQUEST)

    assert len(results) == 1
    assert results[0].property_name == "Still Here"


async def test_slow_supplier_times_out_without_blocking_the_search(monkeypatch):
    monkeypatch.setattr(search_service, "SEARCH_TIMEOUT_SECONDS", 0.05)
    working = FakeAdapter("atlas", offers=[make_offer(property_name="Fast Supplier")])
    slow = FakeAdapter("nova", offers=[make_offer(property_name="Too Slow")], delay=1)

    results = await search_all_suppliers([working, slow], SEARCH_REQUEST)

    assert len(results) == 1
    assert results[0].property_name == "Fast Supplier"


async def test_malformed_supplier_response_is_dropped_not_raised():
    class MalformedAdapter(FakeAdapter):
        async def search_properties(self, request):
            raise KeyError("missing_field")  # simulates a response missing a field our adapter expects

    working = FakeAdapter("atlas", offers=[make_offer(property_name="Good Data")])
    malformed = MalformedAdapter("nova")

    results = await search_all_suppliers([working, malformed], SEARCH_REQUEST)

    assert len(results) == 1
    assert results[0].property_name == "Good Data"


async def test_all_suppliers_failing_returns_empty_list_not_an_error():
    broken1 = FakeAdapter("atlas", error=Exception("down"))
    broken2 = FakeAdapter("nova", error=Exception("also down"))

    results = await search_all_suppliers([broken1, broken2], SEARCH_REQUEST)

    assert results == []
