"""Integration test for the per-PR a11y review pipeline (time-skipping).

Mocks the scan / adjudicate / post activities to verify the orchestration: the
model pass runs only when the scan found candidates, the pure synthesis turns
gap verdicts into findings, and the result carries them.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.a11y import (
    A11yAnalysis,
    A11yCandidate,
    A11yVerdict,
    PrA11yResult,
)
from froot.workflow.pr_a11y_review_workflow import PrA11yReviewWorkflow
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import (
    AdjudicateA11yInput,
    PostA11yInput,
    PrA11yReviewParams,
)
from tests.support import make_pr, make_repo

_TASK_QUEUE = "froot-test-pr-a11y"
_adjudicated: list[int] = []
_posted: list[int] = []


def _candidate() -> A11yCandidate:
    return A11yCandidate(
        file="components/W.vue",
        line=4,
        kind="image",
        dialect="vue",
        detail="<img>",
        snippet="<img :src='u' />",
        context="<img :src='u' />",
    )


@activity.defn(name="scan_pr_a11y")
async def _mock_scan(params: PrA11yReviewParams) -> A11yAnalysis:
    return A11yAnalysis(candidates=(_candidate(),), scanned_files=1)


@activity.defn(name="scan_pr_a11y")
async def _mock_scan_clean(params: PrA11yReviewParams) -> A11yAnalysis:
    return A11yAnalysis(candidates=(), scanned_files=2)


@activity.defn(name="adjudicate_a11y")
async def _mock_adjudicate(
    params: AdjudicateA11yInput,
) -> tuple[A11yVerdict, ...]:
    _adjudicated.append(len(params.candidates))
    return tuple(
        A11yVerdict(
            bucket="gap",
            rationale="screen reader reads the URL",
            citation="<img :src='u' />",
            action="add :alt",
        )
        for _ in params.candidates
    )


@activity.defn(name="post_a11y_review")
async def _mock_post(params: PostA11yInput) -> str | None:
    _posted.append(len(params.findings))
    return "https://example.test/comment" if params.findings else None


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def test_pipeline_surfaces_a_gap_finding():
    _adjudicated.clear()
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrA11yReviewWorkflow],
            activities=[_mock_scan, _mock_adjudicate, _mock_post],
        ):
            result: PrA11yResult = await client.execute_workflow(
                PrA11yReviewWorkflow.run,
                PrA11yReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=5, head_sha="abcdef1234567"),
                ),
                id="pr-a11y-test",
                task_queue=_TASK_QUEUE,
            )
    assert result.pr_number == 5
    assert _adjudicated == [1]  # the one candidate was adjudicated
    assert _posted == [1]  # one gap finding surfaced
    assert len(result.findings) == 1
    assert result.findings[0].bucket == "gap"
    assert result.comment_url == "https://example.test/comment"


async def test_pipeline_skips_model_when_scan_is_clean():
    _adjudicated.clear()
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrA11yReviewWorkflow],
            activities=[_mock_scan_clean, _mock_adjudicate, _mock_post],
        ):
            result: PrA11yResult = await client.execute_workflow(
                PrA11yReviewWorkflow.run,
                PrA11yReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=9, head_sha="0123456abcdef"),
                ),
                id="pr-a11y-clean-test",
                task_queue=_TASK_QUEUE,
            )
    assert _adjudicated == []  # no candidates => the model pass never ran
    assert _posted == [0]
    assert result.findings == ()
    assert result.comment_url is None
