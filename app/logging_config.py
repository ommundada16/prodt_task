"""
Shared logging setup. Log messages use plain key=value pairs (request_id=...,
workflow_id=..., booking_id=..., supplier=..., supplier_reference=...) so
they stay greppable without pulling in a JSON logging library for a
prototype. Never log customer secrets, credentials, or personal data - this
app doesn't collect any, by design.
"""

import logging


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
