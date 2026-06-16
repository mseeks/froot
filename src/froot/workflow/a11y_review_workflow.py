"""The self-scheduling a11y-review loop — froot's per-repo a11y reviewer.

One long-lived workflow per target repo. Each tick lists the repo's open PRs and
dispatches a per-PR a11y review (idempotent per PR + head SHA, so re-polling and
unchanged commits are no-ops); then it sleeps and continues-as-new, keeping
history bounded to one tick. Like the determinism reviewer it stores nothing —
the work is re-derived from GitHub each tick (derive, never store) — and it is
advisory, so it never needs to win a merge race; a slow tick just reviews on the
next commit.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.exceptions import FailureError

with workflow.unsafe.imports_passed_through():
    from froot.workflow import activities
    from froot.workflow.constants import (
        CI_CHECK_TIMEOUT,
        DISPATCH_TIMEOUT,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        A11yReviewScanParams,
        A11yReviewScanResult,
        DispatchA11yInput,
    )


@workflow.defn
class A11yReviewWorkflow:
    """The durable a11y-review loop (one tick per continue-as-new)."""

    @workflow.run
    async def run(self, params: A11yReviewScanParams) -> A11yReviewScanResult:
        """List open PRs, dispatch an a11y review each, then loop/return."""
        reviewed = 0
        try:
            prs = await workflow.execute_activity(
                activities.list_review_prs,
                params.target,
                start_to_close_timeout=CI_CHECK_TIMEOUT,
                retry_policy=TOOL_RETRY,
            )
            for pr in prs:
                await workflow.execute_activity(
                    activities.dispatch_pr_a11y_review,
                    DispatchA11yInput(target=params.target, pr=pr),
                    start_to_close_timeout=DISPATCH_TIMEOUT,
                    retry_policy=TOOL_RETRY,
                )
            reviewed = len(prs)
        except FailureError:
            # A failed tick is just a slow tick: a one-shot run fails loudly,
            # but the durable loop logs and rides it out so a transient upstream
            # fault (e.g. a brief GitHub 401, raised non-retryable) can't
            # terminate the whole continue-as-new loop. Next tick re-derives it.
            if not params.continuous:
                raise
            workflow.logger.warning(
                "a11y-review tick failed for %s; retrying next tick",
                params.target.repo.slug,
                exc_info=True,
            )
        result = A11yReviewScanResult(reviewed=reviewed, dispatched=reviewed)
        if not params.continuous:
            return result
        # Durable loop: sleep, then restart fresh. continue_as_new raises, so
        # nothing runs after it and history stays bounded to one tick.
        await workflow.sleep(timedelta(seconds=params.interval_seconds))
        workflow.continue_as_new(
            A11yReviewScanParams(
                target=params.target,
                interval_seconds=params.interval_seconds,
                continuous=True,
            )
        )
