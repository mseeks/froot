from __future__ import annotations

import json

import pytest
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

import froot.adapters.changelog_http as changelog_mod
import froot.adapters.github as github_mod
import froot.adapters.model_judge as model_mod
import froot.adapters.osv as osv_mod
import froot.adapters.registry as registry_mod
import froot.dashboard.github_source as github_source_mod
import froot.dashboard.read_model as read_model_mod
import froot.workflow.temporal_client as temporal_client
from froot.domain.candidate import AvailableUpgrade, Candidate
from froot.domain.changelog import (
    Changelog,
    CleanVerdict,
    RiskyVerdict,
    UnknownVerdict,
)
from froot.domain.ci import CIPassed
from froot.domain.ecosystem import Ecosystem
from froot.domain.loop import Loop
from froot.domain.outcome import LoopOutcome
from froot.domain.removal import Removal
from froot.policy.naming import bump_workflow_id
from froot.workflow import activities
from froot.workflow.types import (
    AutoMergeInput,
    BumpParams,
    CiCheckInput,
    CloseInput,
    DispatchInput,
    GateReviewInput,
    GateSelfTestInput,
    JudgeInput,
    MergeInput,
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
    make_removal,
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
    # The patch loop yields bumps; narrow to read the version it targets.
    assert [c.target for c in result if isinstance(c, Candidate)] == [
        ver("1.4.3")
    ]


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
    assert [c.target for c in result if isinstance(c, Candidate)] == [
        ver("1.4.3")
    ]
    assert result[0].justification is not None
    assert "GHSA-1" in result[0].justification


async def test_scan_candidates_dead_code_keeps_judge_approved_removals(
    monkeypatch: pytest.MonkeyPatch,
):
    # The dead-code arm: knip flags unused deps, the safe-to-remove judge vetoes
    # each, survivors carry the judge's rationale into their justification.
    unused = (make_removal(package="left-pad"),)
    monkeypatch.setattr(github_mod, "GitHubForge", FakeForge)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(unused=unused),
    )
    monkeypatch.setattr(
        model_mod,
        "PydanticAiJudge",
        lambda: FakeJudge(removal_verdict=CleanVerdict(rationale="not used")),
    )
    result = await activities.scan_candidates(
        ScanCandidatesInput(target=make_repo(), loop=Loop.DEAD_CODE)
    )
    assert [r.package for r in result if isinstance(r, Removal)] == ["left-pad"]
    assert result[0].justification == "unused (knip); not used"


async def test_scan_candidates_dead_code_vetoes_unsafe_removals(
    monkeypatch: pytest.MonkeyPatch,
):
    # A tool used without an import (pytest) is flagged unused but the judge
    # holds it (risky) — the veto at the signal drops it before any PR.
    unused = (make_removal(package="pytest", dev=True),)
    monkeypatch.setattr(github_mod, "GitHubForge", FakeForge)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(unused=unused),
    )
    monkeypatch.setattr(
        model_mod,
        "PydanticAiJudge",
        lambda: FakeJudge(
            removal_verdict=RiskyVerdict(
                rationale="test runner", concerns=("used via CLI",)
            )
        ),
    )
    result = await activities.scan_candidates(
        ScanCandidatesInput(target=make_repo(), loop=Loop.DEAD_CODE)
    )
    assert result == ()


async def test_reconcile_skips_dead_code(monkeypatch: pytest.MonkeyPatch):
    # Reconcile is version-supersession cleanup; a removal has no version, so
    # dead-code reconcile must return 0 *without* re-running its signal (which
    # would cost a checkout + the veto judge every tick).
    def boom(ecosystem: object) -> object:
        raise AssertionError("dead-code reconcile must not re-scan")

    monkeypatch.setattr(github_mod, "GitHubForge", FakeForge)
    monkeypatch.setattr(registry_mod, "package_manager_for", boom)
    closed = await activities.reconcile_open_prs(
        ReconcileInput(target=make_repo(), loop=Loop.DEAD_CODE)
    )
    assert closed == 0


async def test_scan_candidates_logs_considered_and_selected(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # Two upgrades available, but only one yields a patch candidate (the other
    # is a major bump) — so the tick considered 2 and selected 1, dropped 1.
    upgrades = (
        AvailableUpgrade(
            package="left-pad",
            ecosystem=Ecosystem.NPM,
            current=ver("1.4.2"),
            available=(ver("1.4.3"),),  # a patch -> kept
        ),
        AvailableUpgrade(
            package="lodash",
            ecosystem=Ecosystem.NPM,
            current=ver("4.0.0"),
            available=(ver("5.0.0"),),  # only a major -> dropped
        ),
    )
    monkeypatch.setattr(github_mod, "GitHubForge", FakeForge)
    monkeypatch.setattr(
        registry_mod,
        "package_manager_for",
        lambda ecosystem: FakePackageManager(upgrades),
    )
    with caplog.at_level("INFO", logger="froot.scan"):
        result = await activities.scan_candidates(
            ScanCandidatesInput(target=make_repo())
        )
    assert len(result) == 1  # only left-pad's patch
    ticks = [r for r in caplog.records if r.name == "froot.scan"]
    assert len(ticks) == 1
    record = json.loads(ticks[0].getMessage())
    assert record["event"] == "scan_tick"
    assert record["loop"] == "dependency-patch"
    assert record["considered"] == 2
    assert record["selected"] == 1
    assert record["dropped"] == 1


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


async def test_judge_changelog_for_removal_is_clean_from_justification():
    # A removal already cleared the safe-to-remove veto at scan; the in-workflow
    # judge step carries that conclusion into the PR framing without fetching a
    # changelog (there is none) or calling the model.
    verdict = await activities.judge_changelog(
        JudgeInput(
            candidate=make_removal(
                package="left-pad", justification="unused (knip); not imported"
            )
        )
    )
    assert isinstance(verdict, CleanVerdict)
    assert verdict.rationale == "unused (knip); not imported"


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


async def test_open_pull_request_removal_runs_remove_dependency(
    monkeypatch: pytest.MonkeyPatch,
):
    # The one place the action differs by kind: a removal calls
    # remove_dependency (not apply_patch_bump) and uses the removal PR draft.
    fake = FakeForge(existing_pr=None, opened_pr=make_pr(number=8))
    package_manager = FakePackageManager()
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    monkeypatch.setattr(
        registry_mod, "package_manager_for", lambda ecosystem: package_manager
    )
    removal = make_removal(package="left-pad")
    params = OpenPrInput(
        target=make_repo(),
        candidate=removal,
        verdict=CleanVerdict(rationale="safe to remove"),
    )
    pr = await activities.open_pull_request(params)
    assert pr.number == 8
    assert package_manager.applied is None  # no bump
    assert package_manager.removed == [removal]  # the removal action ran
    assert fake.pushed is not None


async def test_gate_review_for_removal_uses_safe_to_remove_judge(
    monkeypatch: pytest.MonkeyPatch,
):
    # The fourth leg for a removal re-runs the safe-to-remove judge (no
    # changelog); a clean verdict approves the auto-merge.
    judge = FakeJudge(removal_verdict=CleanVerdict(rationale="safe"))
    monkeypatch.setattr(model_mod, "PydanticAiJudge", lambda: judge)
    removal = make_removal(package="left-pad")
    # gate_review dispatches on the candidate kind, so the loop is irrelevant
    # here (the dead-code loop lands in a later slice).
    verdict = await activities.gate_review(
        GateReviewInput(candidate=removal, pr=make_pr())
    )
    assert isinstance(verdict, CleanVerdict)
    assert judge.removals == [removal]


async def test_record_outcome_removal_logs_remove_action(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    fake = FakeForge()
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    outcome = LoopOutcome(
        candidate=make_removal(package="left-pad", dev=True),
        verdict=CleanVerdict(rationale="safe to remove"),
        pr=make_pr(),
        ci=CIPassed(),
    )
    with caplog.at_level("INFO", logger="froot.outcome"):
        await activities.record_outcome(
            RecordInput(target=make_repo(), outcome=outcome)
        )
    records = [r for r in caplog.records if r.name == "froot.outcome"]
    assert len(records) == 1
    logged = json.loads(records[0].getMessage())
    assert logged["action"] == "remove"
    assert logged["package"] == "left-pad"
    assert logged["dev"] is True
    assert "from" not in logged  # no version fields for a removal


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
    labeled = set(fake.labeled)
    # The loop labels (no changelog/CI labels, regardless of outcome) plus the
    # environment stamp the gate uses to scope trust to the current judge model.
    assert {"froot", "dependency-patch"} <= labeled
    assert any(name.startswith("froot-env:") for name in labeled)


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


async def test_merge_pull_request_merges_via_forge(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge()
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    pr = make_pr(number=7)
    await activities.merge_pull_request(
        MergeInput(target=make_repo(), pr=pr, loop=Loop.DEPENDENCY_PATCH)
    )
    # Auto-merged through the forge (the head SHA is pinned for concurrency).
    assert fake.merged == [7]


async def test_auto_merge_eligible_false_when_not_allowlisted(
    monkeypatch: pytest.MonkeyPatch,
):
    # The default: empty allowlist -> hold, and not even a network read.
    monkeypatch.delenv("FROOT_AUTOMERGE_ALLOWLIST", raising=False)

    async def _boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("fetch must not run when the repo is not allowed")

    monkeypatch.setattr(github_source_mod, "fetch", _boom)
    eligible = await activities.auto_merge_eligible(
        AutoMergeInput(target=make_repo(), loop=Loop.DEPENDENCY_PATCH)
    )
    assert eligible is False


async def test_auto_merge_eligible_true_when_class_earned(
    monkeypatch: pytest.MonkeyPatch,
):
    # Allowlisted + the triangulated read says earned -> the grant is live.
    monkeypatch.setenv("FROOT_AUTOMERGE_ALLOWLIST", "acme/widgets")

    async def _fetch(repos: tuple[str, ...]) -> tuple[tuple[object, ...], None]:
        return (), None

    async def _fetch_outcomes(
        repos: object, prs: object, **kwargs: object
    ) -> tuple[dict[object, object], None]:
        return {}, None

    monkeypatch.setattr(github_source_mod, "fetch", _fetch)
    monkeypatch.setattr(github_source_mod, "fetch_outcomes", _fetch_outcomes)
    monkeypatch.setattr(read_model_mod, "earned_now", lambda *a, **k: True)
    eligible = await activities.auto_merge_eligible(
        AutoMergeInput(target=make_repo(), loop=Loop.DEPENDENCY_PATCH)
    )
    assert eligible is True


async def test_auto_merge_eligible_false_on_github_error(
    monkeypatch: pytest.MonkeyPatch,
):
    # Allowlisted but the record can't be read -> hold, never merge blind.
    monkeypatch.setenv("FROOT_AUTOMERGE_ALLOWLIST", "acme/widgets")

    async def _fetch(repos: tuple[str, ...]) -> tuple[tuple[object, ...], str]:
        return (), "rate limited"

    monkeypatch.setattr(github_source_mod, "fetch", _fetch)
    eligible = await activities.auto_merge_eligible(
        AutoMergeInput(target=make_repo(), loop=Loop.DEPENDENCY_PATCH)
    )
    assert eligible is False


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


async def test_gate_selftest_healthy_under_default_policy(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # The default live policy refuses every known-bad class -> nothing escapes,
    # and the heartbeat logs healthy=True at INFO.
    for var in (
        "FROOT_AUTOMERGE_MIN_RATE",
        "FROOT_AUTOMERGE_MIN_DECIDED",
        "FROOT_AUTOMERGE_MAX_DEFECT_RATE",
    ):
        monkeypatch.delenv(var, raising=False)
    with caplog.at_level("INFO", logger="froot.gate"):
        escaped = await activities.gate_selftest(
            GateSelfTestInput(target=make_repo())
        )
    assert escaped == ()
    record = json.loads(caplog.records[-1].getMessage())
    assert record["event"] == "gate_selftest"
    assert record["healthy"] is True
    assert record["escaped"] == []


async def test_gate_selftest_alarms_when_config_loosens_the_gate(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    # Drift: a steward raises the defect ceiling in config. The probe runs
    # against the *live* policy, so a known-bad class now escapes and the alarm
    # is logged at ERROR.
    monkeypatch.setenv("FROOT_AUTOMERGE_MAX_DEFECT_RATE", "1.0")
    with caplog.at_level("ERROR", logger="froot.gate"):
        escaped = await activities.gate_selftest(
            GateSelfTestInput(target=make_repo())
        )
    assert "a defect on record" in escaped
    record = json.loads(caplog.records[-1].getMessage())
    assert record["healthy"] is False
    assert caplog.records[-1].levelname == "ERROR"


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


async def test_gate_review_approves_a_clean_re_read(
    monkeypatch: pytest.MonkeyPatch,
):
    changelog = Changelog(package="left-pad", version=ver("1.4.3"), text="fix")
    monkeypatch.setattr(
        changelog_mod,
        "HttpChangelogSource",
        lambda: FakeChangelogSource(changelog),
    )
    fake = FakeJudge(gate_verdict=CleanVerdict(rationale="re-read clean"))
    monkeypatch.setattr(model_mod, "PydanticAiJudge", lambda: fake)
    verdict = await activities.gate_review(
        GateReviewInput(candidate=make_candidate(), pr=make_pr(number=7))
    )
    assert isinstance(verdict, CleanVerdict)  # clean = approve the merge
    assert fake.gate_loops == [Loop.DEPENDENCY_PATCH]


async def test_gate_review_holds_when_no_changelog(
    monkeypatch: pytest.MonkeyPatch,
):
    # Fail-closed: nothing to review -> a non-clean verdict, so the bump never
    # merges unattended.
    monkeypatch.setattr(
        changelog_mod, "HttpChangelogSource", lambda: FakeChangelogSource(None)
    )
    verdict = await activities.gate_review(
        GateReviewInput(candidate=make_candidate(), pr=make_pr(number=7))
    )
    # UnknownVerdict is a hold — never "clean", so the bump never merges.
    assert isinstance(verdict, UnknownVerdict)


async def test_gate_review_holds_on_model_error(
    monkeypatch: pytest.MonkeyPatch,
):
    # Fail-closed the other way: a reviewer that errors holds, never approves.
    changelog = Changelog(package="left-pad", version=ver("1.4.3"), text="fix")
    monkeypatch.setattr(
        changelog_mod,
        "HttpChangelogSource",
        lambda: FakeChangelogSource(changelog),
    )

    class _BoomReviewer:
        async def gate_review(
            self, changelog: Changelog, loop: object = None
        ) -> object:
            raise RuntimeError("ollama unreachable")

    monkeypatch.setattr(model_mod, "PydanticAiJudge", lambda: _BoomReviewer())
    verdict = await activities.gate_review(
        GateReviewInput(candidate=make_candidate(), pr=make_pr(number=7))
    )
    # A reviewer that errors holds (unknown), never approves.
    assert isinstance(verdict, UnknownVerdict)


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
