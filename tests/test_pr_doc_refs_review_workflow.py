"""Integration test for the per-PR doc-refs review pipeline (time-skipping).

Mocks the scan / adjudicate / post activities to verify the orchestration: the
model pass runs only when the scan found candidates, the pure synthesis turns
broken verdicts into findings, and the result carries them.
"""

from __future__ import annotations

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.doc_refs import (
    DocRefAnalysis,
    DocRefCandidate,
    DocRefVerdict,
    PrDocRefsResult,
)
from froot.workflow.pr_doc_refs_review_workflow import PrDocRefsReviewWorkflow
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import (
    AdjudicateDocRefsInput,
    PostDocRefsInput,
    PrDocRefsReviewParams,
)
from tests.support import make_pr, make_repo

_TASK_QUEUE = "froot-test-pr-doc-refs"
_adjudicated: list[int] = []
_posted: list[int] = []


def _candidate() -> DocRefCandidate:
    return DocRefCandidate(
        file="README.md",
        line=4,
        kind="broken-link",
        referent="docs/gone.md",
        snippet="See [gone](docs/gone.md).",
        broken_by_pr=True,
    )


@activity.defn(name="scan_pr_doc_refs")
async def _mock_scan(params: PrDocRefsReviewParams) -> DocRefAnalysis:
    return DocRefAnalysis(candidates=(_candidate(),), scanned_files=1)


@activity.defn(name="scan_pr_doc_refs")
async def _mock_scan_clean(params: PrDocRefsReviewParams) -> DocRefAnalysis:
    return DocRefAnalysis(candidates=(), scanned_files=2)


@activity.defn(name="adjudicate_doc_refs")
async def _mock_adjudicate(
    params: AdjudicateDocRefsInput,
) -> tuple[DocRefVerdict, ...]:
    _adjudicated.append(len(params.candidates))
    return tuple(
        DocRefVerdict(
            bucket="broken",
            rationale="the PR deleted the target",
            citation="docs/gone.md",
            action="drop the link",
        )
        for _ in params.candidates
    )


@activity.defn(name="post_doc_refs_review")
async def _mock_post(params: PostDocRefsInput) -> str | None:
    _posted.append(len(params.findings))
    return "https://example.test/comment" if params.findings else None


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def test_pipeline_surfaces_a_broken_finding():
    _adjudicated.clear()
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrDocRefsReviewWorkflow],
            activities=[_mock_scan, _mock_adjudicate, _mock_post],
        ):
            result: PrDocRefsResult = await client.execute_workflow(
                PrDocRefsReviewWorkflow.run,
                PrDocRefsReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=5, head_sha="abcdef1234567"),
                ),
                id="pr-doc-refs-test",
                task_queue=_TASK_QUEUE,
            )
    assert result.pr_number == 5
    assert _adjudicated == [1]  # the one candidate was adjudicated
    assert _posted == [1]  # one broken finding surfaced
    assert len(result.findings) == 1
    assert result.findings[0].bucket == "broken"
    assert result.comment_url == "https://example.test/comment"


async def test_pipeline_skips_model_when_scan_is_clean():
    _adjudicated.clear()
    _posted.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[PrDocRefsReviewWorkflow],
            activities=[_mock_scan_clean, _mock_adjudicate, _mock_post],
        ):
            result: PrDocRefsResult = await client.execute_workflow(
                PrDocRefsReviewWorkflow.run,
                PrDocRefsReviewParams(
                    target=make_repo(),
                    pr=make_pr(number=9, head_sha="0123456abcdef"),
                ),
                id="pr-doc-refs-clean-test",
                task_queue=_TASK_QUEUE,
            )
    assert _adjudicated == []  # no candidates => the model pass never ran
    assert _posted == [0]
    assert result.findings == ()
    assert result.comment_url is None
