"""The self-scheduling doc-coherence-review loop — froot's per-repo doc auditor.

One long-lived workflow per repo: each tick lists the open PRs and dispatches a
per-PR doc-coherence review (idempotent per PR + head SHA), then sleeps and
continues-as-new, keeping history bounded to one tick. Stores nothing (derive,
never store); advisory, so a slow tick just reviews on the next commit.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from froot.workflow import activities
    from froot.workflow.constants import (
        CI_CHECK_TIMEOUT,
        DISPATCH_TIMEOUT,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        DispatchDocCoherenceInput,
        DocCoherenceReviewScanParams,
        DocCoherenceReviewScanResult,
    )


@workflow.defn
class DocCoherenceReviewWorkflow:
    """The durable doc-coherence-review loop (one tick per continue-as-new)."""

    @workflow.run
    async def run(
        self, params: DocCoherenceReviewScanParams
    ) -> DocCoherenceReviewScanResult:
        """List open PRs, dispatch a review each, then loop or return."""
        prs = await workflow.execute_activity(
            activities.list_review_prs,
            params.target,
            start_to_close_timeout=CI_CHECK_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        for pr in prs:
            await workflow.execute_activity(
                activities.dispatch_pr_doc_coherence_review,
                DispatchDocCoherenceInput(target=params.target, pr=pr),
                start_to_close_timeout=DISPATCH_TIMEOUT,
                retry_policy=TOOL_RETRY,
            )
        result = DocCoherenceReviewScanResult(
            reviewed=len(prs), dispatched=len(prs)
        )
        if not params.continuous:
            return result
        # Durable loop: sleep, then restart fresh. continue_as_new raises, so
        # nothing runs after it and history stays bounded to one tick.
        await workflow.sleep(timedelta(seconds=params.interval_seconds))
        workflow.continue_as_new(
            DocCoherenceReviewScanParams(
                target=params.target,
                interval_seconds=params.interval_seconds,
                continuous=True,
            )
        )
