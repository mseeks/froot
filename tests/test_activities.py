from __future__ import annotations

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

import froot.adapters.changelog_http as changelog_mod
import froot.adapters.github as github_mod
import froot.adapters.model_judge as model_mod
import froot.adapters.osv as osv_mod
import froot.adapters.registry as registry_mod
import froot.workflow.temporal_client as temporal_client
from froot.domain.candidate import AvailableUpgrade
from froot.domain.changelog import Changelog, CleanVerdict, UnknownVerdict
from froot.domain.ci import CIPassed
from froot.domain.ecosystem import Ecosystem
from froot.domain.loop import Loop
from froot.domain.outcome import LoopOutcome
from froot.policy.naming import bump_workflow_id
from froot.workflow import activities
from froot.workflow.types import (
    BumpParams,
    CiCheckInput,
    CloseInput,
    DispatchInput,
    JudgeInput,
    OpenPrInput,
    ReconcileInput,
    RecordInput,
    ScanCandidatesInput,
)
from tests.support import (
    FakeAdvisorySource,
    FakeChangelogSource,
    FakeForge,
    FakeJudge,
    FakePackageManager,
    make_advisory,
    make_candidate,
    make_installed,
    make_pr,
    make_repo,
    make_upgrade,
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
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(upgrades),
    )
    result = await activities.scan_candidates(
        ScanCandidatesInput(target=make_repo())
    )
    assert [candidate.target for candidate in result] == [ver("1.4.3")]


async def test_scan_candidates_security_loop(
    monkeypatch: pytest.MonkeyPatch,
):
    # The security arm: installed set -> OSV advisories -> clearing targets.
    installed = (make_installed("left-pad", "1.4.2"),)
    advisories = (
        make_advisory("left-pad", "GHSA-1", ranges=(("0", "1.4.3"),)),
    )
    monkeypatch.setattr(github_mod, "GitHubForge", FakeForge)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(installed=installed),
    )
    monkeypatch.setattr(
        osv_mod, "OsvAdvisorySource", lambda: FakeAdvisorySource(advisories)
    )
    result = await activities.scan_candidates(
        ScanCandidatesInput(target=make_repo(), loop=Loop.SECURITY_PATCH)
    )
    assert [candidate.target for candidate in result] == [ver("1.4.3")]
    assert result[0].justification is not None
    assert "GHSA-1" in result[0].justification


async def test_scan_candidates_selects_package_manager_by_ecosystem(
    monkeypatch: pytest.MonkeyPatch,
):
    seen: dict[str, Ecosystem] = {}

    def factory(ecosystem: Ecosystem) -> FakePackageManager:
        seen["ecosystem"] = ecosystem
        return FakePackageManager(())

    monkeypatch.setattr(github_mod, "GitHubForge", FakeForge)
    monkeypatch.setattr(registry_mod, "package_manager_for", factory)
    await activities.scan_candidates(
        ScanCandidatesInput(target=make_repo(ecosystem=Ecosystem.UV))
    )
    assert seen["ecosystem"] is Ecosystem.UV


async def test_judge_changelog_unknown_when_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        changelog_mod, "HttpChangelogSource", lambda: FakeChangelogSource(None)
    )
    verdict = await activities.judge_changelog(
        JudgeInput(candidate=make_candidate())
    )
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
    verdict = await activities.judge_changelog(
        JudgeInput(candidate=make_candidate())
    )
    assert isinstance(verdict, CleanVerdict)


async def test_open_pull_request_idempotent_short_circuit(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(existing_pr=make_pr(number=42))
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(),
    )
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
    monkeypatch.setattr(
        registry_mod, "package_manager_for", lambda ecosystem: package_manager
    )
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
    # Exactly the fixed pair — no changelog/CI labels, regardless of outcome.
    assert set(fake.labeled) == {"froot", "dependency-patch"}


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
        self.started.append({"id": id, "policy": id_reuse_policy, "arg": arg})


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


async def test_dispatch_bump_pins_close_on_red(
    monkeypatch: pytest.MonkeyPatch,
):
    # The toggle is read at dispatch and pinned onto the bump's params, so the
    # workflow never reads config itself.
    monkeypatch.setenv("FROOT_CLOSE_ON_RED", "0")
    fake = _FakeClient()

    async def _client() -> _FakeClient:
        return fake

    monkeypatch.setattr(temporal_client, "client", _client)
    await activities.dispatch_bump(
        DispatchInput(target=make_repo(), candidate=make_candidate())
    )
    arg = fake.started[0]["arg"]
    assert isinstance(arg, BumpParams)
    assert arg.close_on_red is False


async def test_close_pull_request_comments_then_closes_and_deletes(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge()
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    pr = make_pr(number=7)
    await activities.close_pull_request(
        CloseInput(target=make_repo(), pr=pr, failing=("build",))
    )
    assert fake.closed == [7]
    assert fake.deleted_branches == [pr.branch]
    # The "why" is posted (idempotent comment path) and names the failing check.
    assert fake.comments and fake.comments[-1][0] == 7
    assert "build" in fake.comments[-1][1]


async def test_reconcile_open_prs_closes_superseded(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("FROOT_RECONCILE", "1")
    upgrades = (
        make_upgrade("left-pad", current="1.4.2", available=("1.4.3", "1.4.4")),
    )
    stale = make_pr(number=5, branch="froot/dependency-patch/left-pad-1.4.3")
    fake = FakeForge(open_prs=(stale,))
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(upgrades),
    )
    closed = await activities.reconcile_open_prs(
        ReconcileInput(target=make_repo())
    )
    assert closed == 1
    assert fake.closed == [5]
    assert fake.deleted_branches == [stale.branch]


async def test_reconcile_open_prs_noop_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("FROOT_RECONCILE", "0")
    fake = FakeForge(open_prs=(make_pr(),))
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    closed = await activities.reconcile_open_prs(
        ReconcileInput(target=make_repo())
    )
    assert closed == 0
    assert fake.closed == []


async def test_judge_changelog_degrades_to_unknown_on_model_error(
    monkeypatch: pytest.MonkeyPatch,
):
    changelog = Changelog(
        package="left-pad", version=ver("1.4.3"), text="fixes"
    )
    monkeypatch.setattr(
        changelog_mod,
        "HttpChangelogSource",
        lambda: FakeChangelogSource(changelog),
    )

    class _BoomJudge:
        async def judge(
            self, changelog: Changelog, loop: object = None
        ) -> object:
            raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(model_mod, "PydanticAiJudge", lambda: _BoomJudge())
    # The model is non-load-bearing: its failure degrades to unknown, never
    # failing the activity (which would stall the spine on a flaky model).
    verdict = await activities.judge_changelog(
        JudgeInput(candidate=make_candidate())
    )
    assert isinstance(verdict, UnknownVerdict)
    assert "unavailable" in verdict.rationale.lower()


async def test_judge_changelog_passes_loop_to_model(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeJudge(CleanVerdict(rationale="ok"))
    changelog = Changelog(package="x", version=ver("1.4.3"), text="notes")
    monkeypatch.setattr(
        changelog_mod,
        "HttpChangelogSource",
        lambda: FakeChangelogSource(changelog),
    )
    monkeypatch.setattr(model_mod, "PydanticAiJudge", lambda: fake)
    await activities.judge_changelog(
        JudgeInput(candidate=make_candidate(), loop=Loop.SECURITY_PATCH)
    )
    assert fake.loops == [Loop.SECURITY_PATCH]


async def test_open_pull_request_security_loop_namespaces_branch(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(
        existing_pr=None,
        opened_pr=make_pr(
            number=8, branch="froot/security-patch/left-pad-1.5.0"
        ),
    )
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(),
    )
    # A security bump is often a minor — the generalized Candidate allows it.
    candidate = make_candidate(
        package="left-pad", current="1.4.2", target="1.5.0"
    )
    await activities.open_pull_request(
        OpenPrInput(
            target=make_repo(),
            candidate=candidate,
            verdict=CleanVerdict(rationale="x"),
            loop=Loop.SECURITY_PATCH,
        )
    )
    assert fake.pushed is not None
    assert fake.pushed.value.startswith("froot/security-patch/")
