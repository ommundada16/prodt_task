"""
Temporal worker process. This is what actually executes workflow and
activity code - the FastAPI app only starts/queries/signals workflows,
it never runs them directly.

Run with: python -m app.workflows.worker
(requires a Temporal server running - see docker-compose.yml)
"""

import asyncio
import os

from temporalio.client import Client
from temporalio.worker import Worker

from app.db.database import init_db
from app.logging_config import configure_logging
from app.workflows import activities
from app.workflows.booking_workflow import BookingWorkflow

TASK_QUEUE = "hotel-bookings"
TEMPORAL_SERVER_ADDRESS = os.getenv("TEMPORAL_SERVER_ADDRESS", "localhost:7233")


async def main() -> None:
    configure_logging()
    init_db()
    client = await Client.connect(TEMPORAL_SERVER_ADDRESS)
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[BookingWorkflow],
        activities=[
            activities.revalidate_offer,
            activities.create_supplier_reservation,
            activities.save_booking_record,
            activities.check_supplier_reservation_status,
            activities.update_booking_status,
            activities.cancel_supplier_reservation,
        ],
    )
    print(f"Worker started, listening on task queue '{TASK_QUEUE}'")
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
