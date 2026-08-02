"""FastAPI app exposing the unified hotel search and booking endpoints."""

import logging
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.db.database import get_db, init_db
from app.db.repository import save_search_and_offers
from app.logging_config import configure_logging
from app.schemas import BookHotelRequest, HotelOffer, SearchRequest
from app.services.search_service import search_all_suppliers
from app.suppliers.atlas_adapter import AtlasAdapter
from app.suppliers.nova_adapter import NovaAdapter
from app.workflows.booking_workflow import BookingWorkflow
from app.workflows.client import get_temporal_client
from app.workflows.models import BookingRequestInput
from app.workflows.worker import TASK_QUEUE

configure_logging()
logger = logging.getLogger("app.api")

app = FastAPI(title="Travel Supplier Aggregator")


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


# Adding a new supplier here (and to this list) is the only change needed
# to make it show up in search - search_service.py doesn't change at all.
SUPPLIER_ADAPTERS = [AtlasAdapter(), NovaAdapter()]


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/", include_in_schema=False)
def home():
    """Simple search-and-book demo page. /docs remains the API reference for developers."""
    return FileResponse("app/static/index.html")


@app.post("/search/hotels", response_model=list[HotelOffer])
async def search_hotels(request: SearchRequest, http_request: Request, db: Session = Depends(get_db)) -> list[HotelOffer]:
    request_id = http_request.state.request_id
    logger.info(f"request_id={request_id} action=search destination={request.destination}")
    offers = await search_all_suppliers(SUPPLIER_ADAPTERS, request)
    save_search_and_offers(db, request, offers)
    logger.info(f"request_id={request_id} action=search_complete result_count={len(offers)}")
    return offers


def _workflow_id_for(idempotency_key: str) -> str:
    return f"booking-{idempotency_key}"


@app.post("/bookings")
async def create_booking(request: BookHotelRequest, http_request: Request):
    """
    Starts the booking workflow. The workflow ID is derived from
    idempotency_key, and Temporal rejects starting a second workflow with
    an ID that's already running - so submitting the same booking request
    twice (e.g. a double click) attaches to the original workflow instead
    of starting a duplicate one.
    """
    client = await get_temporal_client()
    workflow_id = _workflow_id_for(request.idempotency_key)
    logger.info(
        f"request_id={http_request.state.request_id} action=create_booking "
        f"workflow_id={workflow_id} supplier={request.supplier_id} "
        f"supplier_property_id={request.supplier_property_id}"
    )

    workflow_input = BookingRequestInput(
        idempotency_key=request.idempotency_key,
        supplier_id=request.supplier_id,
        supplier_property_id=request.supplier_property_id,
        destination=request.destination,
        check_in=request.check_in.isoformat(),
        check_out=request.check_out.isoformat(),
        guests=request.guests,
        rooms=request.rooms,
        expected_total_price=request.expected_total_price,
        max_price_increase_pct=request.max_price_increase_pct,
        simulate_supplier_failures=request.simulate_supplier_failures,
    )

    await client.start_workflow(
        BookingWorkflow.run,
        workflow_input,
        id=workflow_id,
        task_queue=TASK_QUEUE,
    )
    return {"workflow_id": workflow_id}


@app.get("/bookings/{workflow_id}/status")
async def get_booking_status(workflow_id: str):
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        status = await handle.query(BookingWorkflow.status)
    except Exception:
        raise HTTPException(status_code=404, detail="Booking workflow not found")
    return {"workflow_id": workflow_id, "status": status}


@app.get("/bookings/{workflow_id}/result")
async def get_booking_result(workflow_id: str):
    """
    Returns the booking's current details. Uses a query rather than waiting
    on workflow completion, because a confirmed booking's workflow stays
    open (to remain cancellable) rather than finishing - waiting on it
    would hang forever for a confirmed booking.
    """
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    try:
        return await handle.query(BookingWorkflow.details)
    except Exception:
        raise HTTPException(status_code=404, detail="Booking workflow not found")


@app.post("/bookings/{workflow_id}/cancel")
async def cancel_booking(workflow_id: str):
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    await handle.signal(BookingWorkflow.cancel_booking)
    return {"workflow_id": workflow_id, "cancel_requested": True}
