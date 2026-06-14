"""A single PR's doc-coherence review — the agentic semantic pass (advisory).

Two durable steps: run the read-only agent over the PR checkout to map semantic
drift (the heavy, nondeterministic work, confined to ONE activity), then post
one advisory comment. The workflow body runs only one pure call
(:func:`synthesize_doc_coherence_findings`), so it stays deterministic and
passes the determinism gate even though the agent it dispatches does not.
Idempotent per (PR, head SHA).
"""

from __future__ import annotations

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from froot.domain.doc_coherence import PrDocCoherenceResult
    from froot.policy.doc_coherence_comment import (
        synthesize_doc_coherence_findings,
    )
    from froot.workflow import activities
    from froot.workflow.constants import (
        CI_CHECK_TIMEOUT,
        HEARTBEAT_TIMEOUT,
        MODEL_ACTIVITY_TIMEOUT,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        PostDocCoherenceInput,
        PrDocCoherenceReviewParams,
    )


@workflow.defn
class PrDocCoherenceReviewWorkflow:
    """Review one PR for semantic doc drift via the agent (advisory)."""

    @workflow.run
    async def run(
        self, params: PrDocCoherenceReviewParams
    ) -> PrDocCoherenceResult:
        """Run the drift-mapping agent, then post the advisory comment."""
        agent_run = await workflow.execute_activity(
            activities.run_doc_coherence_agent,
            params,
            start_to_close_timeout=MODEL_ACTIVITY_TIMEOUT,
            heartbeat_timeout=HEARTBEAT_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        findings = synthesize_doc_coherence_findings(agent_run.items)
        comment_url = await workflow.execute_activity(
            activities.post_doc_coherence_review,
            PostDocCoherenceInput(
                target=params.target,
                pr=params.pr,
                findings=findings,
                completed=agent_run.status == "completed",
            ),
            start_to_close_timeout=CI_CHECK_TIMEOUT,
            retry_policy=TOOL_RETRY,
        )
        return PrDocCoherenceResult(
            pr_number=params.pr.number,
            head_sha=params.pr.head_sha,
            run_status=agent_run.status,
            findings=findings,
            comment_url=comment_url,
        )
