"""The self-scheduling determinism-review loop — froot's per-repo PR reviewer.

One long-lived workflow per target repo. Each tick lists the repo's open PRs and
dispatches a per-PR review (idempotent per PR + head SHA, so re-polling and
unchanged commits are no-ops); then it sleeps and continues-as-new, keeping
history bounded to one tick. Like the scan loop it stores nothing — the work is
re-derived from GitHub each tick (derive, never store).

A one-shot run (``continuous=False``, the default) does a single tick and
returns; production starts it once with ``continuous=True`` and it runs forever.
The loop is advisory, so it never needs to win a merge race — a slow tick just
reviews on the next commit.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from froot.workflow import activities
    from froot.workflow.constants import CI_CHECK_TIMEOUT, DISPATCH_TIMEOUT
    from froot.workflow.types import (
        DispatchReviewInput,
        ReviewScanParams,
        ReviewScanResult,
    )


@workflow.defn
class ReviewWorkflow:
    """The durable determinism-review loop (one tick per continue-as-new)."""

    @workflow.run
    async def run(self, params: ReviewScanParams) -> ReviewScanResult:
        """List open PRs, dispatch a review per PR, then loop or return."""
        prs = await workflow.execute_activity(
            activities.list_review_prs,
            params.target,
            start_to_close_timeout=CI_CHECK_TIMEOUT,
        )
        for pr in prs:
            await workflow.execute_activity(
                activities.dispatch_pr_review,
                DispatchReviewInput(target=params.target, pr=pr),
                start_to_close_timeout=DISPATCH_TIMEOUT,
            )
        result = ReviewScanResult(reviewed=len(prs), dispatched=len(prs))
        if not params.continuous:
            return result
        # Durable loop: sleep, then restart fresh. continue_as_new raises, so
        # nothing runs after it and history stays bounded to one tick.
        await workflow.sleep(timedelta(seconds=params.interval_seconds))
        workflow.continue_as_new(
            ReviewScanParams(
                target=params.target,
                interval_seconds=params.interval_seconds,
                continuous=True,
            )
        )
