"""Integration test for the per-PR doc-coherence pipeline (time-skipping).

Mocks the agent + post activities to verify the orchestration: the agent's items
flow through the pure synthesis to the comment, and an ended-early run posts
with ``completed=False`` (a "couldn't verify"), never a false all-clear.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.doc_coherence import (
    DocCoherenceItem,
    DocCoherenceRun,
    PrDocCoherenceResult,
)
from froot.workflow.pr_doc_coherence_review_workflow import (
    PrDocCoherenceReviewWorkflow,
)
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import (
    PostDocCoherenceInput,
    PrDocCoherenceReviewParams,
)
from tests.support import make_pr, make_repo

_TASK_QUEUE = "froot-test-pr-doc-coh"
_posted: list[tuple[int, bool]] = []


@activity.defn(name="run_doc_coherence_agent")
async def _mock_agent(params: PrDocCoherenceReviewParams) -> DocCoherenceRun:
    return DocCoherenceRun(
        items=(
            DocCoherenceItem(
                bucket="drift",
                what="README claims foo() exists",
                why="renamed to bar()",
                citation="README.md:3",
            ),
        ),
        status="completed",
    )


@activity.defn(name="run_doc_coherence_agent")
async def _mock_agent_failed(
    params: PrDocCoherenceReviewParams,
) -> DocCoherenceRun:
    return DocCoherenceRun(items=(), status="ended-early: model down")


@activity.defn(name="post_doc_coherence_review")
async def _mock_post(params: PostDocCoherenceInput) -> str | None:
    _posted.append((len(params.findings), params.completed))
    if params.findings or not params.completed:
        return "https://example.test/comment"
    return None


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def test_pipeline_surfaces_a_drift_finding():
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrDocCoherenceReviewWorkflow],
            activities=[_mock_agent, _mock_post],
        ):
            result: PrDocCoherenceResult = await client.execute_workflow(
                PrDocCoherenceReviewWorkflow.run,
                PrDocCoherenceReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=5, head_sha="abcdef1234567"),
                ),
                id="pr-doc-coh-test",
                task_queue=_TASK_QUEUE,
            )
    assert result.run_status == "completed"
    assert len(result.findings) == 1
    assert result.findings[0].bucket == "drift"
    assert _posted == [(1, True)]


async def test_pipeline_marks_an_incomplete_run_not_all_clear():
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrDocCoherenceReviewWorkflow],
            activities=[_mock_agent_failed, _mock_post],
        ):
            result: PrDocCoherenceResult = await client.execute_workflow(
                PrDocCoherenceReviewWorkflow.run,
                PrDocCoherenceReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=9, head_sha="0123456abcdef"),
                ),
                id="pr-doc-coh-fail-test",
                task_queue=_TASK_QUEUE,
            )
    assert result.run_status.startswith("ended-early")
    assert result.findings == ()
    assert _posted == [(0, False)]  # posted, but flagged not-completed
