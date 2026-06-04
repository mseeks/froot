"""Integration test for the determinism-review loop on a time-skipping server.

Mocks the list + dispatch activities to verify the fan-out: one dispatch per
open PR, and the tick's reported counts.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.pull_request import PullRequestRef
from froot.workflow.review_workflow import ReviewWorkflow
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import (
    DispatchReviewInput,
    ReviewScanParams,
    ReviewScanResult,
)
from tests.support import make_pr, make_repo

_TASK_QUEUE = "froot-test-review"
_dispatched: list[int] = []


@activity.defn(name="list_review_prs")
async def _mock_list(target: object) -> tuple[PullRequestRef, ...]:
    return (
        make_pr(number=1, head_sha="aaaaaaa"),
        make_pr(number=2, head_sha="bbbbbbb"),
    )


@activity.defn(name="dispatch_pr_review")
async def _mock_dispatch(params: DispatchReviewInput) -> None:
    _dispatched.append(params.pr.number)


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def test_review_dispatches_each_open_pr():
    _dispatched.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[ReviewWorkflow],
            activities=[_mock_list, _mock_dispatch],
        ):
            result: ReviewScanResult = await client.execute_workflow(
                ReviewWorkflow.run,
                ReviewScanParams(target=make_repo(), continuous=False),
                id="review-test",
                task_queue=_TASK_QUEUE,
            )
    assert result.reviewed == 2
    assert result.dispatched == 2
    assert sorted(_dispatched) == [1, 2]


async def test_review_loop_keeps_running_and_repolls():
    _dispatched.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[ReviewWorkflow],
            activities=[_mock_list, _mock_dispatch],
        ):
            handle = await client.start_workflow(
                ReviewWorkflow.run,
                ReviewScanParams(
                    target=make_repo(), interval_seconds=60, continuous=True
                ),
                id="review-continuous",
                task_queue=_TASK_QUEUE,
            )
            await env.sleep(90)
            description = await handle.describe()
            await handle.terminate()
    assert description.status == WorkflowExecutionStatus.RUNNING
    assert len(_dispatched) >= 2  # at least the first tick fanned out
