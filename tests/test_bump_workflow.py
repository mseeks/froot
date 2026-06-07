"""Integration tests for the bump workflow on a time-skipping test server.

The activities are mocked (by matching activity name), so this exercises the
real spine: the driver loop, the effect interpretation, and the durable CI wait
(whose ``workflow.sleep`` the time-skipping server fast-forwards).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.changelog import ChangelogVerdict, CleanVerdict, RiskyVerdict
from froot.domain.ci import (
    CIFailed,
    CIPassed,
    CIPending,
    CIStatus,
    CITimedOut,
)
from froot.domain.outcome import LoopOutcome
from froot.domain.pull_request import PullRequestRef
from froot.workflow.bump_workflow import BumpWorkflow
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import (
    AutoMergeInput,
    BumpParams,
    CiCheckInput,
    CloseInput,
    GateReviewInput,
    JudgeInput,
    MergeInput,
    OpenPrInput,
    RecordInput,
)
from tests.support import make_candidate, make_pr, make_repo

_TASK_QUEUE = "froot-test"
# A scripted CI reply sequence the mock pops through (then falls back to green).
_ci_replies: list[CIStatus] = []
# PR numbers the close-on-red path closed, in order.
_closed: list[int] = []
# PR numbers the acting gate auto-merged, in order, and the eligibility the
# mock gate reports (a test flips it to exercise the auto-merge path).
_merged: list[int] = []
_eligible: bool = False
# The verdict the mock gate reviewer returns (clean = approve the merge; a test
# flips it to a hold to exercise the deep-review veto).
_gate_verdict: ChangelogVerdict = CleanVerdict(rationale="re-read clean")


@activity.defn(name="judge_changelog")
async def _mock_judge(params: JudgeInput) -> ChangelogVerdict:
    return CleanVerdict(rationale="patch only")


@activity.defn(name="open_pull_request")
async def _mock_open_pr(params: OpenPrInput) -> PullRequestRef:
    return make_pr(number=7)


@activity.defn(name="check_ci")
async def _mock_check_ci(params: CiCheckInput) -> CIStatus:
    return _ci_replies.pop(0) if _ci_replies else CIPassed()


@activity.defn(name="record_outcome")
async def _mock_record(params: RecordInput) -> None:
    return None


@activity.defn(name="close_pull_request")
async def _mock_close(params: CloseInput) -> None:
    _closed.append(params.pr.number)


@activity.defn(name="auto_merge_eligible")
async def _mock_eligible(params: AutoMergeInput) -> bool:
    return _eligible


@activity.defn(name="gate_review")
async def _mock_gate_review(params: GateReviewInput) -> ChangelogVerdict:
    return _gate_verdict


@activity.defn(name="merge_pull_request")
async def _mock_merge(params: MergeInput) -> None:
    _merged.append(params.pr.number)


_MOCKS: list[Callable[..., Any]] = [
    _mock_judge,
    _mock_open_pr,
    _mock_check_ci,
    _mock_record,
    _mock_close,
    _mock_eligible,
    _mock_gate_review,
    _mock_merge,
]


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def _run_bump(*, close_on_red: bool = True) -> LoopOutcome:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[BumpWorkflow],
            activities=_MOCKS,
        ):
            return await client.execute_workflow(
                BumpWorkflow.run,
                BumpParams(
                    target=make_repo(),
                    candidate=make_candidate(),
                    close_on_red=close_on_red,
                ),
                id="bump-test",
                task_queue=_TASK_QUEUE,
            )


async def test_happy_path_green():
    _ci_replies.clear()
    _closed.clear()
    outcome = await _run_bump()
    assert outcome.pr.number == 7
    assert outcome.ci_passed
    assert isinstance(outcome.ci, CIPassed)
    assert _closed == []  # green PRs are left for the human, never closed


async def test_ci_failed_closes_pr_and_records_failure():
    _ci_replies.clear()
    _closed.clear()
    _ci_replies.append(CIFailed(failing=("build",)))
    outcome = await _run_bump()
    assert not outcome.ci_passed
    assert isinstance(outcome.ci, CIFailed)
    # Close-on-red (the default): the red PR is closed, and the outcome is
    # still recorded (the loop reached its terminal state).
    assert _closed == [7]


async def test_ci_failed_left_open_when_close_on_red_off():
    _ci_replies.clear()
    _closed.clear()
    _ci_replies.append(CIFailed(failing=("build",)))
    outcome = await _run_bump(close_on_red=False)
    assert isinstance(outcome.ci, CIFailed)
    # close-on-red off: the red PR is recorded but left open for the human.
    assert _closed == []


async def test_ci_pending_then_pass_waits_durably():
    _ci_replies.clear()
    _ci_replies.extend([CIPending(), CIPending(), CIPassed()])
    outcome = await _run_bump()
    assert outcome.ci_passed


async def test_ci_timeout_when_never_resolves():
    _ci_replies.clear()
    _ci_replies.extend([CIPending()] * 100)
    outcome = await _run_bump()
    assert isinstance(outcome.ci, CITimedOut)


async def test_green_clean_auto_merges_when_eligible_and_review_approves():
    # The acting gate, full path: a clean+green bump on an earned class is
    # deep-reviewed and, on approval, auto-merged by the loop.
    global _eligible
    _ci_replies.clear()
    _closed.clear()
    _merged.clear()
    _eligible = True
    try:
        outcome = await _run_bump()
    finally:
        _eligible = False
    assert outcome.ci_passed
    assert _merged == [7]  # the loop merged it
    assert _closed == []


async def test_eligible_but_gate_review_holds_does_not_merge():
    # The deep-review veto: the class is earned and CI is green, but the
    # independent gate reviewer holds -> the loop records and leaves it open.
    global _eligible, _gate_verdict
    _ci_replies.clear()
    _merged.clear()
    _closed.clear()
    _eligible = True
    _gate_verdict = RiskyVerdict(rationale="a hidden behavior change")
    try:
        outcome = await _run_bump()
    finally:
        _eligible = False
        _gate_verdict = CleanVerdict(rationale="re-read clean")
    assert outcome.ci_passed
    assert _merged == []  # the review vetoed the merge
    assert _closed == []  # green: left open for the human, not closed


async def test_green_clean_not_merged_when_class_not_eligible():
    # The default: no grant -> propose-only, the loop never merges (and never
    # even reaches the deep review).
    _ci_replies.clear()
    _merged.clear()
    outcome = await _run_bump()
    assert outcome.ci_passed
    assert _merged == []
