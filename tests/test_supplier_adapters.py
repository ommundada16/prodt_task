"""
Tests for supplier adapters: converting each supplier's own data shape
into our shared HotelOffer schema (price calculations, availability
mapping), and normalising each supplier's reservation-status wording.
"""

from datetime import date

import pytest

from app.schemas import AvailabilityStatus, SearchRequest

SEARCH_REQUEST = SearchRequest(
    destination="Mumbai", check_in=date(2026, 9, 10), check_out=date(2026, 9, 12), guests=2, rooms=1
)


async def test_atlas_search_converts_percentage_tax_to_shared_schema(atlas_adapter):
    offers = await atlas_adapter.search_properties(SEARCH_REQUEST)

    grand_palace = next(o for o in offers if o.supplier_property_id == "ATL-100")
    assert grand_palace.supplier_id == "atlas"
    assert grand_palace.base_price == 4200.0 * 2  # price_per_night * nights
    assert grand_palace.taxes_and_fees == pytest.approx(4200.0 * 2 * 0.12)
    assert grand_palace.total_price == pytest.approx(grand_palace.base_price + grand_palace.taxes_and_fees)
    assert grand_palace.availability_status == AvailabilityStatus.AVAILABLE


async def test_atlas_on_request_status_maps_correctly(atlas_adapter):
    offers = await atlas_adapter.search_properties(SEARCH_REQUEST)
    beacon = next(o for o in offers if o.supplier_property_id == "ATL-101")
    assert beacon.availability_status == AvailabilityStatus.ON_REQUEST


async def test_nova_search_converts_flat_fee_to_shared_schema(nova_adapter):
    offers = await nova_adapter.search_properties(SEARCH_REQUEST)

    central = next(o for o in offers if o.supplier_property_id == "NOVA-500")
    assert central.base_price == 3900.0 * 2
    assert central.taxes_and_fees == 450.0  # flat fee, not a percentage of price
    assert central.total_price == pytest.approx(central.base_price + central.taxes_and_fees)


async def test_nova_on_request_status_maps_correctly(nova_adapter):
    offers = await nova_adapter.search_properties(SEARCH_REQUEST)
    skyline = next(o for o in offers if o.supplier_property_id == "NOVA-501")
    assert skyline.availability_status == AvailabilityStatus.ON_REQUEST


def test_atlas_normalizes_reservation_status(atlas_adapter):
    assert atlas_adapter.normalize_reservation_status("PENDING") == "pending"
    assert atlas_adapter.normalize_reservation_status("CONFIRMED") == "confirmed"
    assert atlas_adapter.normalize_reservation_status("CANCELLED") == "cancelled"
    assert atlas_adapter.normalize_reservation_status("SOMETHING_UNKNOWN") == "failed"


def test_nova_normalizes_reservation_status(nova_adapter):
    assert nova_adapter.normalize_reservation_status("IN_PROGRESS") == "pending"
    assert nova_adapter.normalize_reservation_status("CONFIRMED") == "confirmed"
    assert nova_adapter.normalize_reservation_status("CANCELLED") == "cancelled"
    assert nova_adapter.normalize_reservation_status("SOMETHING_UNKNOWN") == "failed"


async def test_atlas_reservation_is_idempotent(atlas_adapter):
    ref1 = await atlas_adapter.create_reservation("ATL-100", SEARCH_REQUEST, idempotency_key="same-key")
    ref2 = await atlas_adapter.create_reservation("ATL-100", SEARCH_REQUEST, idempotency_key="same-key")
    assert ref1 == ref2


async def test_atlas_reservation_retries_succeed_after_simulated_failures(atlas_adapter):
    with pytest.raises(Exception):
        await atlas_adapter.create_reservation("ATL-100", SEARCH_REQUEST, idempotency_key="flaky-key", simulate_failures=2)
    with pytest.raises(Exception):
        await atlas_adapter.create_reservation("ATL-100", SEARCH_REQUEST, idempotency_key="flaky-key", simulate_failures=2)
    # Third attempt with the same key succeeds - the forced-failure count has been used up.
    reference = await atlas_adapter.create_reservation("ATL-100", SEARCH_REQUEST, idempotency_key="flaky-key", simulate_failures=2)
    assert reference


async def test_atlas_reservation_status_moves_from_pending_to_confirmed(atlas_adapter):
    reference = await atlas_adapter.create_reservation("ATL-100", SEARCH_REQUEST, idempotency_key="poll-key")
    first_check = await atlas_adapter.get_reservation_status(reference)
    second_check = await atlas_adapter.get_reservation_status(reference)
    assert first_check == "PENDING"
    assert second_check == "CONFIRMED"


async def test_atlas_malformed_search_response_raises_instead_of_silently_returning_bad_data(atlas_adapter, monkeypatch):
    """If a supplier ever returns a hotel object missing a field our adapter
    expects, the adapter should raise (so search_service can catch and drop
    it) rather than silently producing an invalid/incomplete HotelOffer."""
    from app.mock_suppliers import atlas_api as atlas_api_module

    original = list(atlas_api_module.ATLAS_PROPERTIES)
    broken_hotel = dict(original[0])
    del broken_hotel["tax_percentage"]  # simulate a malformed/incomplete supplier response
    monkeypatch.setattr(atlas_api_module, "ATLAS_PROPERTIES", [broken_hotel])

    with pytest.raises(KeyError):
        await atlas_adapter.search_properties(SEARCH_REQUEST)
