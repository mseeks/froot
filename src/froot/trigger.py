"""Trigger an immediate one-shot scan of every configured acting loop.

Run as a one-shot (a k8s Job, or ``python -m froot.trigger``). For each acting
(commit-or-revert) loop in ``FROOT_LOOPS`` and each repo in ``FROOT_REPOS`` it
starts a *separate* one-shot :class:`~froot.workflow.scan_workflow.ScanWorkflow`
(``continuous=False``) that scans once and returns. It never touches the
long-lived scan loops: the one-shot carries a distinct ``-now`` workflow id, and
the bumps it dispatches use the same deterministic ids, so it opens PRs only for
work the scheduled loop hasn't already handled (no duplicates).

This is the non-destructive "scan now" the steward reaches for to verify a fresh
deploy or chase a just-introduced finding, instead of waiting out the daily
interval — no terminating or interrupting the running loops.
``FROOT_TRIGGER_LOOPS`` optionally narrows it to specific loops (default: all
acting loops in ``FROOT_LOOPS``); advisory loops are skipped (no ScanWorkflow).

Config from the environment: ``TEMPORAL_*`` and the ``FROOT_*`` settings (the
repo list and the loop list), plus the optional ``FROOT_TRIGGER_LOOPS`` filter.
Re-running is safe — a one-shot still in flight is left to finish.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from froot.domain.loop import Loop
from froot.loops import registry
from froot.loops.registry import Disposition
from froot.policy.naming import scan_workflow_id
from froot.workflow.types import ScanParams

if TYPE_CHECKING:
    from froot.domain.repo import TargetRepo


@dataclass(frozen=True)
class _OneShot:
    """One off-cycle scan to start — the pure unit of work.

    Attributes:
        params: The one-shot scan input (``continuous=False``).
        workflow_id: The ``-now`` id, distinct from the long-lived loop's.
        label: A short human tag for the start log line.
        slug: The ``owner/name`` this scan is for.
    """

    params: ScanParams
    workflow_id: str
    label: str
    slug: str


def parse_trigger_loops(value: str | None) -> tuple[Loop, ...] | None:
    """Parse ``FROOT_TRIGGER_LOOPS`` (comma-separated) into a filter.

    Returns ``None`` (meaning "every configured acting loop") for an empty or
    unset value; else the named loops. An unknown name raises ``ValueError``
    (via :class:`Loop`), so a typo fails loudly rather than scanning nothing.
    """
    if value is None or not value.strip():
        return None
    loops = tuple(
        Loop(entry.strip()) for entry in value.split(",") if entry.strip()
    )
    return loops or None


def oneshot_plans(
    *,
    repos: tuple[TargetRepo, ...],
    loops: tuple[Loop, ...],
    only: tuple[Loop, ...] | None = None,
) -> tuple[_OneShot, ...]:
    """Every one-shot scan to start (pure), one per (acting loop, repo).

    An acting loop is included iff it is in ``loops`` and, when ``only`` is
    given, also in ``only``. Advisory loops are skipped — they have no
    ScanWorkflow. The set of loops and their families come from the registry,
    so a new acting loop is reachable here by registration alone.
    """
    wanted = set(loops) if only is None else (set(loops) & set(only))
    out: list[_OneShot] = []
    for spec in registry.all_specs():
        loop = spec.loop
        if (
            spec.disposition is not Disposition.COMMIT_OR_REVERT
            or loop not in wanted
        ):
            continue
        for target in repos:
            out.append(
                _OneShot(
                    params=ScanParams(
                        target=target, continuous=False, loop=loop
                    ),
                    workflow_id=f"{scan_workflow_id(target, loop)}-now",
                    label=f"{loop.value} scan-now",
                    slug=target.repo.slug,
                )
            )
    return tuple(out)


async def _trigger() -> None:
    from temporalio.client import Client
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.config.settings import Settings, TemporalSettings

    settings = Settings()  # non-secret values come from the environment
    plans = oneshot_plans(
        repos=settings.repos,
        loops=settings.loops,
        only=parse_trigger_loops(os.environ.get("FROOT_TRIGGER_LOOPS")),
    )
    if not plans:
        print(
            "no acting loops to scan "
            "(check FROOT_LOOPS and FROOT_TRIGGER_LOOPS)"
        )
        return

    temporal = TemporalSettings()
    client = await Client.connect(
        temporal.host,
        namespace=temporal.namespace,
        data_converter=pydantic_data_converter,
    )
    queue = temporal.task_queue
    for plan in plans:
        try:
            handle = await client.start_workflow(
                "ScanWorkflow",
                plan.params,
                id=plan.workflow_id,
                task_queue=queue,
                # A finished one-shot can re-run; one still in flight is left.
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
            print(f"scan-now {plan.label} {handle.id!r} for {plan.slug}")
        except WorkflowAlreadyStartedError:
            print(f"scan-now {plan.workflow_id!r} already in flight — skipped")


def main() -> None:
    """Console entrypoint: start a one-shot scan for every configured loop."""
    asyncio.run(_trigger())


if __name__ == "__main__":
    main()
