"""Integration test for the doc-coherence-review loop on a time-skipping server.

Mocks the list + dispatch activities to verify the fan-out (one dispatch per
open PR, the tick's reported counts) and the loop's durability across a failed
tick — the regression behind the prod a11y dead-loop alert, identical here.
"""

from __future__ import annotations

import pytest
from temporalio import activity
from temporalio.client import (
    Client,
    WorkflowExecutionStatus,
    WorkflowFailureError,
)
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.pull_request import PullRequestRef
from froot.workflow.doc_coherence_review_workflow import (
    DocCoherenceReviewWorkflow,
)
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import (
    DispatchDocCoherenceInput,
    DocCoherenceReviewScanParams,
    DocCoherenceReviewScanResult,
)
from tests.support import make_pr, make_repo

_TASK_QUEUE = "froot-test-doc-coherence-review"
_dispatched: list[int] = []


@activity.defn(name="list_review_prs")
async def _mock_list(target: object) -> tuple[PullRequestRef, ...]:
    return (
        make_pr(number=1, head_sha="aaaaaaa"),
        make_pr(number=2, head_sha="bbbbbbb"),
    )


@activity.defn(name="dispatch_pr_doc_coherence_review")
async def _mock_dispatch(params: DispatchDocCoherenceInput) -> None:
    _dispatched.append(params.pr.number)


@activity.defn(name="list_review_prs")
async def _mock_list_401(target: object) -> tuple[PullRequestRef, ...]:
    # The prod incident: a transient GitHub 401, raised non-retryable.
    raise ApplicationError("GitHub auth failed (401)", non_retryable=True)


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def test_doc_coherence_dispatches_each_open_pr():
    _dispatched.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[DocCoherenceReviewWorkflow],
            activities=[_mock_list, _mock_dispatch],
        ):
            result: DocCoherenceReviewScanResult = (
                await client.execute_workflow(
                    DocCoherenceReviewWorkflow.run,
                    DocCoherenceReviewScanParams(
                        target=make_repo(), continuous=False
                    ),
                    id="doc-coherence-review-test",
                    task_queue=_TASK_QUEUE,
                )
            )
    assert result.reviewed == 2
    assert result.dispatched == 2
    assert sorted(_dispatched) == [1, 2]


async def test_doc_coherence_loop_keeps_running_and_repolls():
    _dispatched.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[DocCoherenceReviewWorkflow],
            activities=[_mock_list, _mock_dispatch],
        ):
            handle = await client.start_workflow(
                DocCoherenceReviewWorkflow.run,
                DocCoherenceReviewScanParams(
                    target=make_repo(), interval_seconds=60, continuous=True
                ),
                id="doc-coherence-review-continuous",
                task_queue=_TASK_QUEUE,
            )
            await env.sleep(90)
            description = await handle.describe()
            await handle.terminate()
    assert description.status == WorkflowExecutionStatus.RUNNING
    assert len(_dispatched) >= 2  # at least the first tick fanned out


async def test_doc_coherence_loop_survives_a_failing_tick():
    """A non-retryable tick error must not kill the durable loop (regression).

    Before the fix the 401 propagated out of the loop body and terminated the
    continue-as-new loop, so reviews stopped until the watchdog revived it. The
    loop must instead log the failed tick and keep ticking.
    """
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[DocCoherenceReviewWorkflow],
            activities=[_mock_list_401, _mock_dispatch],
        ):
            handle = await client.start_workflow(
                DocCoherenceReviewWorkflow.run,
                DocCoherenceReviewScanParams(
                    target=make_repo(), interval_seconds=60, continuous=True
                ),
                id="doc-coherence-failing-tick",
                task_queue=_TASK_QUEUE,
            )
            await env.sleep(150)  # span more than one failed tick + reschedule
            description = await handle.describe()
            await handle.terminate()
    assert description.status == WorkflowExecutionStatus.RUNNING


async def test_doc_coherence_one_shot_still_fails_loudly():
    """A one-shot run keeps propagating a tick failure (no silent swallow)."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[DocCoherenceReviewWorkflow],
            activities=[_mock_list_401, _mock_dispatch],
        ):
            with pytest.raises(WorkflowFailureError):
                await client.execute_workflow(
                    DocCoherenceReviewWorkflow.run,
                    DocCoherenceReviewScanParams(
                        target=make_repo(), continuous=False
                    ),
                    id="doc-coherence-one-shot-fail",
                    task_queue=_TASK_QUEUE,
                )
