"""
Tests for the Temporal booking workflow, run against Temporal's built-in
time-skipping test server (no real Temporal server needed - this is the
approach Temporal itself recommends for testing workflow logic). These
exercise the full path: workflow -> activities -> real adapters -> mock
supplier ASGI apps -> test database.
"""

import uuid

import pytest
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from app.db.database import SessionLocal
from app.db.models import BookingRecord
from app.workflows import activities
from app.workflows.booking_workflow import BookingWorkflow
from app.workflows.models import BookingRequestInput

TASK_QUEUE = "test-hotel-bookings"

ACTIVITIES = [
    activities.revalidate_offer,
    activities.create_supplier_reservation,
    activities.save_booking_record,
    activities.check_supplier_reservation_status,
    activities.update_booking_status,
    activities.cancel_supplier_reservation,
]


def make_input(key=None, expected_price=9408.0, simulate_failures=0, max_increase=5.0):
    return BookingRequestInput(
        idempotency_key=key or str(uuid.uuid4()),
        supplier_id="atlas",
        supplier_property_id="ATL-100",
        destination="Mumbai",
        check_in="2026-09-10",
        check_out="2026-09-12",
        guests=2,
        rooms=1,
        expected_total_price=expected_price,
        max_price_increase_pct=max_increase,
        simulate_supplier_failures=simulate_failures,
    )


@pytest.fixture
async def env():
    async with await WorkflowEnvironment.start_time_skipping() as environment:
        yield environment


def booking_count(idempotency_key: str) -> int:
    db = SessionLocal()
    try:
        return db.query(BookingRecord).filter_by(idempotency_key=idempotency_key).count()
    finally:
        db.close()


async def test_happy_path_confirms_booking(env):
    input = make_input()
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[BookingWorkflow], activities=ACTIVITIES):
        handle = await env.client.start_workflow(
            BookingWorkflow.run, input, id=f"booking-{input.idempotency_key}", task_queue=TASK_QUEUE
        )
        # The workflow stays open after confirming (so it can still be
        # cancelled later) - query current details rather than waiting on
        # workflow completion.
        status = await handle.query(BookingWorkflow.status)
        while status != "confirmed":
            status = await handle.query(BookingWorkflow.status)
        result = await handle.query(BookingWorkflow.details)

    assert result.status == "confirmed"
    assert result.supplier_reservation_reference is not None
    assert booking_count(input.idempotency_key) == 1


async def test_price_increase_beyond_threshold_fails_without_reserving(env):
    # expected_total_price is far below the real price the mock supplier
    # will report, so revalidation should reject it before ever reserving.
    input = make_input(expected_price=100.0)
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[BookingWorkflow], activities=ACTIVITIES):
        handle = await env.client.start_workflow(
            BookingWorkflow.run, input, id=f"booking-{input.idempotency_key}", task_queue=TASK_QUEUE
        )
        result = await handle.result()

    assert result.status == "failed"
    assert result.supplier_reservation_reference is None
    assert booking_count(input.idempotency_key) == 0


async def test_flaky_supplier_recovers_via_activity_retries(env):
    input = make_input(simulate_failures=2)
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[BookingWorkflow], activities=ACTIVITIES):
        handle = await env.client.start_workflow(
            BookingWorkflow.run, input, id=f"booking-{input.idempotency_key}", task_queue=TASK_QUEUE
        )
        status = await handle.query(BookingWorkflow.status)
        while status != "confirmed":
            status = await handle.query(BookingWorkflow.status)

    assert status == "confirmed"


async def test_duplicate_booking_request_does_not_create_a_second_record(env):
    """A booking's workflow stays open (to remain cancellable) even after
    it's confirmed. That means Temporal itself rejects a second
    start_workflow call with the same workflow ID while the first is still
    active - the strongest form of duplicate-booking prevention, enforced
    by the platform rather than application code. This mirrors exactly
    what app/api/main.py's create_booking endpoint catches and treats as
    "already in progress" rather than an error."""
    key = str(uuid.uuid4())
    workflow_id = f"booking-{key}"

    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[BookingWorkflow], activities=ACTIVITIES):
        handle1 = await env.client.start_workflow(BookingWorkflow.run, make_input(key=key), id=workflow_id, task_queue=TASK_QUEUE)
        status = await handle1.query(BookingWorkflow.status)
        while status != "confirmed":
            status = await handle1.query(BookingWorkflow.status)
        result1 = await handle1.query(BookingWorkflow.details)

        # The same booking request is submitted again (e.g. a retried HTTP
        # call after a client-side timeout) with the same idempotency key,
        # while the original booking is still active.
        with pytest.raises(WorkflowAlreadyStartedError):
            await env.client.start_workflow(BookingWorkflow.run, make_input(key=key), id=workflow_id, task_queue=TASK_QUEUE)

        handle2 = env.client.get_workflow_handle(workflow_id)
        result2 = await handle2.query(BookingWorkflow.details)

    assert result1.booking_id == result2.booking_id
    assert booking_count(key) == 1


async def test_cancellation_after_supplier_confirmation(env):
    input = make_input()
    workflow_id = f"booking-{input.idempotency_key}"

    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[BookingWorkflow], activities=ACTIVITIES):
        handle = await env.client.start_workflow(BookingWorkflow.run, input, id=workflow_id, task_queue=TASK_QUEUE)

        status = await handle.query(BookingWorkflow.status)
        while status != "confirmed":
            status = await handle.query(BookingWorkflow.status)

        await handle.signal(BookingWorkflow.cancel_booking)
        result = await handle.result()

    assert result.status == "cancelled"

    db = SessionLocal()
    try:
        booking = db.query(BookingRecord).filter_by(idempotency_key=input.idempotency_key).first()
        assert booking.status == "cancelled"
    finally:
        db.close()


async def test_workflow_recovers_after_worker_restart(env):
    """The workflow's state lives on the Temporal server, not in the worker
    process - so a worker crashing and a fresh one taking over should not
    lose or restart the booking."""
    input = make_input()
    workflow_id = f"booking-{input.idempotency_key}"

    # Start a worker, kick off the workflow, then let the worker be torn
    # down (end of the `async with` block) before it necessarily finishes -
    # simulating a worker crash mid-booking.
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[BookingWorkflow], activities=ACTIVITIES):
        handle = await env.client.start_workflow(BookingWorkflow.run, input, id=workflow_id, task_queue=TASK_QUEUE)

    # No worker is running right now. A brand new one picks up exactly
    # where the old one left off, using the same task queue.
    async with Worker(env.client, task_queue=TASK_QUEUE, workflows=[BookingWorkflow], activities=ACTIVITIES):
        status = await handle.query(BookingWorkflow.status)
        while status != "confirmed":
            status = await handle.query(BookingWorkflow.status)

    assert status == "confirmed"
    assert booking_count(input.idempotency_key) == 1
