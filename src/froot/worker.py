"""The Temporal worker entrypoint — the runnable assembly.

Connects to Temporal with the Pydantic data converter and registers the whole
runtime: both workflows and every activity. Run it once a Temporal server is
reachable::

    python -m froot.worker

The connection is env-configured so the same image runs anywhere:
``TEMPORAL_HOST`` (default ``localhost:7233``), ``TEMPORAL_NAMESPACE`` (default
``default``), and ``TEMPORAL_TASK_QUEUE`` (default ``froot``). The adapters read
their own keys (``FROOT_GITHUB_TOKEN``) and the model endpoint
(``FROOT_OLLAMA_URL`` / ``FROOT_OLLAMA_MODEL``) from the environment.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from temporalio.client import Client
from temporalio.worker import Worker

from froot.adapters.telemetry import (
    metrics_runtime,
    setup_tracing,
    shutdown_tracing,
    tracing_interceptors,
)
from froot.config.settings import DashboardSettings, TemporalSettings
from froot.workflow.runtime import ALL_ACTIVITIES, DATA_CONVERTER, WORKFLOWS

# Process one activity at a time: the model judge calls a single local Gemma
# (which serializes anyway), and the household/hobby volume never needs more.
# The durable CI wait sleeps between polls, so it does not hold this slot.
_MAX_CONCURRENT_ACTIVITIES = 1


async def run_worker(
    *,
    target_host: str | None = None,
    namespace: str | None = None,
    task_queue: str | None = None,
) -> None:
    """Connect to Temporal and run the worker until cancelled.

    Each parameter falls back to its ``TEMPORAL_*`` environment variable
    (via :class:`~froot.config.settings.TemporalSettings`), then to the default,
    so a deployment configures the worker purely through env.
    """
    settings = TemporalSettings()
    host = target_host or settings.host
    ns = namespace or settings.namespace
    queue = task_queue or settings.task_queue
    setup_tracing("froot-worker")
    client = await Client.connect(
        host,
        namespace=ns,
        data_converter=DATA_CONVERTER,
        interceptors=tracing_interceptors(),
        runtime=metrics_runtime(),
    )
    worker = Worker(
        client,
        task_queue=queue,
        workflows=WORKFLOWS,
        activities=ALL_ACTIVITIES,
        max_concurrent_activities=_MAX_CONCURRENT_ACTIVITIES,
    )
    # Run until SIGTERM/SIGINT, then shut down gracefully and flush telemetry
    # (atexit does NOT run on an unhandled signal, so the last span batch would
    # otherwise be dropped on every Recreate rollout).
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    # The read-model dashboard shares this process and this client (lazy import
    # so httpx/the dashboard never load when it is switched off). It serves a
    # derived 10,000ft view; reach it with `kubectl port-forward`. A failure to
    # start it (e.g. the port is taken) must never take the worker down — it is
    # a non-load-bearing debug surface, so degrade to running without it.
    dashboard = None
    if DashboardSettings().enabled:
        from froot.dashboard.server import start as start_dashboard

        try:
            dashboard = await start_dashboard(client)
        except Exception:
            logging.getLogger("froot.worker").exception(
                "dashboard failed to start; running worker without it"
            )
    try:
        async with worker:
            await stop.wait()
    finally:
        if dashboard is not None:
            dashboard.close()
            with contextlib.suppress(Exception):
                await dashboard.wait_closed()
        shutdown_tracing()


def main() -> None:
    """Console entrypoint: run the worker, configured from the environment."""
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
