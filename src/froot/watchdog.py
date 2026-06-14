"""Periodic loop-liveness watchdog: restart dead loops, alert when it must.

froot's loops are long-lived continue-as-new workflows. Temporal resumes them
across worker restarts, but a workflow that *terminally* fails stays dead with
nothing to resurrect it — one did, silently, for days. This watchdog is the
supervisor that closes that gap. Run it on a schedule (a k8s CronJob) a layer
below the workflows it watches, so it can't share their failure mode.

It reuses the starter's pure plan of every configured loop, then for each tries
an idempotent start (``ALLOW_DUPLICATE_FAILED_ONLY``): a running loop raises
``WorkflowAlreadyStartedError`` and is left untouched; a terminally-dead one
starts fresh. A revived loop is a real, non-transient failure — Temporal already
self-heals the transient ones — so the watchdog posts an ntfy alert naming what
it had to bring back, and stays silent when everything is healthy. The alert
fires every tick a loop stays dead, the right escalation for one that keeps
failing.

Config from the environment, exactly as the starter and worker read it
(``TEMPORAL_*``, the repo list, the loop selection, the advisory flags, and
``FROOT_NTFY_TOPIC`` for the alerts). Run as ``python -m froot.watchdog``.
"""

from __future__ import annotations

import asyncio
import json
import logging

from froot.starter import advisory_wiring, plans

_log = logging.getLogger("froot.watchdog")


def revival_alert(revived: tuple[str, ...]) -> tuple[str, str] | None:
    """The ``(title, message)`` to alert on, or ``None`` if nothing was revived.

    Pure, so the one decision that matters — alert iff a loop was brought back —
    is testable without a Temporal client.
    """
    if not revived:
        return None
    count = len(revived)
    title = f"froot revived {count} dead loop{'s' if count != 1 else ''}"
    return title, "\n".join(revived)


async def _watch() -> None:
    from temporalio.client import Client
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.adapters.ntfy import notify
    from froot.config.settings import (
        A11yReviewSettings,
        DocCoherenceReviewSettings,
        DocRefsReviewSettings,
        NtfySettings,
        ReviewSettings,
        Settings,
        TemporalSettings,
    )

    settings = Settings()  # non-secret values come from the environment
    review = ReviewSettings()
    a11y = A11yReviewSettings()
    doc_refs = DocRefsReviewSettings()
    doc_coherence = DocCoherenceReviewSettings()
    expected = plans(
        repos=settings.repos,
        loops=settings.loops,
        scan_interval_seconds=settings.scan_interval_seconds,
        advisory=advisory_wiring(
            review_enabled=review.enabled,
            review_interval_seconds=review.poll_interval_seconds,
            a11y_enabled=a11y.enabled,
            a11y_interval_seconds=a11y.poll_interval_seconds,
            doc_refs_enabled=doc_refs.enabled,
            doc_refs_interval_seconds=doc_refs.poll_interval_seconds,
            doc_coherence_enabled=doc_coherence.enabled,
            doc_coherence_interval_seconds=doc_coherence.poll_interval_seconds,
        ),
    )
    if not expected:
        print("watchdog: no loops configured")
        return

    temporal = TemporalSettings()
    client = await Client.connect(
        temporal.host,
        namespace=temporal.namespace,
        data_converter=pydantic_data_converter,
    )
    queue = temporal.task_queue
    revived: list[str] = []
    for plan in expected:
        try:
            await client.start_workflow(
                plan.workflow_type,
                plan.params,
                id=plan.workflow_id,
                task_queue=queue,
                id_reuse_policy=(
                    WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                ),
            )
        except WorkflowAlreadyStartedError:
            continue  # healthy — running, left untouched
        revived.append(f"{plan.label} · {plan.slug}")
        print(f"watchdog: revived {plan.label} loop {plan.workflow_id!r}")
    _log.info(
        json.dumps(
            {
                "event": "watchdog_tick",
                "checked": len(expected),
                "revived": len(revived),
            }
        )
    )
    alert = revival_alert(tuple(revived))
    if alert is not None:
        title, message = alert
        await notify(
            NtfySettings(),
            title=title,
            message=message,
            tags="rotating_light",
            priority="high",
        )


def main() -> None:
    """Console entrypoint: reconcile loop liveness once, from the env."""
    from froot.worker import configure_logging

    configure_logging()
    asyncio.run(_watch())


if __name__ == "__main__":
    main()
