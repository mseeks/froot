"""Start (once) the durable determinism-review loop for each configured repo.

Run as a one-shot after the worker is up (a k8s Job, or ``python -m
froot.review_starter`` locally). For every repo in ``FROOT_REPOS`` it submits a
long-lived ``ReviewWorkflow`` — workflow id ``froot-review-<owner>-<name>``,
``ALLOW_DUPLICATE_FAILED_ONLY`` so a running loop is left untouched but a
terminated one can restart. Each tick re-derives the repo's open PRs and
continues-as-new (no cursor — derived, never stored).

Skips entirely when ``FROOT_REVIEW_ENABLED`` is off. Config from the
environment: ``TEMPORAL_*`` and the ``FROOT_*`` settings (the repo list, the
review poll interval). Re-running is safe.
"""

from __future__ import annotations

import asyncio


async def _start() -> None:
    from temporalio.client import Client
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.config.settings import (
        ReviewSettings,
        Settings,
        TemporalSettings,
    )
    from froot.policy.naming import review_workflow_id
    from froot.workflow.review_workflow import ReviewWorkflow
    from froot.workflow.types import ReviewScanParams

    review = ReviewSettings()
    if not review.enabled:
        print("determinism review disabled (FROOT_REVIEW_ENABLED) — no loops")
        return

    settings = Settings()  # non-secret values come from the environment
    temporal = TemporalSettings()
    client = await Client.connect(
        temporal.host,
        namespace=temporal.namespace,
        data_converter=pydantic_data_converter,
    )
    queue = temporal.task_queue
    for target in settings.repos:
        workflow_id = review_workflow_id(target)
        params = ReviewScanParams(
            target=target,
            interval_seconds=review.poll_interval_seconds,
            continuous=True,
        )
        try:
            handle = await client.start_workflow(
                ReviewWorkflow.run,
                params,
                id=workflow_id,
                task_queue=queue,
                id_reuse_policy=(
                    WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                ),
            )
            print(f"started review loop {handle.id!r} for {target.repo.slug}")
        except WorkflowAlreadyStartedError:
            print(f"review loop {workflow_id!r} already running — untouched")


def main() -> None:
    """Console entrypoint: start the review loops, configured from the env."""
    asyncio.run(_start())


if __name__ == "__main__":
    main()
