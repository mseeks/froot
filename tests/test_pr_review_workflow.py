"""Integration test for the per-PR review pipeline on a time-skipping server.

Mocks the analyze / adjudicate / post activities to verify the orchestration:
the frontier is adjudicated only when present, findings combine static hazards
with model-confirmed frontier, and the result carries them.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.determinism import (
    AnalysisResult,
    FrontierItem,
    FrontierVerdict,
    HazardPath,
    Impurity,
    PrReviewResult,
)
from froot.workflow.pr_review_workflow import PrReviewWorkflow
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import (
    AdjudicateInput,
    PostReviewInput,
    PrReviewParams,
)
from tests.support import make_pr, make_repo

_TASK_QUEUE = "froot-test-pr-review"
_adjudicated: list[int] = []
_posted: list[int] = []


def _impurity() -> Impurity:
    return Impurity(
        rule="random.random",
        hint="use workflow.random()",
        module="app.util",
        line=3,
    )


def _frontier() -> FrontierItem:
    return FrontierItem(
        kind="third_party_import",
        workflow="app.workflow:W",
        module="app.workflow",
        line=2,
        symbol="httpx",
        snippet="import httpx",
    )


@activity.defn(name="analyze_pr")
async def _mock_analyze(params: PrReviewParams) -> AnalysisResult:
    return AnalysisResult(
        lexical=(),
        hazards=(
            HazardPath(
                workflow="app.workflow:W",
                via=("roll",),
                impurity=_impurity(),
            ),
        ),
        frontier=(_frontier(),),
    )


@activity.defn(name="analyze_pr")
async def _mock_analyze_clean(params: PrReviewParams) -> AnalysisResult:
    return AnalysisResult(lexical=(), hazards=(), frontier=())


@activity.defn(name="adjudicate_frontier")
async def _mock_adjudicate(
    params: AdjudicateInput,
) -> tuple[FrontierVerdict, ...]:
    _adjudicated.append(len(params.frontier))
    return tuple(
        FrontierVerdict(reaches="yes", rationale="reached from run()")
        for _ in params.frontier
    )


@activity.defn(name="post_review")
async def _mock_post(params: PostReviewInput) -> str | None:
    _posted.append(len(params.findings))
    return "https://example.test/comment" if params.findings else None


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def test_pipeline_combines_static_and_model_findings():
    _adjudicated.clear()
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrReviewWorkflow],
            activities=[_mock_analyze, _mock_adjudicate, _mock_post],
        ):
            result: PrReviewResult = await client.execute_workflow(
                PrReviewWorkflow.run,
                PrReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=5, head_sha="abcdef1234567"),
                ),
                id="pr-review-test",
                task_queue=_TASK_QUEUE,
            )
    assert result.pr_number == 5
    assert _adjudicated == [1]  # the one frontier item was adjudicated
    # one static hazard + one model-confirmed frontier => two findings
    assert _posted == [2]
    assert len(result.findings) == 2
    assert result.comment_url == "https://example.test/comment"


async def test_pipeline_skips_adjudication_when_no_frontier():
    _adjudicated.clear()
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrReviewWorkflow],
            activities=[_mock_analyze_clean, _mock_adjudicate, _mock_post],
        ):
            result: PrReviewResult = await client.execute_workflow(
                PrReviewWorkflow.run,
                PrReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=9, head_sha="0123456abcdef"),
                ),
                id="pr-review-clean-test",
                task_queue=_TASK_QUEUE,
            )
    assert _adjudicated == []  # no frontier => the model pass never ran
    assert _posted == [0]
    assert result.findings == ()
    assert result.comment_url is None
