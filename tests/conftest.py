"""
Shared pytest fixtures. Sets DATABASE_URL to a dedicated test database
before any app module is imported, so running the test suite never
touches the local dev app.db.
"""

import os

os.environ["DATABASE_URL"] = "sqlite:///./test.db"

import httpx
import pytest

from app.db.database import Base, engine, init_db
from app.mock_suppliers import atlas_api, nova_api
from app.suppliers.atlas_adapter import AtlasAdapter
from app.suppliers.nova_adapter import NovaAdapter


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _reset_mock_supplier_state():
    """Each mock supplier keeps its 'database' in module-level dicts and
    counters. Reset them before every test so tests can't leak state into
    each other (e.g. one test's idempotency key colliding with another's)."""
    atlas_api.ATLAS_RESERVATIONS.clear()
    atlas_api.ATLAS_IDEMPOTENCY_INDEX.clear()
    atlas_api.ATLAS_REMAINING_FAILURES.clear()
    atlas_api._next_reservation_number = 1

    nova_api.NOVA_BOOKINGS.clear()
    nova_api.NOVA_IDEMPOTENCY_INDEX.clear()
    nova_api.NOVA_REMAINING_FAILURES.clear()
    nova_api._next_booking_number = 1
    yield


@pytest.fixture
def atlas_adapter():
    """An AtlasAdapter wired directly to the mock Atlas ASGI app in-process -
    no real network call, no need for a running server."""
    transport = httpx.ASGITransport(app=atlas_api.app)
    return AtlasAdapter(base_url="http://atlas.test", transport=transport)


@pytest.fixture
def nova_adapter():
    transport = httpx.ASGITransport(app=nova_api.app)
    return NovaAdapter(base_url="http://nova.test", transport=transport)
