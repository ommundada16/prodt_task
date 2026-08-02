"""A single shared Temporal client for the FastAPI app to start/query/signal workflows with."""

from temporalio.client import Client

from app.workflows.worker import TEMPORAL_SERVER_ADDRESS

_client: Client | None = None


async def get_temporal_client() -> Client:
    global _client
    if _client is None:
        _client = await Client.connect(TEMPORAL_SERVER_ADDRESS)
    return _client
