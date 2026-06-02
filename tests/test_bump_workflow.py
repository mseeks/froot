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

from froot.domain.candidate import PatchCandidate
from froot.domain.changelog import ChangelogVerdict, CleanVerdict
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
    BumpParams,
    CiCheckInput,
    OpenPrInput,
    RecordInput,
)
from tests.support import make_candidate, make_pr, make_repo

_TASK_QUEUE = "froot-test"
# A scripted CI reply sequence the mock pops through (then falls back to green).
_ci_replies: list[CIStatus] = []


@activity.defn(name="judge_changelog")
async def _mock_judge(candidate: PatchCandidate) -> ChangelogVerdict:
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


_MOCKS: list[Callable[..., Any]] = [
    _mock_judge,
    _mock_open_pr,
    _mock_check_ci,
    _mock_record,
]


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def _run_bump() -> LoopOutcome:
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
                BumpParams(target=make_repo(), candidate=make_candidate()),
                id="bump-test",
                task_queue=_TASK_QUEUE,
            )


async def test_happy_path_green():
    _ci_replies.clear()
    outcome = await _run_bump()
    assert outcome.pr.number == 7
    assert outcome.ci_passed
    assert isinstance(outcome.ci, CIPassed)


async def test_ci_failed_records_failure_and_does_not_merge():
    _ci_replies.clear()
    _ci_replies.append(CIFailed(failing=("build",)))
    outcome = await _run_bump()
    assert not outcome.ci_passed
    assert isinstance(outcome.ci, CIFailed)


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
