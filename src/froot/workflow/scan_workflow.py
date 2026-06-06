"""The self-scheduling scan loop — froot's durable trigger (per repo).

One long-lived workflow per target repo. Each tick checks out the repo, selects
the patch candidates, and dispatches a bump loop per candidate (idempotent, so
re-dispatch is a no-op); then it sleeps and continues-as-new, keeping history
bounded to one tick. There is no stored seen-set — the outstanding work is
re-derived from the repo each tick (derive, never store), and the per-bump
workflow id makes re-proposing an already-handled bump a no-op.

A one-shot run (``continuous=False``, the default) performs a single tick and
returns; production starts it once with ``continuous=True`` and it runs forever.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from froot.workflow import activities
    from froot.workflow.constants import (
        ACTIVITY_TIMEOUT,
        DISPATCH_TIMEOUT,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        DispatchInput,
        ReconcileInput,
        ScanCandidatesInput,
        ScanParams,
        ScanResult,
    )


@workflow.defn
class ScanWorkflow:
    """The durable dependency-scan loop (one tick per continue-as-new)."""

    @workflow.run
    async def run(self, params: ScanParams) -> ScanResult:
        """Scan, dispatch each, reconcile stale PRs, then loop or return."""
        candidates = await workflow.execute_activity(
            activities.scan_candidates,
            ScanCandidatesInput(target=params.target, loop=params.loop),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        for candidate in candidates:
            await workflow.execute_activity(
                activities.dispatch_bump,
                DispatchInput(
                    target=params.target,
                    candidate=candidate,
                    loop=params.loop,
                ),
                start_to_close_timeout=DISPATCH_TIMEOUT,
                retry_policy=TOOL_RETRY,
            )
        # Close this loop's PRs a newer target superseded — re-derived from the
        # repo each tick, same as the scan, and scoped to the loop's namespace.
        reconciled = await workflow.execute_activity(
            activities.reconcile_open_prs,
            ReconcileInput(target=params.target, loop=params.loop),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        result = ScanResult(
            found=len(candidates),
            dispatched=len(candidates),
            reconciled=reconciled,
        )
        if not params.continuous:
            return result
        # Durable loop: sleep, then restart fresh. continue_as_new raises, so
        # nothing runs after it and history stays bounded to one tick.
        await workflow.sleep(timedelta(seconds=params.interval_seconds))
        workflow.continue_as_new(
            ScanParams(
                target=params.target,
                interval_seconds=params.interval_seconds,
                continuous=True,
                loop=params.loop,
            )
        )
