"""
SQLAlchemy models for everything the app persists: search requests, the
normalised offers returned for them, booking records, and the status
history of each booking.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.database import Base


class SearchRequestRecord(Base):
    __tablename__ = "search_requests"

    id = Column(Integer, primary_key=True)
    destination = Column(String, nullable=False)
    check_in = Column(String, nullable=False)
    check_out = Column(String, nullable=False)
    guests = Column(Integer, nullable=False)
    rooms = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    offers = relationship("OfferRecord", back_populates="search_request")


class OfferRecord(Base):
    """A normalised offer returned for a search, kept so a later booking can
    reference exactly what the user saw (price, supplier, property)."""

    __tablename__ = "offers"

    id = Column(Integer, primary_key=True)
    search_request_id = Column(Integer, ForeignKey("search_requests.id"), nullable=False)
    supplier_id = Column(String, nullable=False)
    supplier_property_id = Column(String, nullable=False)
    property_name = Column(String, nullable=False)
    location = Column(String, nullable=False)
    room_type = Column(String, nullable=False)
    currency = Column(String, nullable=False)
    total_price = Column(Float, nullable=False)
    availability_status = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    search_request = relationship("SearchRequestRecord", back_populates="offers")


class BookingRecord(Base):
    """The internal record of a booking attempt, driven by the Temporal
    booking workflow. idempotency_key stops the same booking request from
    being processed twice."""

    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True)
    idempotency_key = Column(String, unique=True, nullable=False)
    offer_id = Column(Integer, ForeignKey("offers.id"), nullable=False)
    workflow_id = Column(String, nullable=False)
    supplier_id = Column(String, nullable=False)
    supplier_reservation_reference = Column(String, nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    offer = relationship("OfferRecord")
    status_history = relationship("BookingStatusHistoryRecord", back_populates="booking")


class BookingStatusHistoryRecord(Base):
    """Every status transition a booking goes through. `note` is used to
    record failure/retry information (e.g. which activity failed and why)."""

    __tablename__ = "booking_status_history"

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False)
    status = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    booking = relationship("BookingRecord", back_populates="status_history")
