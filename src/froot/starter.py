"""Start (once) every configured froot loop — acting and advisory, one pass.

Run as a one-shot after the worker is up (a k8s Job, or ``python -m
froot.starter`` locally). It walks the loop registry: each acting
(commit-or-revert) loop named in ``FROOT_LOOPS`` gets a long-lived
``ScanWorkflow`` per repo; each advisory (emit-signal) loop that is enabled
gets its own per-repo review workflow. Every start uses
``ALLOW_DUPLICATE_FAILED_ONLY`` so a running loop is left untouched but a
terminated one can restart, and each tick re-derives its work and
continues-as-new (no cursor — derived, never stored).

This is the single entrypoint that replaced the per-family scan / review /
a11y starters: adding a loop is a registry spec (plus, for an advisory loop,
one row of start wiring), not a new starter module.

Config from the environment: ``TEMPORAL_*`` and the ``FROOT_*`` settings (the
repo list, the per-loop intervals, and the advisory enable flags
``FROOT_REVIEW_ENABLED`` / ``FROOT_A11Y_ENABLED``). Re-running is safe.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from froot.domain.loop import Loop
from froot.loops import registry
from froot.loops.registry import Disposition
from froot.policy.naming import (
    a11y_review_workflow_id,
    doc_refs_review_workflow_id,
    review_workflow_id,
    scan_workflow_id,
)
from froot.workflow.types import (
    A11yReviewScanParams,
    DocRefsReviewScanParams,
    ReviewScanParams,
    ScanParams,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from froot.domain.repo import TargetRepo

# The input every loop's self-scheduling root workflow takes.
_Params = (
    ScanParams
    | ReviewScanParams
    | A11yReviewScanParams
    | DocRefsReviewScanParams
)


@dataclass(frozen=True)
class _Start:
    """One workflow to (idempotently) start — the pure unit of work.

    Attributes:
        workflow_type: The registered workflow type to start by name
            (``ScanWorkflow`` / ``ReviewWorkflow`` / ``A11yReviewWorkflow``).
        params: The root workflow's input.
        workflow_id: The deterministic id (the singleton / idempotency key).
        label: A short human tag for the start log line.
        slug: The ``owner/name`` this start is for.
    """

    workflow_type: str
    params: _Params
    workflow_id: str
    label: str
    slug: str


@dataclass(frozen=True)
class _Advisory:
    """The bespoke start wiring for one advisory (emit-signal) loop.

    The advisory loops' root workflows are still their own (the per-PR engine
    is not unified), so each carries its workflow type, id namer, and params
    class, plus its own enable flag and poll interval from settings.

    Attributes:
        enabled: Whether this loop's enable flag is set.
        interval_seconds: This loop's poll cadence.
        workflow_type: The registered workflow type name.
        namer: The deterministic per-repo id namer.
        params: The params class this loop's workflow takes.
        label: A short human tag for the start log line.
    """

    enabled: bool
    interval_seconds: int
    workflow_type: str
    namer: Callable[[TargetRepo], str]
    params: (
        type[ReviewScanParams]
        | type[A11yReviewScanParams]
        | type[DocRefsReviewScanParams]
    )
    label: str


def advisory_wiring(
    *,
    review_enabled: bool,
    review_interval_seconds: int,
    a11y_enabled: bool,
    a11y_interval_seconds: int,
    doc_refs_enabled: bool,
    doc_refs_interval_seconds: int,
) -> dict[Loop, _Advisory]:
    """The advisory loops' bespoke start wiring, keyed by loop."""
    return {
        Loop.DETERMINISM_REVIEW: _Advisory(
            enabled=review_enabled,
            interval_seconds=review_interval_seconds,
            workflow_type="ReviewWorkflow",
            namer=review_workflow_id,
            params=ReviewScanParams,
            label="determinism",
        ),
        Loop.A11Y_REVIEW: _Advisory(
            enabled=a11y_enabled,
            interval_seconds=a11y_interval_seconds,
            workflow_type="A11yReviewWorkflow",
            namer=a11y_review_workflow_id,
            params=A11yReviewScanParams,
            label="a11y",
        ),
        Loop.DOC_REFS: _Advisory(
            enabled=doc_refs_enabled,
            interval_seconds=doc_refs_interval_seconds,
            workflow_type="DocRefsReviewWorkflow",
            namer=doc_refs_review_workflow_id,
            params=DocRefsReviewScanParams,
            label="doc-refs",
        ),
    }


def plans(
    *,
    repos: tuple[TargetRepo, ...],
    loops: tuple[Loop, ...],
    scan_interval_seconds: int,
    advisory: dict[Loop, _Advisory],
) -> tuple[_Start, ...]:
    """Every workflow to start, derived from the registry (pure).

    One pass over the registered loops, branched on disposition: an acting loop
    is started iff it is in ``loops`` (``FROOT_LOOPS``); an advisory loop iff
    its wiring is present and enabled. The set of loops, and which family each
    is in, comes from the registry — so a new loop is a registration, not an
    edit here.
    """
    out: list[_Start] = []
    for spec in registry.all_specs():
        loop = spec.loop
        if spec.disposition is Disposition.COMMIT_OR_REVERT:
            if loop not in loops:
                continue
            for target in repos:
                out.append(
                    _Start(
                        workflow_type="ScanWorkflow",
                        params=ScanParams(
                            target=target,
                            interval_seconds=scan_interval_seconds,
                            continuous=True,
                            loop=loop,
                        ),
                        workflow_id=scan_workflow_id(target, loop),
                        label=f"{loop.value} scan",
                        slug=target.repo.slug,
                    )
                )
            continue
        wiring = advisory.get(loop)
        if wiring is None or not wiring.enabled:
            continue
        for target in repos:
            out.append(
                _Start(
                    workflow_type=wiring.workflow_type,
                    params=wiring.params(
                        target=target,
                        interval_seconds=wiring.interval_seconds,
                        continuous=True,
                    ),
                    workflow_id=wiring.namer(target),
                    label=f"{wiring.label} review",
                    slug=target.repo.slug,
                )
            )
    return tuple(out)


async def _start() -> None:
    from temporalio.client import Client
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.contrib.pydantic import pydantic_data_converter
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.config.settings import (
        A11yReviewSettings,
        DocRefsReviewSettings,
        ReviewSettings,
        Settings,
        TemporalSettings,
    )

    settings = Settings()  # non-secret values come from the environment
    review = ReviewSettings()
    a11y = A11yReviewSettings()
    doc_refs = DocRefsReviewSettings()
    to_start = plans(
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
        ),
    )
    if not to_start:
        print("no loops to start (check FROOT_LOOPS and the enable flags)")
        return

    temporal = TemporalSettings()
    client = await Client.connect(
        temporal.host,
        namespace=temporal.namespace,
        data_converter=pydantic_data_converter,
    )
    queue = temporal.task_queue
    for plan in to_start:
        try:
            handle = await client.start_workflow(
                plan.workflow_type,
                plan.params,
                id=plan.workflow_id,
                task_queue=queue,
                id_reuse_policy=(
                    WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                ),
            )
            print(f"started {plan.label} loop {handle.id!r} for {plan.slug}")
        except WorkflowAlreadyStartedError:
            print(
                f"{plan.label} loop {plan.workflow_id!r} already running"
                " — untouched"
            )


def main() -> None:
    """Console entrypoint: start every configured loop, from the env."""
    asyncio.run(_start())


if __name__ == "__main__":
    main()
