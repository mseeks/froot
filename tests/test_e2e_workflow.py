"""End-to-end: the real bump loop closing through the real activities.

Unlike ``test_bump_workflow`` (which mocks the activities to exercise just the
spine), this wires the *real* activities — judge, open, check-ci, record, close
— and only swaps the adapters underneath them for in-memory fakes. So it proves
the whole chain closes: the durable workflow drives the pure state machine,
which drives the real effect interpreters, which drive the ports. Both terminal
shapes are covered — a green bump that records and stays open for the human, and
a red bump that the loop closes (and whose branch it deletes) before recording.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from temporalio.client import Client
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

import froot.adapters.changelog_http as changelog_mod
import froot.adapters.github as github_mod
import froot.adapters.model_judge as model_mod
import froot.adapters.registry as registry_mod
from froot.domain.candidate import Candidate
from froot.domain.changelog import Changelog, CleanVerdict
from froot.domain.ci import CIFailed, CIPassed, CIPending
from froot.domain.loop import Loop
from froot.domain.outcome import LoopOutcome
from froot.workflow import activities
from froot.workflow.bump_workflow import BumpWorkflow
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.types import BumpParams
from tests.support import (
    FakeChangelogSource,
    FakeForge,
    FakeJudge,
    FakePackageManager,
    make_candidate,
    make_pr,
    make_repo,
    ver,
)

_TASK_QUEUE = "froot-e2e"
# The real bump activities — only the adapters beneath them are faked.
_REAL_ACTIVITIES: list[Callable[..., Any]] = [
    activities.judge_changelog,
    activities.gate_review,
    activities.open_pull_request,
    activities.check_ci,
    activities.record_outcome,
    activities.close_pull_request,
    activities.auto_merge_eligible,
    activities.merge_pull_request,
]


def _wire_fakes(monkeypatch: pytest.MonkeyPatch, fake: FakeForge) -> None:
    """Point every adapter the bump activities reach at the shared fake."""
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(),
    )
    monkeypatch.setattr(
        changelog_mod,
        "HttpChangelogSource",
        lambda: FakeChangelogSource(
            Changelog(package="left-pad", version=ver("1.4.3"), text="fix")
        ),
    )
    monkeypatch.setattr(
        model_mod,
        "PydanticAiJudge",
        lambda: FakeJudge(CleanVerdict(rationale="clean")),
    )


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def _run(
    *,
    close_on_red: bool = True,
    loop: Loop = Loop.DEPENDENCY_PATCH,
    candidate: Candidate | None = None,
) -> LoopOutcome:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[BumpWorkflow],
            activities=_REAL_ACTIVITIES,
        ):
            return await client.execute_workflow(
                BumpWorkflow.run,
                BumpParams(
                    target=make_repo(),
                    candidate=candidate or make_candidate(),
                    close_on_red=close_on_red,
                    loop=loop,
                ),
                id="bump-e2e",
                task_queue=_TASK_QUEUE,
            )


async def test_green_bump_records_and_stays_open(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(opened_pr=make_pr(number=7), ci=CIPassed())
    _wire_fakes(monkeypatch, fake)
    outcome = await _run()
    assert outcome.pr.number == 7
    assert outcome.ci_passed
    # The PR is recorded (labeled) and left open for the human — never closed.
    labeled = set(fake.labeled or ())
    assert {"froot", "dependency-patch"} <= labeled
    assert any(name.startswith("froot-env:") for name in labeled)
    assert fake.closed == []


async def test_green_security_bump_records_with_security_labels(
    monkeypatch: pytest.MonkeyPatch,
):
    # The whole chassis is loop-agnostic: a security bump (a minor, here) runs
    # the same real activities to record; only the namespace differs.
    fake = FakeForge(
        opened_pr=make_pr(
            number=9, branch="froot/security-patch/left-pad-1.5.0"
        ),
        ci=CIPassed(),
    )
    _wire_fakes(monkeypatch, fake)
    # A security bump is often a minor — the generalized Candidate allows it.
    candidate = make_candidate(
        package="left-pad", current="1.4.2", target="1.5.0"
    )
    outcome = await _run(loop=Loop.SECURITY_PATCH, candidate=candidate)
    assert outcome.ci_passed
    labeled = set(fake.labeled or ())
    assert {"froot", "security-patch"} <= labeled
    assert any(name.startswith("froot-env:") for name in labeled)
    assert fake.closed == []


async def test_green_bump_waits_through_pending_then_records(
    monkeypatch: pytest.MonkeyPatch,
):
    # The real check_ci activity polls the fake through pending -> pending ->
    # passed; the workflow's durable wait (time-skipped here) carries it.
    fake = FakeForge(
        opened_pr=make_pr(number=7),
        ci_sequence=(CIPending(), CIPending(), CIPassed()),
    )
    _wire_fakes(monkeypatch, fake)
    outcome = await _run()
    assert outcome.ci_passed
    assert fake.closed == []


async def test_red_bump_closes_pr_and_records(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(opened_pr=make_pr(number=7), ci=CIFailed(failing=("ci",)))
    _wire_fakes(monkeypatch, fake)
    outcome = await _run()
    assert isinstance(outcome.ci, CIFailed)
    # Closed (with its branch deleted) AND recorded: the loop closed cleanly.
    assert fake.closed == [7]
    assert fake.deleted_branches == [make_pr(number=7).branch]
    labeled = set(fake.labeled or ())
    assert {"froot", "dependency-patch"} <= labeled
    assert any(name.startswith("froot-env:") for name in labeled)


async def test_red_bump_stays_open_when_close_on_red_off(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(opened_pr=make_pr(number=7), ci=CIFailed(failing=("ci",)))
    _wire_fakes(monkeypatch, fake)
    outcome = await _run(close_on_red=False)
    assert isinstance(outcome.ci, CIFailed)
    # Toggle off: recorded but left open, nothing closed.
    assert fake.closed == []
    labeled = set(fake.labeled or ())
    assert {"froot", "dependency-patch"} <= labeled
    assert any(name.startswith("froot-env:") for name in labeled)
