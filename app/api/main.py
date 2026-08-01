"""FastAPI app exposing the unified hotel search endpoint."""

from fastapi import FastAPI

from app.schemas import HotelOffer, SearchRequest
from app.services.search_service import search_all_suppliers
from app.suppliers.atlas_adapter import AtlasAdapter
from app.suppliers.nova_adapter import NovaAdapter

app = FastAPI(title="Travel Supplier Aggregator")

# Adding a new supplier here (and to this list) is the only change needed
# to make it show up in search - search_service.py doesn't change at all.
SUPPLIER_ADAPTERS = [AtlasAdapter(), NovaAdapter()]


@app.post("/search/hotels", response_model=list[HotelOffer])
async def search_hotels(request: SearchRequest) -> list[HotelOffer]:
    return await search_all_suppliers(SUPPLIER_ADAPTERS, request)
