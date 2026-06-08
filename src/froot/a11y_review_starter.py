"""Start (once) the durable a11y-review loop for each configured repo.

Run as a one-shot after the worker is up (a k8s Job, or ``python -m
froot.a11y_review_starter`` locally). For every repo in ``FROOT_REPOS`` it
submits a long-lived ``A11yReviewWorkflow`` — workflow id
``froot-a11y-<owner>-<name>``, ``ALLOW_DUPLICATE_FAILED_ONLY`` so a running loop
is left untouched but a terminated one can restart. Each tick re-derives the
repo's open PRs and continues-as-new (no cursor — derived, never stored).

Skips entirely when ``FROOT_A11Y_ENABLED`` is off (the default — a new loop
opts in deliberately, per MHE's observe-then-act staging). A repo with no Vue/
JSX templates simply yields no findings, so pointing the loop at a non-UI repo
is harmless. Config from the environment: ``TEMPORAL_*`` and the ``FROOT_*``
settings (the repo list, the a11y poll interval). Re-running is safe.
"""

from __future__ import annotations

import asyncio


async def _start() -> None:
    from temporalio.client import Client
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.config.settings import (
        A11yReviewSettings,
        Settings,
        TemporalSettings,
    )
    from froot.policy.naming import a11y_review_workflow_id
    from froot.workflow.a11y_review_workflow import A11yReviewWorkflow
    from froot.workflow.types import A11yReviewScanParams

    a11y = A11yReviewSettings()
    if not a11y.enabled:
        print("a11y review disabled (FROOT_A11Y_ENABLED) — no loops")
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
        workflow_id = a11y_review_workflow_id(target)
        params = A11yReviewScanParams(
            target=target,
            interval_seconds=a11y.poll_interval_seconds,
            continuous=True,
        )
        try:
            handle = await client.start_workflow(
                A11yReviewWorkflow.run,
                params,
                id=workflow_id,
                task_queue=queue,
                id_reuse_policy=(
                    WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                ),
            )
            print(f"started a11y loop {handle.id!r} for {target.repo.slug}")
        except WorkflowAlreadyStartedError:
            print(f"a11y loop {workflow_id!r} already running — untouched")


def main() -> None:
    """Console entrypoint: start the a11y loops, configured from the env."""
    asyncio.run(_start())


if __name__ == "__main__":
    main()
