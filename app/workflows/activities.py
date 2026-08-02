"""
Temporal activities: every piece of I/O (calling a supplier, touching the
database) lives here rather than in the workflow. Activities are the unit
Temporal retries and times out - workflow code itself must stay
deterministic, so nothing here is called directly by the workflow except
through workflow.execute_activity.
"""

from datetime import date
from typing import Optional

from temporalio import activity

from app.db.database import SessionLocal
from app.db.models import BookingRecord, BookingStatusHistoryRecord
from app.schemas import SearchRequest
from app.suppliers.atlas_adapter import AtlasAdapter
from app.suppliers.nova_adapter import NovaAdapter
from app.workflows.models import BookingRequestInput

SUPPLIER_ADAPTERS = {"atlas": AtlasAdapter(), "nova": NovaAdapter()}


def _adapter_for(supplier_id: str):
    return SUPPLIER_ADAPTERS[supplier_id]


def _search_request(input: BookingRequestInput) -> SearchRequest:
    return SearchRequest(
        destination=input.destination,
        check_in=date.fromisoformat(input.check_in),
        check_out=date.fromisoformat(input.check_out),
        guests=input.guests,
        rooms=input.rooms,
    )


@activity.defn
async def revalidate_offer(input: BookingRequestInput) -> float:
    """Re-checks the supplier's current total price for this property.
    Returns just the price - that's all the workflow needs to decide
    whether to proceed."""
    adapter = _adapter_for(input.supplier_id)
    offer = await adapter.get_price_and_availability(input.supplier_property_id, _search_request(input))
    return offer.total_price


@activity.defn
async def create_supplier_reservation(input: BookingRequestInput) -> str:
    """Creates the reservation with the supplier. input.idempotency_key is
    passed through to the supplier, so if Temporal retries this activity
    (e.g. because the response timed out after the supplier had already
    processed it), the supplier returns the existing reservation instead
    of creating a second one."""
    adapter = _adapter_for(input.supplier_id)
    return await adapter.create_reservation(
        input.supplier_property_id,
        _search_request(input),
        idempotency_key=input.idempotency_key,
        simulate_failures=input.simulate_supplier_failures,
    )


@activity.defn
async def save_booking_record(input: BookingRequestInput, supplier_reservation_reference: str, workflow_id: str) -> int:
    """Creates (or, on retry, reuses) the internal booking row. The unique
    idempotency_key column means this is safe to run more than once for
    the same booking request."""
    db = SessionLocal()
    try:
        booking = db.query(BookingRecord).filter_by(idempotency_key=input.idempotency_key).first()
        if booking is None:
            booking = BookingRecord(
                idempotency_key=input.idempotency_key,
                workflow_id=workflow_id,
                supplier_id=input.supplier_id,
                supplier_property_id=input.supplier_property_id,
                total_price=input.expected_total_price,
                supplier_reservation_reference=supplier_reservation_reference,
                status="reserved",
            )
            db.add(booking)
            db.commit()
            db.refresh(booking)
        else:
            booking.supplier_reservation_reference = supplier_reservation_reference
            booking.status = "reserved"
            db.commit()

        db.add(BookingStatusHistoryRecord(booking_id=booking.id, status="reserved", note="Supplier reservation created"))
        db.commit()
        return booking.id
    finally:
        db.close()


@activity.defn
async def check_supplier_reservation_status(input: BookingRequestInput, supplier_reservation_reference: str) -> str:
    """Returns a normalised status: pending, confirmed, cancelled, or failed - see
    SupplierAdapter.normalize_reservation_status."""
    adapter = _adapter_for(input.supplier_id)
    raw_status = await adapter.get_reservation_status(supplier_reservation_reference)
    return adapter.normalize_reservation_status(raw_status)


@activity.defn
async def update_booking_status(booking_id: int, status: str, note: Optional[str] = None) -> None:
    db = SessionLocal()
    try:
        booking = db.get(BookingRecord, booking_id)
        booking.status = status
        db.add(BookingStatusHistoryRecord(booking_id=booking_id, status=status, note=note))
        db.commit()
    finally:
        db.close()


@activity.defn
async def cancel_supplier_reservation(input: BookingRequestInput, supplier_reservation_reference: str) -> bool:
    adapter = _adapter_for(input.supplier_id)
    return await adapter.cancel_reservation(supplier_reservation_reference)
