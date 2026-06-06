"""Start (once) the durable scan loop for each configured repo.

Run as a one-shot after the worker is up (a k8s Job, or ``python -m
froot.scan_starter`` locally). For every repo in ``FROOT_REPOS`` it submits a
long-lived ``ScanWorkflow`` — workflow id ``froot-scan-<owner>-<name>``,
``ALLOW_DUPLICATE_FAILED_ONLY`` so a running loop is left untouched but a
terminated one can restart. Each tick re-derives the outstanding patches from
the repo and continues-as-new (no cursor — derived, never stored).

Config from the environment: ``TEMPORAL_HOST`` / ``TEMPORAL_NAMESPACE`` /
``TEMPORAL_TASK_QUEUE`` and the ``FROOT_*`` settings (the repo list + scan
interval). Re-running is safe.
"""

from __future__ import annotations

import asyncio


async def _start() -> None:
    from temporalio.client import Client
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.config.settings import Settings, TemporalSettings
    from froot.policy.naming import scan_workflow_id
    from froot.workflow.scan_workflow import ScanWorkflow
    from froot.workflow.types import ScanParams

    settings = Settings()  # non-secret values come from the environment
    temporal = TemporalSettings()
    client = await Client.connect(
        temporal.host,
        namespace=temporal.namespace,
        data_converter=pydantic_data_converter,
    )
    queue = temporal.task_queue
    for loop in settings.loops:
        for target in settings.repos:
            workflow_id = scan_workflow_id(target, loop)
            params = ScanParams(
                target=target,
                interval_seconds=settings.scan_interval_seconds,
                continuous=True,
                loop=loop,
            )
            try:
                handle = await client.start_workflow(
                    ScanWorkflow.run,
                    params,
                    id=workflow_id,
                    task_queue=queue,
                    id_reuse_policy=(
                        WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                    ),
                )
                print(
                    f"started {loop.value} scan loop {handle.id!r} "
                    f"for {target.repo.slug}"
                )
            except WorkflowAlreadyStartedError:
                print(f"scan loop {workflow_id!r} already running — untouched")


def main() -> None:
    """Console entrypoint: start the scan loops, configured from the env."""
    asyncio.run(_start())


if __name__ == "__main__":
    main()
