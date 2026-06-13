"""The Temporal worker entrypoint — the runnable assembly.

Connects to Temporal with the Pydantic data converter and registers the whole
runtime: all four workflows and every activity. Run it once a Temporal server is
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
import sys

from temporalio.client import Client
from temporalio.worker import Worker

from froot.adapters.telemetry import (
    metrics_runtime,
    setup_tracing,
    shutdown_tracing,
    tracing_interceptors,
)
from froot.config.settings import (
    DashboardSettings,
    TemporalSettings,
    WorkerSettings,
)
from froot.workflow.runtime import ALL_ACTIVITIES, DATA_CONVERTER, WORKFLOWS


def configure_logging() -> None:
    """Send froot's structured outcome lines to stdout at INFO.

    The activities emit one JSON ``loop_outcome`` line per closed loop on the
    ``froot.*`` loggers at INFO — the cheap, human-readable half of "derive,
    never store", and the stream the deploy points operators (and the ClickStack
    filelog) at. A logger with no configured handler defaults to WARNING, so
    without this those INFO lines are silently dropped. Attach a single stdout
    handler at INFO that emits the record verbatim (the message is already JSON,
    so it stays machine-parseable), and pin the chatty ``temporalio`` SDK at
    WARNING so the outcome lines are not buried in poll/heartbeat noise.

    Idempotent: a second call neither duplicates the handler nor lowers levels.
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    already = any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stdout
        for h in root.handlers
    )
    if not already:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
    logging.getLogger("temporalio").setLevel(logging.WARNING)


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
    # Run several activities concurrently (default 4, env-configurable) so
    # independent loops' model adjudications overlap instead of serializing
    # behind one in-flight call; the local Gemma now serves them concurrently.
    # The durable CI wait is a workflow timer, so a bump on CI holds no slot.
    worker = Worker(
        client,
        task_queue=queue,
        workflows=WORKFLOWS,
        activities=ALL_ACTIVITIES,
        max_concurrent_activities=WorkerSettings().max_concurrent_activities,
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
    configure_logging()
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
