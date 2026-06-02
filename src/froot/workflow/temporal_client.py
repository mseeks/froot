"""A lazily-connected, process-wide Temporal client for activities.

The scan loop's dispatch activity starts a bump workflow per candidate, so it
needs a client. This connects one per process on first use and caches it. It is
intentionally free of telemetry imports so it can sit in the activity import
graph without pulling OpenTelemetry across the workflow-sandbox boundary.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from temporalio.client import Client

# Connected on first use; reset by ``tests/conftest.py`` between tests.
_CLIENT: Client | None = None


def task_queue() -> str:
    """The task queue the workers listen on (``TEMPORAL_TASK_QUEUE``)."""
    from froot.config.settings import TemporalSettings

    return TemporalSettings().task_queue


async def _connect() -> Client:
    from temporalio.client import Client
    from temporalio.contrib.pydantic import pydantic_data_converter

    from froot.config.settings import TemporalSettings

    settings = TemporalSettings()
    return await Client.connect(
        settings.host,
        namespace=settings.namespace,
        data_converter=pydantic_data_converter,
    )


async def client() -> Client:
    """The process-wide Temporal client, connected on first use."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = await _connect()
    return _CLIENT
