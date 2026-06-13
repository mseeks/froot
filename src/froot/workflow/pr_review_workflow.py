"""A single PR's determinism review — analyze, adjudicate, comment (advisory).

A linear, durable pipeline (not a branching state machine — the flow is three
steps): analyze the workflow surface at the PR head, adjudicate the ambiguous
frontier with the model (only when there is one), synthesize the findings
(pure), and upsert one advisory comment. Idempotent per (PR, head SHA) via its
workflow id, so a new commit is a new review that edits the comment in place.

All AST, model, and GitHub work happens in activities; the workflow body only
orchestrates and runs one pure policy call (:func:`synthesize_findings`), so it
stays deterministic and passes the determinism gate itself.
"""

from __future__ import annotations

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from froot.domain.determinism import FrontierVerdict, PrReviewResult
    from froot.policy.review_comment import synthesize_findings
    from froot.workflow import activities
    from froot.workflow.constants import (
        ACTIVITY_TIMEOUT,
        CI_CHECK_TIMEOUT,
        HEARTBEAT_TIMEOUT,
        MODEL_ACTIVITY_TIMEOUT,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        AdjudicateInput,
        PostReviewInput,
        PrReviewParams,
    )


@workflow.defn
class PrReviewWorkflow:
    """Review one PR for transitive determinism hazards (advisory)."""

    @workflow.run
    async def run(self, params: PrReviewParams) -> PrReviewResult:
        """Analyze, adjudicate the frontier, then post the advisory comment."""
        analysis = await workflow.execute_activity(
            activities.analyze_pr,
            params,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        verdicts: tuple[FrontierVerdict, ...] = ()
        if analysis.frontier:
            verdicts = await workflow.execute_activity(
                activities.adjudicate_frontier,
                AdjudicateInput(frontier=analysis.frontier),
                start_to_close_timeout=MODEL_ACTIVITY_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=TOOL_RETRY,
            )
        findings = synthesize_findings(
            analysis.hazards, analysis.frontier, verdicts
        )
        comment_url = await workflow.execute_activity(
            activities.post_review,
            PostReviewInput(
                target=params.target, pr=params.pr, findings=findings
            ),
            start_to_close_timeout=CI_CHECK_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        return PrReviewResult(
            pr_number=params.pr.number,
            head_sha=params.pr.head_sha,
            lexical_count=len(analysis.lexical),
            findings=findings,
            comment_url=comment_url,
        )
