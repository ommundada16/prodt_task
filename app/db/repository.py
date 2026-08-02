"""Small persistence helpers used by the API layer to record what happened,
separate from the core search/booking logic itself."""

from sqlalchemy.orm import Session

from app.db.models import OfferRecord, SearchRequestRecord
from app.schemas import HotelOffer, SearchRequest


def save_search_and_offers(db: Session, request: SearchRequest, offers: list[HotelOffer]) -> None:
    search_record = SearchRequestRecord(
        destination=request.destination,
        check_in=request.check_in.isoformat(),
        check_out=request.check_out.isoformat(),
        guests=request.guests,
        rooms=request.rooms,
    )
    db.add(search_record)
    db.flush()  # assigns search_record.id without committing yet

    for offer in offers:
        db.add(
            OfferRecord(
                search_request_id=search_record.id,
                supplier_id=offer.supplier_id,
                supplier_property_id=offer.supplier_property_id,
                property_name=offer.property_name,
                location=offer.location,
                room_type=offer.room_type,
                currency=offer.currency,
                total_price=offer.total_price,
                availability_status=offer.availability_status.value,
            )
        )
    db.commit()
