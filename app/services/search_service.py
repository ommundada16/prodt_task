"""
Runs a hotel search across every configured supplier at once, cleans up
the results, and ranks them.
"""

import asyncio

from app.schemas import AvailabilityStatus, HotelOffer, SearchRequest
from app.suppliers.base import SupplierAdapter

# Confidence score per supplier, used as one input to ranking. In a real
# system this would come from historical data quality/reliability metrics;
# here it's a fixed value per supplier to keep the ranking logic easy to
# follow and explain.
SUPPLIER_CONFIDENCE = {
    "atlas": 0.90,
    "nova": 0.85,
}

SEARCH_TIMEOUT_SECONDS = 5.0


async def search_all_suppliers(adapters: list[SupplierAdapter], request: SearchRequest) -> list[HotelOffer]:
    """
    Calls every supplier concurrently. If one supplier fails or times out,
    its results are simply dropped - the other suppliers' results are
    still returned instead of failing the whole search.
    """
    results = await asyncio.gather(
        *(_search_one_supplier(adapter, request) for adapter in adapters),
        return_exceptions=True,
    )

    offers: list[HotelOffer] = []
    for result in results:
        if isinstance(result, Exception):
            continue
        offers.extend(result)

    offers = _remove_unavailable(offers)
    offers = _deduplicate(offers)
    offers = _rank(offers)
    return offers


async def _search_one_supplier(adapter: SupplierAdapter, request: SearchRequest) -> list[HotelOffer]:
    return await asyncio.wait_for(adapter.search_properties(request), timeout=SEARCH_TIMEOUT_SECONDS)


def _remove_unavailable(offers: list[HotelOffer]) -> list[HotelOffer]:
    return [offer for offer in offers if offer.availability_status != AvailabilityStatus.SOLD_OUT]


def _deduplicate(offers: list[HotelOffer]) -> list[HotelOffer]:
    """
    Two suppliers can list what is effectively the same physical room
    (same property name, location, and room type). When that happens,
    keep only the cheaper offer.

    This is a simple heuristic match on normalised name/location/room
    type, not a guaranteed identity match - see docs/assumptions for
    limitations (e.g. suppliers spelling the same property differently
    would not be caught).
    """
    best_by_key: dict[tuple[str, str, str], HotelOffer] = {}
    for offer in offers:
        key = (
            offer.property_name.strip().lower(),
            offer.location.strip().lower(),
            offer.room_type.strip().lower(),
        )
        existing = best_by_key.get(key)
        if existing is None or offer.total_price < existing.total_price:
            best_by_key[key] = offer
    return list(best_by_key.values())


def _rank(offers: list[HotelOffer]) -> list[HotelOffer]:
    """
    Ranking method:

        score = supplier_confidence - price_penalty - availability_penalty

    - price_penalty is total_price normalised against the most expensive
      offer in the result set (0-1), so cheaper offers score higher
      regardless of currency/amount scale.
    - availability_penalty is 0 for AVAILABLE and 0.2 for ON_REQUEST
      (SOLD_OUT offers are already filtered out before this runs).
    - supplier_confidence is a fixed per-supplier weight (see
      SUPPLIER_CONFIDENCE above), so between two similarly priced offers
      the more reliable supplier is preferred.

    Results are sorted by this score, highest first.
    """
    if not offers:
        return offers

    max_price = max(offer.total_price for offer in offers) or 1.0

    def score(offer: HotelOffer) -> float:
        price_penalty = offer.total_price / max_price
        availability_penalty = 0.0 if offer.availability_status == AvailabilityStatus.AVAILABLE else 0.2
        confidence = SUPPLIER_CONFIDENCE.get(offer.supplier_id, 0.5)
        return confidence - price_penalty - availability_penalty

    return sorted(offers, key=score, reverse=True)
