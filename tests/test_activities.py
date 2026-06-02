from __future__ import annotations

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

import froot.adapters.changelog_http as changelog_mod
import froot.adapters.github as github_mod
import froot.adapters.model_judge as model_mod
import froot.adapters.npm as npm_mod
import froot.workflow.temporal_client as temporal_client
from froot.domain.candidate import AvailableUpgrade
from froot.domain.changelog import Changelog, CleanVerdict, UnknownVerdict
from froot.domain.ci import CIPassed
from froot.domain.ecosystem import Ecosystem
from froot.domain.outcome import LoopOutcome
from froot.policy.naming import bump_workflow_id
from froot.workflow import activities
from froot.workflow.types import (
    CiCheckInput,
    DispatchInput,
    OpenPrInput,
    RecordInput,
)
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


async def test_scan_candidates_selects_patches(
    monkeypatch: pytest.MonkeyPatch,
):
    upgrades = (
        AvailableUpgrade(
            package="left-pad",
            ecosystem=Ecosystem.NPM,
            current=ver("1.4.2"),
            available=(ver("1.4.3"), ver("1.5.0")),
        ),
    )
    monkeypatch.setattr(github_mod, "GitHubForge", FakeForge)
    monkeypatch.setattr(
        npm_mod, "NpmPackageManager", lambda: FakePackageManager(upgrades)
    )
    result = await activities.scan_candidates(make_repo())
    assert [candidate.target for candidate in result] == [ver("1.4.3")]


async def test_judge_changelog_unknown_when_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        changelog_mod, "HttpChangelogSource", lambda: FakeChangelogSource(None)
    )
    verdict = await activities.judge_changelog(make_candidate())
    assert isinstance(verdict, UnknownVerdict)


async def test_judge_changelog_uses_model(monkeypatch: pytest.MonkeyPatch):
    changelog = Changelog(
        package="left-pad", version=ver("1.4.3"), text="fixes"
    )
    monkeypatch.setattr(
        changelog_mod,
        "HttpChangelogSource",
        lambda: FakeChangelogSource(changelog),
    )
    monkeypatch.setattr(
        model_mod,
        "PydanticAiJudge",
        lambda: FakeJudge(CleanVerdict(rationale="clean")),
    )
    verdict = await activities.judge_changelog(make_candidate())
    assert isinstance(verdict, CleanVerdict)


async def test_open_pull_request_idempotent_short_circuit(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(existing_pr=make_pr(number=42))
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    monkeypatch.setattr(npm_mod, "NpmPackageManager", FakePackageManager)
    params = OpenPrInput(
        target=make_repo(),
        candidate=make_candidate(),
        verdict=CleanVerdict(rationale="x"),
    )
    pr = await activities.open_pull_request(params)
    assert pr.number == 42
    assert fake.checked_out is False  # short-circuited: no checkout/apply/push


async def test_open_pull_request_full_path(monkeypatch: pytest.MonkeyPatch):
    fake = FakeForge(existing_pr=None, opened_pr=make_pr(number=7))
    package_manager = FakePackageManager()
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    monkeypatch.setattr(npm_mod, "NpmPackageManager", lambda: package_manager)
    params = OpenPrInput(
        target=make_repo(),
        candidate=make_candidate(),
        verdict=CleanVerdict(rationale="x"),
    )
    pr = await activities.open_pull_request(params)
    assert pr.number == 7
    assert fake.checked_out is True
    assert package_manager.applied == make_candidate()
    assert fake.pushed is not None


async def test_check_ci(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        github_mod, "GitHubForge", lambda: FakeForge(ci=CIPassed())
    )
    status = await activities.check_ci(
        CiCheckInput(target=make_repo(), head_sha="abc1234")
    )
    assert isinstance(status, CIPassed)


async def test_record_outcome_sets_labels(monkeypatch: pytest.MonkeyPatch):
    fake = FakeForge()
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    outcome = LoopOutcome(
        candidate=make_candidate(),
        verdict=CleanVerdict(rationale="x"),
        pr=make_pr(),
        ci=CIPassed(),
    )
    await activities.record_outcome(
        RecordInput(target=make_repo(), outcome=outcome)
    )
    assert fake.labeled is not None
    assert "ci:passed" in fake.labeled
    assert "changelog:clean" in fake.labeled


class _FakeClient:
    def __init__(self, *, already_started: bool = False) -> None:
        self.already_started = already_started
        self.started: list[dict[str, object]] = []

    async def start_workflow(
        self, run, arg, *, id, task_queue, id_reuse_policy
    ):
        if self.already_started:
            raise WorkflowAlreadyStartedError(
                workflow_id=id, workflow_type="BumpWorkflow"
            )
        self.started.append({"id": id, "policy": id_reuse_policy})


async def test_dispatch_bump_starts_with_reject_duplicate(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = _FakeClient()

    async def _client() -> _FakeClient:
        return fake

    monkeypatch.setattr(temporal_client, "client", _client)
    repo, candidate = make_repo(), make_candidate()
    await activities.dispatch_bump(
        DispatchInput(target=repo, candidate=candidate)
    )
    assert len(fake.started) == 1
    assert fake.started[0]["id"] == bump_workflow_id(repo, candidate)
    assert fake.started[0]["policy"] == WorkflowIDReusePolicy.REJECT_DUPLICATE


async def test_dispatch_bump_is_noop_when_already_started(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = _FakeClient(already_started=True)

    async def _client() -> _FakeClient:
        return fake

    monkeypatch.setattr(temporal_client, "client", _client)
    # Must not raise: re-dispatching an in-flight bump is a no-op (the
    # workflow-id + REJECT_DUPLICATE keep it to one PR per bump).
    await activities.dispatch_bump(
        DispatchInput(target=make_repo(), candidate=make_candidate())
    )
