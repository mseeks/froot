"""Run the dashboard standalone for local development.

Usage::

    python -m froot.dashboard

Connects its own Temporal client from the ``TEMPORAL_*`` environment (point it
at a ``kubectl port-forward`` of the frontend) and serves until interrupted. In
production the worker hosts the same server in-process — this entrypoint is only
for developing or eyeballing the page against live data from a laptop.
"""

from __future__ import annotations

import asyncio
import contextlib


async def _serve() -> None:
    from temporalio.client import Client

    from froot.config.settings import TemporalSettings
    from froot.dashboard.server import start
    from froot.workflow.runtime import DATA_CONVERTER

    settings = TemporalSettings()
    client = await Client.connect(
        settings.host,
        namespace=settings.namespace,
        data_converter=DATA_CONVERTER,
    )
    server = await start(client)
    async with server:
        await server.serve_forever()


def main() -> None:
    """Console entrypoint: serve the dashboard until Ctrl-C."""
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_serve())


if __name__ == "__main__":
    main()
