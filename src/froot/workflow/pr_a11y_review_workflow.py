"""A single PR's a11y review — scan, adjudicate, comment (advisory).

A linear, durable pipeline (not a branching state machine — the flow is three
steps): scan the PR's changed templates at the head, adjudicate each flagged
site with the model (only when there is one), synthesize the findings (pure),
and upsert one advisory comment. Idempotent per (PR, head SHA) via its workflow
id, so a new commit is a new review that edits the comment in place.

All file, model, and GitHub work happens in activities; the workflow body only
orchestrates and runs one pure policy call (:func:`synthesize_a11y_findings`),
so it stays deterministic and passes the determinism gate itself.
"""

from __future__ import annotations

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from froot.domain.a11y import A11yVerdict, PrA11yResult
    from froot.policy.a11y_comment import synthesize_a11y_findings
    from froot.workflow import activities
    from froot.workflow.constants import (
        ACTIVITY_TIMEOUT,
        CI_CHECK_TIMEOUT,
        HEARTBEAT_TIMEOUT,
        MODEL_ACTIVITY_TIMEOUT,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        AdjudicateA11yInput,
        PostA11yInput,
        PrA11yReviewParams,
    )


@workflow.defn
class PrA11yReviewWorkflow:
    """Review one PR for source-level accessibility gaps (advisory)."""

    @workflow.run
    async def run(self, params: PrA11yReviewParams) -> PrA11yResult:
        """Scan the changed templates, adjudicate, then post the advisory."""
        analysis = await workflow.execute_activity(
            activities.scan_pr_a11y,
            params,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        verdicts: tuple[A11yVerdict, ...] = ()
        if analysis.candidates:
            verdicts = await workflow.execute_activity(
                activities.adjudicate_a11y,
                AdjudicateA11yInput(candidates=analysis.candidates),
                start_to_close_timeout=MODEL_ACTIVITY_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=TOOL_RETRY,
            )
        findings = synthesize_a11y_findings(analysis.candidates, verdicts)
        comment_url = await workflow.execute_activity(
            activities.post_a11y_review,
            PostA11yInput(
                target=params.target, pr=params.pr, findings=findings
            ),
            start_to_close_timeout=CI_CHECK_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        return PrA11yResult(
            pr_number=params.pr.number,
            head_sha=params.pr.head_sha,
            candidates=len(analysis.candidates),
            findings=findings,
            comment_url=comment_url,
        )
