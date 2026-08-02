"""
The booking lifecycle, implemented as a Temporal workflow.

Steps: revalidate price -> check it hasn't moved too much -> create the
supplier reservation -> save the internal booking record -> poll the
supplier until it confirms (or the polling window runs out) -> mark the
booking accordingly. Once confirmed, the workflow stays open (rather than
completing) so the booking can still be cancelled later - it only finishes
once cancelled, or once it fails/needs manual review earlier in the flow.

Workflow code itself does no I/O - every external call is delegated to an
activity (see activities.py). That's what lets Temporal retry a failed
step on its own, and correctly resume this workflow (from wherever it
left off) if the worker process crashes and restarts.
"""

import asyncio
from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from app.workflows import activities
    from app.workflows.models import BookingRequestInput, BookingResult

ACTIVITY_TIMEOUT = timedelta(seconds=10)
DEFAULT_RETRY_POLICY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)

POLL_INTERVAL = timedelta(seconds=2)
MAX_POLL_ATTEMPTS = 10


@workflow.defn
class BookingWorkflow:
    def __init__(self) -> None:
        self._status = "started"
        self._booking_id: Optional[int] = None
        self._reservation_reference: Optional[str] = None
        self._reason: Optional[str] = None
        self._cancel_requested = False

    @workflow.query
    def status(self) -> str:
        """Lets a caller check progress without waiting for the workflow to finish."""
        return self._status

    @workflow.query
    def details(self) -> BookingResult:
        """Current booking details, safe to call at any point - including
        while the workflow is still open (e.g. confirmed and waiting for a
        possible later cancellation) and after it has completed. Callers
        should use this instead of waiting on the workflow's final result,
        since a confirmed booking's workflow does not complete until it is
        eventually cancelled."""
        return BookingResult(
            booking_id=self._booking_id,
            status=self._status,
            supplier_reservation_reference=self._reservation_reference,
            reason=self._reason,
        )

    @workflow.signal
    async def cancel_booking(self) -> None:
        self._cancel_requested = True

    @workflow.run
    async def run(self, input: BookingRequestInput) -> BookingResult:
        workflow_id = workflow.info().workflow_id
        self._status = "revalidating"
        current_price = await workflow.execute_activity(
            activities.revalidate_offer,
            input,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )

        price_increase_pct = (current_price - input.expected_total_price) / input.expected_total_price * 100
        if price_increase_pct > input.max_price_increase_pct:
            self._status = "failed"
            self._reason = (
                f"Price increased by {price_increase_pct:.1f}%, above the "
                f"{input.max_price_increase_pct}% accepted threshold"
            )
            workflow.logger.info(f"workflow_id={workflow_id} status=failed reason=price_increase")
            return BookingResult(
                booking_id=None,
                status="failed",
                supplier_reservation_reference=None,
                reason=self._reason,
            )

        self._status = "reserving"
        try:
            reservation_reference = await workflow.execute_activity(
                activities.create_supplier_reservation,
                input,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
        except ActivityError as exc:
            self._status = "failed"
            self._reason = f"Supplier reservation failed after retries: {exc}"
            workflow.logger.info(f"workflow_id={workflow_id} status=failed reason=reservation_failed")
            return BookingResult(
                booking_id=None,
                status="failed",
                supplier_reservation_reference=None,
                reason=self._reason,
            )

        self._reservation_reference = reservation_reference
        self._status = "saving_booking_record"
        try:
            self._booking_id = await workflow.execute_activity(
                activities.save_booking_record,
                args=[input, reservation_reference, workflow_id],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
        except ActivityError as exc:
            # Compensation: the supplier reservation succeeded but we
            # could not record it internally even after retries. Rather
            # than leave an orphaned supplier booking with no internal
            # trace, cancel it at the supplier and flag for a human to
            # double check instead of silently losing track of it.
            self._status = "manual_review"
            self._reason = f"Internal booking record failed after supplier reservation succeeded: {exc}"
            workflow.logger.info(
                f"workflow_id={workflow_id} supplier_reference={reservation_reference} "
                f"status=manual_review reason=internal_save_failed"
            )
            await workflow.execute_activity(
                activities.cancel_supplier_reservation,
                args=[input, reservation_reference],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            return BookingResult(
                booking_id=None,
                status="manual_review",
                supplier_reservation_reference=reservation_reference,
                reason=self._reason,
            )

        final_status, reason = await self._wait_for_confirmation(input, reservation_reference)
        self._reason = reason

        if final_status == "confirmed":
            self._status = "confirmed"
            await self._persist_status("confirmed", None)
            workflow.logger.info(f"workflow_id={workflow_id} booking_id={self._booking_id} status=confirmed")

            # A confirmed booking can still be cancelled later (e.g. the
            # guest's plans change before check-in). Stay open and listen
            # for a cancellation signal instead of closing the workflow
            # immediately - this is what lets /bookings/{id}/cancel keep
            # working even after the booking is already confirmed.
            await workflow.wait_condition(lambda: self._cancel_requested)

            self._status = "cancelling"
            await workflow.execute_activity(
                activities.cancel_supplier_reservation,
                args=[input, reservation_reference],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            final_status, reason = "cancelled", "Cancelled by user request after confirmation"
            self._reason = reason

        self._status = final_status
        await self._persist_status(final_status, reason)
        workflow.logger.info(f"workflow_id={workflow_id} booking_id={self._booking_id} status={final_status}")

        return BookingResult(
            booking_id=self._booking_id,
            status=final_status,
            supplier_reservation_reference=reservation_reference,
            reason=reason,
        )

    async def _persist_status(self, status: str, reason: Optional[str]) -> None:
        await workflow.execute_activity(
            activities.update_booking_status,
            args=[self._booking_id, status, reason],
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=DEFAULT_RETRY_POLICY,
        )

    async def _wait_for_confirmation(self, input: BookingRequestInput, reservation_reference: str) -> tuple[str, Optional[str]]:
        self._status = "waiting_for_confirmation"

        for _ in range(MAX_POLL_ATTEMPTS):
            if self._cancel_requested:
                break

            supplier_status = await workflow.execute_activity(
                activities.check_supplier_reservation_status,
                args=[input, reservation_reference],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )

            if supplier_status == "confirmed":
                return "confirmed", None
            if supplier_status in ("cancelled", "failed"):
                return "manual_review", f"Supplier reported status '{supplier_status}' while waiting for confirmation"

            await asyncio.sleep(POLL_INTERVAL.total_seconds())

        if self._cancel_requested:
            await workflow.execute_activity(
                activities.cancel_supplier_reservation,
                args=[input, reservation_reference],
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            return "cancelled", "Cancelled by user request"

        return "manual_review", "Supplier did not confirm within the polling window"
