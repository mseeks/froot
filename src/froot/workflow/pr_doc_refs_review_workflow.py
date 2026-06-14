"""A single PR's doc-refs review — scan, adjudicate, comment (advisory).

A linear, durable pipeline (three steps, not a branching state machine): scan
the PR's changed docs at the head for dangling references, adjudicate each with
the model (only when there is one), synthesize the findings (pure), and upsert
one advisory comment. Idempotent per (PR, head SHA) via its workflow id, so a
new commit is a new review that edits the comment in place.

All file, model, and GitHub work happens in activities; the workflow body only
orchestrates and runs one pure policy call
(:func:`synthesize_doc_ref_findings`), so it stays deterministic and passes the
determinism gate itself.
"""

from __future__ import annotations

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from froot.domain.doc_refs import DocRefVerdict, PrDocRefsResult
    from froot.policy.doc_refs_comment import synthesize_doc_ref_findings
    from froot.workflow import activities
    from froot.workflow.constants import (
        ACTIVITY_TIMEOUT,
        CI_CHECK_TIMEOUT,
        HEARTBEAT_TIMEOUT,
        MODEL_ACTIVITY_TIMEOUT,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        AdjudicateDocRefsInput,
        PostDocRefsInput,
        PrDocRefsReviewParams,
    )


@workflow.defn
class PrDocRefsReviewWorkflow:
    """Review one PR for dangling documentation references (advisory)."""

    @workflow.run
    async def run(self, params: PrDocRefsReviewParams) -> PrDocRefsResult:
        """Scan the changed docs, adjudicate, then post the advisory."""
        analysis = await workflow.execute_activity(
            activities.scan_pr_doc_refs,
            params,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        verdicts: tuple[DocRefVerdict, ...] = ()
        if analysis.candidates:
            verdicts = await workflow.execute_activity(
                activities.adjudicate_doc_refs,
                AdjudicateDocRefsInput(candidates=analysis.candidates),
                start_to_close_timeout=MODEL_ACTIVITY_TIMEOUT,
                heartbeat_timeout=HEARTBEAT_TIMEOUT,
                retry_policy=TOOL_RETRY,
            )
        findings = synthesize_doc_ref_findings(analysis.candidates, verdicts)
        comment_url = await workflow.execute_activity(
            activities.post_doc_refs_review,
            PostDocRefsInput(
                target=params.target, pr=params.pr, findings=findings
            ),
            start_to_close_timeout=CI_CHECK_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        return PrDocRefsResult(
            pr_number=params.pr.number,
            head_sha=params.pr.head_sha,
            candidates=len(analysis.candidates),
            findings=findings,
            comment_url=comment_url,
        )
