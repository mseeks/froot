"""Activities: the effect interpreters that wrap the adapters.

Each activity is the impure boundary for one effect. Adapter imports are LAZY
(inside the bodies) so the model and HTTP stacks never enter a workflow sandbox;
the pure policy and domain imports stay at module level. Activities return
domain values — the workflow wraps them into events and feeds the pure state
machine. The activity signatures' types are evaluated at runtime by Temporal's
data converter, so the domain imports here are deliberately not deferred.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from temporalio import activity

from froot.domain.a11y import A11yAnalysis, A11yVerdict
from froot.domain.candidate import Candidate
from froot.domain.changelog import (
    ChangelogVerdict,
    CleanVerdict,
    UnknownVerdict,
)
from froot.domain.ci import CIStatus
from froot.domain.dead_source import DeadExport, DeadFile
from froot.domain.determinism import AnalysisResult, FrontierVerdict
from froot.domain.pull_request import PullRequestDraft, PullRequestRef
from froot.domain.removal import Removal
from froot.domain.repo import TargetRepo
from froot.domain.work import WorkItem
from froot.policy.a11y_comment import (
    A11Y_MARKER,
    render_a11y_comment,
    should_post,
)
from froot.policy.a11y_scan import scan_sources
from froot.policy.compose import (
    dead_export_pull_request_draft,
    dead_file_pull_request_draft,
    pr_labels,
    pull_request_draft,
    removal_pull_request_draft,
)
from froot.policy.dead_source import unexport_line
from froot.policy.determinism import analyze_workflow_surface
from froot.policy.naming import (
    branch_name,
    bump_workflow_id,
    pr_a11y_review_workflow_id,
    pr_review_workflow_id,
)
from froot.policy.review_comment import (
    REVIEW_MARKER,
    render_review_comment,
)
from froot.policy.review_comment import (
    should_post as should_post_review,
)
from froot.workflow.types import (
    AdjudicateA11yInput,
    AdjudicateInput,
    AutoMergeInput,
    CiCheckInput,
    CloseInput,
    DispatchA11yInput,
    DispatchInput,
    DispatchReviewInput,
    GateReviewInput,
    GateSelfTestInput,
    JudgeInput,
    MergeInput,
    OpenPrInput,
    PostA11yInput,
    PostReviewInput,
    PrA11yReviewParams,
    PrReviewParams,
    ReconcileInput,
    RecordInput,
    ScanCandidatesInput,
)

if TYPE_CHECKING:
    from froot.domain.loop import Loop
    from froot.ports.protocols import PackageManager

_log = logging.getLogger("froot.outcome")
_review_log = logging.getLogger("froot.review")
_a11y_log = logging.getLogger("froot.a11y")
_reconcile_log = logging.getLogger("froot.reconcile")
_scan_log = logging.getLogger("froot.scan")
_gate_log = logging.getLogger("froot.gate")


def _manifest_dir(target: TargetRepo, workspace: Path) -> Path:
    """The directory the manifest lives in (a monorepo subdir, or the root)."""
    return workspace / target.manifest_dir if target.manifest_dir else workspace


def _draft_for(params: OpenPrInput) -> PullRequestDraft:
    """Build the PR draft for the work item — bump vs removal compose.

    The PR-title verb is the loop's, resolved from its registered spec here (the
    impure boundary) and passed into the pure draft builders.
    """
    from froot.loops import registry

    item = params.candidate
    title_prefix = registry.commit_tail(params.loop).title_prefix
    match item:
        case Candidate():
            return pull_request_draft(
                params.target,
                item,
                params.verdict,
                params.loop,
                title_prefix=title_prefix,
            )
        case Removal():
            return removal_pull_request_draft(
                params.target, item, params.loop, title_prefix=title_prefix
            )
        case DeadFile():
            return dead_file_pull_request_draft(
                params.target, item, params.loop, title_prefix=title_prefix
            )
        case DeadExport():
            return dead_export_pull_request_draft(
                params.target, item, params.loop, title_prefix=title_prefix
            )
    assert_never(item)


def _delete_dead_file(base: Path, item: DeadFile) -> None:
    """Delete the unused file from the checkout (``push_branch`` stages it).

    Resolved against ``base`` — the manifest dir the analyzer ran in, so the
    path matches what the signal flagged. A missing file raises (the same
    fail-loud as the bump action), never a silent no-op PR.
    """
    (base / item.path).unlink()


def _apply_dead_export(base: Path, item: DeadExport) -> None:
    """Strip the unused ``export`` from the file at the analyzer's line.

    Re-validates the line still declares ``symbol`` via the same pure transform
    the signal narrowed with (:func:`~froot.policy.dead_source.unexport_line`);
    a mismatch — the source drifted under the signal — raises rather than push
    an empty diff, so the loop never opens a no-op PR.
    """
    path = base / item.file
    lines = path.read_text().split("\n")
    index = item.line - 1
    if not 0 <= index < len(lines):
        msg = f"{item.file}:{item.line} out of range for {item.symbol!r}"
        raise RuntimeError(msg)
    rewritten = unexport_line(lines[index], item.symbol)
    if rewritten is None:
        msg = (
            f"{item.file}:{item.line} is no longer an un-exportable "
            f"declaration of {item.symbol!r}"
        )
        raise RuntimeError(msg)
    lines[index] = rewritten
    path.write_text("\n".join(lines))


async def _select_candidates(
    loop: Loop,
    target: TargetRepo,
    package_manager: PackageManager,
    manifest_dir: Path,
) -> tuple[int, tuple[WorkItem, ...]]:
    """Gather this loop's signal from the checkout and select its work items.

    The one genuinely per-loop seam: dependency-patch reads the available
    upgrades and picks the highest patch; security-patch reads the installed,
    asks OSV for advisories, and picks the lowest version clearing each;
    dead-code reads the unused dependencies a static analyzer flags and vetoes
    each with the safe-to-remove judge. The impure sources are lazy-imported per
    arm so none drags another's stack into a sandbox. Each feeds a pure (or, for
    dead-code, model-vetoed) selection.

    Returns ``(considered, items)`` — ``considered`` is the size of the upstream
    signal (available upgrades / advisories found / unused deps flagged) so the
    scan can make its selectivity legible (how much was seen versus kept).

    The one genuinely per-loop body now lives in each loop's spec ``observe``
    (see :mod:`froot.loops`); the spine looks the loop up and runs it, so this
    selection seam needs no per-loop arm.
    """
    from froot.loops import registry

    return await registry.commit_tail(loop).observe(
        target, package_manager, manifest_dir
    )


@activity.defn
async def scan_candidates(
    params: ScanCandidatesInput,
) -> tuple[WorkItem, ...]:
    """Check out the repo and select this loop's candidates.

    Emits the tick's selectivity — how much upstream signal was considered
    versus how much was kept — as span attributes (when ``FROOT_OTEL`` is on)
    and as a structured ``scan_tick`` log, so the signal stage is legible in the
    run ledger even on a tick that proposes nothing.
    """
    from froot.adapters.github import GitHubForge
    from froot.adapters.registry import package_manager_for
    from froot.adapters.telemetry import set_span_attributes

    forge = GitHubForge()
    package_manager = package_manager_for(params.target.ecosystem)
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        await forge.checkout(params.target, workspace)
        considered, candidates = await _select_candidates(
            params.loop,
            params.target,
            package_manager,
            _manifest_dir(params.target, workspace),
        )
    selected = len(candidates)
    dropped = max(considered - selected, 0)
    set_span_attributes(
        scan_loop=params.loop.value,
        scan_repo=params.target.repo.slug,
        scan_considered=considered,
        scan_selected=selected,
        scan_dropped=dropped,
    )
    _scan_log.info(
        json.dumps(
            {
                "event": "scan_tick",
                "loop": params.loop.value,
                "repo": params.target.repo.slug,
                "considered": considered,
                "selected": selected,
                "dropped": dropped,
            }
        )
    )
    return candidates


@activity.defn
async def judge_changelog(params: JudgeInput) -> ChangelogVerdict:
    """Fetch the candidate's changelog and get the model's typed verdict.

    The model is froot's one thin, non-load-bearing judgment: a clean verdict
    never *gates* a PR (CI is the oracle), so a model that is down, slow, or
    erroring must not stall the spine. A judge failure degrades to
    ``UnknownVerdict`` — the bump proceeds, the human still gets the PR, and the
    dashboard records the verdict as unknown — rather than failing (and then
    retrying) the activity. Only the model call is guarded; the fetch is already
    best-effort (returns ``None``, not an exception). The loop selects what the
    model is asked (clean-patch vs breaking-change-on-a-security-bump).
    """
    from froot.adapters.changelog_http import HttpChangelogSource
    from froot.adapters.model_judge import PydanticAiJudge

    candidate = params.candidate
    if isinstance(candidate, Removal | DeadFile | DeadExport):
        # A signal-judged kind (removal / dead file / dead export) already
        # cleared its safe-to-remove veto at scan; there is no changelog to
        # read, so carry that conclusion straight into the PR framing (the
        # rationale the veto recorded on the work item).
        return CleanVerdict(
            rationale=candidate.justification or "unused; safe to remove"
        )
    changelog = await HttpChangelogSource().fetch(candidate)
    if changelog is None:
        return UnknownVerdict(rationale="No changelog could be fetched.")
    try:
        return await PydanticAiJudge().judge(changelog, params.loop)
    except Exception as exc:
        activity.logger.warning(
            "changelog judge unavailable for %s; degrading to unknown: %r",
            params.candidate.subject,
            exc,
        )
        return UnknownVerdict(
            rationale=f"Changelog judge unavailable ({type(exc).__name__})."
        )


@activity.defn
async def gate_review(params: GateReviewInput) -> ChangelogVerdict:
    """Independently deep-review a bump at the gate; fail-closed to a hold.

    The fourth trust leg (§3.7): a second, adversarial model pass over the
    changelog, run only when a bump is about to auto-merge. ``clean`` approves
    the merge; ``risky``/``unknown`` hold the PR for the human. Fail-CLOSED — a
    missing changelog or a model error returns a non-clean verdict, so an
    unreviewable bump never merges unattended. This is the opposite disposition
    from :func:`judge_changelog` (which degrades-to-proceed): here the safe
    direction is to hold, and a non-clean verdict already means hold.
    """
    from froot.adapters.changelog_http import HttpChangelogSource
    from froot.adapters.model_judge import PydanticAiJudge

    candidate = params.candidate
    verdict: ChangelogVerdict
    if isinstance(candidate, Removal):
        # The fourth leg for a removal: independently re-judge that it is safe
        # to remove (the same check the scan veto ran). No changelog to read;
        # fail-CLOSED to a hold on a model error, like the bump path.
        try:
            verdict = await PydanticAiJudge().judge_removal(candidate)
        except Exception as exc:
            activity.logger.warning(
                "safe-to-remove gate review unavailable for %s; holding: %r",
                candidate.subject,
                exc,
            )
            verdict = UnknownVerdict(
                rationale=(
                    f"Removal reviewer unavailable ({type(exc).__name__})."
                )
            )
    elif isinstance(candidate, DeadFile | DeadExport):
        # The fourth leg for a dead file / unused export: independently re-judge
        # the delete / un-export is safe (the scan veto's check). No changelog
        # to read; fail-CLOSED to a hold on a model error, like the bump path.
        try:
            verdict = await PydanticAiJudge().judge_dead_source(candidate)
        except Exception as exc:
            activity.logger.warning(
                "dead-source gate review unavailable for %s; holding: %r",
                candidate.subject,
                exc,
            )
            verdict = UnknownVerdict(
                rationale=(
                    f"Dead-source reviewer unavailable ({type(exc).__name__})."
                )
            )
    else:
        changelog = await HttpChangelogSource().fetch(candidate)
        if changelog is None:
            verdict = UnknownVerdict(
                rationale="No changelog to review; holding (fail-closed)."
            )
        else:
            try:
                verdict = await PydanticAiJudge().gate_review(
                    changelog, params.loop
                )
            except Exception as exc:
                activity.logger.warning(
                    "gate reviewer unavailable for %s; holding: %r",
                    candidate.package,
                    exc,
                )
                verdict = UnknownVerdict(
                    rationale=(
                        f"Gate reviewer unavailable ({type(exc).__name__})."
                    )
                )
    _gate_log.info(
        json.dumps(
            {
                "event": "gate_review",
                "loop": params.loop.value,
                "pr": params.pr.number,
                "pr_url": params.pr.url,
                "package": params.candidate.subject,
                "verdict": verdict.kind,
                "approved": verdict.kind == "clean",
            }
        )
    )
    return verdict


@activity.defn
async def open_pull_request(params: OpenPrInput) -> PullRequestRef:
    """Apply the work item's edit and open (idempotently) its PR.

    The one place the action differs by work-item kind: a bump regenerates the
    lockfile at the target version; a removal deletes a dependency (both
    lockfile-only, no install or scripts); a dead file is deleted whole; a dead
    export is stripped of its ``export``. Everything else (the dedup branch, the
    checkout, the push, the open) is the same chassis, and CI is the oracle for
    every kind.
    """
    from froot.adapters.github import GitHubForge
    from froot.adapters.registry import package_manager_for

    forge = GitHubForge()
    package_manager = package_manager_for(params.target.ecosystem)
    branch = branch_name(params.candidate, params.loop)
    existing = await forge.find_open_pull_request(params.target, branch)
    if existing is not None:
        return existing
    draft = _draft_for(params)
    item = params.candidate
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        await forge.checkout(params.target, workspace)
        manifest_dir = _manifest_dir(params.target, workspace)
        match item:
            case Candidate():
                await package_manager.apply_patch_bump(item, manifest_dir)
            case Removal():
                await package_manager.remove_dependency(item, manifest_dir)
            case DeadFile():
                _delete_dead_file(manifest_dir, item)
            case DeadExport():
                # Prefer the AST codemod in the sandbox (deletes a truly-dead
                # symbol, un-exports one still used in-file); fall back to the
                # in-worker regex un-export when no sandbox is configured.
                from froot.adapters.codemod import apply_export_codemod

                if not await apply_export_codemod(manifest_dir, item):
                    _apply_dead_export(manifest_dir, item)
        await forge.push_branch(workspace, branch, draft.title)
    return await forge.open_pull_request(params.target, draft)


@activity.defn
async def check_ci(params: CiCheckInput) -> CIStatus:
    """Read the repo's CI status for the PR's head commit (the oracle)."""
    from froot.adapters.github import GitHubForge

    return await GitHubForge().ci_status(params.target, params.head_sha)


@activity.defn
async def record_outcome(params: RecordInput) -> None:
    """Label the PR and log the run telemetry — the signal-update.

    The labels carry the loop *and* the judgment environment (the judge model)
    the PR was opened under, so the gate can count only the track record earned
    under the current environment and reset it when the model changes (§3.7).
    """
    from froot.adapters.github import GitHubForge
    from froot.config.settings import ModelSettings
    from froot.policy.environment import env_label

    outcome = params.outcome
    item = outcome.candidate
    labels = (
        *pr_labels(params.loop),
        env_label(ModelSettings().ollama_model),
    )
    await GitHubForge().add_labels(params.target, outcome.pr.number, labels)
    record = {
        "event": "loop_outcome",
        "loop": params.loop.value,
        "repo": params.target.repo.slug,
        "package": item.subject,
        "changelog": outcome.verdict.kind,
        "ci": outcome.ci.kind,
        "ci_passed": outcome.ci_passed,
        "pr": outcome.pr.number,
        "pr_url": outcome.pr.url,
    }
    match item:
        case Candidate():
            record |= {
                "action": "bump",
                "from": str(item.current),
                "to": str(item.target),
            }
        case Removal():
            record |= {"action": "remove", "dev": item.dev}
        case DeadFile():
            record |= {"action": "remove_file", "path": item.path}
        case DeadExport():
            record |= {
                "action": "unexport",
                "file": item.file,
                "symbol": item.symbol,
            }
    _log.info(json.dumps(record))


@activity.defn
async def dispatch_bump(params: DispatchInput) -> None:
    """Start the bump loop for a candidate (idempotent per bump identity).

    Reads the close-on-red toggle here, at the impure boundary, and pins it onto
    the bump's params — so the running workflow never reads config itself and an
    in-flight bump keeps the value it was dispatched with.
    """
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.config.settings import BehaviorSettings
    from froot.workflow.bump_workflow import BumpWorkflow
    from froot.workflow.temporal_client import client, task_queue
    from froot.workflow.types import BumpParams

    temporal = await client()
    try:
        await temporal.start_workflow(
            BumpWorkflow.run,
            BumpParams(
                target=params.target,
                candidate=params.candidate,
                close_on_red=BehaviorSettings().close_on_red,
                loop=params.loop,
            ),
            id=bump_workflow_id(params.target, params.candidate, params.loop),
            task_queue=task_queue(),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        # This bump already has a loop (running or completed) — a no-op, so
        # re-scanning never opens a second PR for the same bump.
        return


@activity.defn
async def auto_merge_eligible(params: AutoMergeInput) -> bool:
    """Whether this (repo, loop) class has earned the auto-merge grant.

    Short-circuits to ``False`` for any repo a steward has not allowlisted (the
    default), so the common case costs nothing. Otherwise it re-derives the
    class's standing from the live GitHub history — the same triangulated,
    windowed, environment-scoped computation the dashboard's shadow gate shows
    (``read_model.earned_now``) — so the acting gate and the advisory panel can
    never disagree. Best-effort: any read failure degrades to ``False`` (hold),
    never an auto-merge.
    """
    from datetime import UTC, datetime

    from froot.config.settings import AutonomySettings, ModelSettings
    from froot.dashboard import github_source, read_model
    from froot.policy.environment import environment_slug

    policy = AutonomySettings().policy()
    repo = params.target.repo.slug
    if repo not in policy.allowlisted_repos:
        return False
    now = datetime.now(UTC)
    prs, prs_error = await github_source.fetch((repo,))
    if prs_error is not None:
        return False  # can't confirm the record -> hold, never merge blind
    outcomes, _ = await github_source.fetch_outcomes(
        (repo,), prs, now=now, window_days=policy.window_days
    )
    return read_model.earned_now(
        now,
        prs,
        outcomes,
        repo,
        params.loop,
        policy,
        environment_slug(ModelSettings().ollama_model),
    )


@activity.defn
async def merge_pull_request(params: MergeInput) -> None:
    """Auto-merge an earned, clean+green bump's PR (the acting gate's write).

    Reached only after the pure machine confirmed clean+green and the class
    earned the grant on an allowlisted repo. Passes the head SHA so GitHub
    refuses the merge if the head moved since the gate decided.
    """
    from froot.adapters.github import GitHubForge

    await GitHubForge().merge_pull_request(
        params.target, params.pr.number, head_sha=params.pr.head_sha
    )
    _log.info(
        json.dumps(
            {
                "event": "pr_merged",
                "loop": params.loop.value,
                "reason": "auto_merge",
                "repo": params.target.repo.slug,
                "pr": params.pr.number,
                "pr_url": params.pr.url,
            }
        )
    )


@activity.defn
async def close_pull_request(params: CloseInput) -> None:
    """Comment why, then close a red bump's PR and delete its branch.

    The note goes through the idempotent ``upsert_issue_comment`` and the close
    itself is idempotent, so a retried close edits its comment in place and
    never double-posts. The bump's record step still runs after this, so the red
    outcome is logged either way.
    """
    from froot.adapters.github import GitHubForge
    from froot.policy.compose import CLOSE_MARKER, closed_on_red_comment

    forge = GitHubForge()
    body = closed_on_red_comment(params.failing)
    await forge.upsert_issue_comment(
        params.target, params.pr.number, CLOSE_MARKER, body
    )
    await forge.close_pull_request(
        params.target, params.pr.number, params.pr.branch
    )
    _log.info(
        json.dumps(
            {
                "event": "pr_closed",
                "loop": params.loop.value,
                "reason": "ci_red",
                "repo": params.target.repo.slug,
                "pr": params.pr.number,
                "pr_url": params.pr.url,
                "failing": list(params.failing),
            }
        )
    )


@activity.defn
async def reconcile_open_prs(params: ReconcileInput) -> int:
    """Close this loop's PRs that a newer candidate or the base has overtaken.

    Self-contained: lists the repo's open PRs, re-derives this loop's live
    candidates (a fresh checkout + the loop's signal, derive-never-store), asks
    the pure :func:`~froot.policy.reconcile.reconciliations` policy: which of
    loop's PRs to close, and closes each (deleting its branch). Scoped to the
    loop's own branch namespace, so the two loops never reconcile each other's
    PRs. A no-op when reconcile is off (``FROOT_RECONCILE``). Returns the count.
    """
    from froot.adapters.github import GitHubForge
    from froot.adapters.registry import package_manager_for
    from froot.config.settings import BehaviorSettings
    from froot.policy.compose import CLOSE_MARKER
    from froot.policy.reconcile import reconciliations

    if not BehaviorSettings().reconcile:
        return 0
    # Reconcile is version-supersession cleanup, which only bump loops have: a
    # removal carries no version to be overtaken. A loop that does not reconcile
    # (dead-code) is skipped rather than re-running its signal (knip + the veto
    # judge) every tick only to close nothing. (A removal-specific reconcile —
    # close when no longer unused — is future work.) The trait is on the spec.
    from froot.loops import registry

    if not registry.commit_tail(params.loop).reconciles:
        return 0

    target, loop = params.target, params.loop
    forge = GitHubForge()
    package_manager = package_manager_for(target.ecosystem)
    open_prs = await forge.list_open_pull_requests(target)
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        await forge.checkout(target, workspace)
        _considered, candidates = await _select_candidates(
            loop, target, package_manager, _manifest_dir(target, workspace)
        )
    closures = reconciliations(open_prs, candidates, loop)
    for closure in closures:
        await forge.upsert_issue_comment(
            target, closure.pr.number, CLOSE_MARKER, closure.comment
        )
        await forge.close_pull_request(
            target, closure.pr.number, closure.pr.branch
        )
    if closures:
        _reconcile_log.info(
            json.dumps(
                {
                    "event": "reconcile",
                    "loop": loop.value,
                    "repo": target.repo.slug,
                    "closed": len(closures),
                    "prs": [closure.pr.number for closure in closures],
                }
            )
        )
    return len(closures)


@activity.defn
async def gate_selftest(params: GateSelfTestInput) -> tuple[str, ...]:
    """Run the adversarial gate probe against the live policy; alarm on escape.

    The §2.11 deliberate disturbance for the acting gate: a battery of synthetic
    known-bad class histories a healthy gate must refuse, scored against the
    policy froot is *actually running* (config and all). Any escape — a bad
    class the live gate would grant — is logged at ERROR (the alarm) so it
    surfaces in telemetry the moment config drifts; a clean pass logs a
    heartbeat at INFO. Returns the escaped scenario names. Pure compute,
    repo-independent (the ``target``/``loop`` are only the log's context).
    """
    from froot.config.settings import AutonomySettings
    from froot.policy.gate_probe import gate_escapes

    escaped = gate_escapes(AutonomySettings().policy())
    record = json.dumps(
        {
            "event": "gate_selftest",
            "loop": params.loop.value,
            "repo": params.target.repo.slug,
            "healthy": not escaped,
            "escaped": list(escaped),
        }
    )
    if escaped:
        _gate_log.error(record)  # an alarm: the gate would trust a bad class
    else:
        _gate_log.info(record)
    return escaped


# ── The determinism reviewer (the transitive ring) ──────────────────────────
@activity.defn
async def list_review_prs(target: TargetRepo) -> tuple[PullRequestRef, ...]:
    """List the repo's open PRs for the determinism reviewer to consider."""
    from froot.adapters.github import GitHubForge

    return await GitHubForge().list_open_pull_requests(target)


@activity.defn
async def dispatch_pr_review(params: DispatchReviewInput) -> None:
    """Start a PR's determinism review (idempotent per PR + head SHA)."""
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.workflow.pr_review_workflow import PrReviewWorkflow
    from froot.workflow.temporal_client import client, task_queue

    temporal = await client()
    try:
        await temporal.start_workflow(
            PrReviewWorkflow.run,
            PrReviewParams(target=params.target, pr=params.pr),
            id=pr_review_workflow_id(
                params.target, params.pr.number, params.pr.head_sha
            ),
            task_queue=task_queue(),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        # This (PR, head SHA) already has a review — a no-op, so re-polling
        # never double-reviews the same commit.
        return


@activity.defn
async def analyze_pr(params: PrReviewParams) -> AnalysisResult:
    """Check out the PR head and analyze the workflow surface for hazards."""
    from froot.adapters.github import GitHubForge
    from froot.adapters.source_tree import load_modules
    from froot.config.settings import ReviewSettings

    forge = GitHubForge()
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        await forge.checkout_pull_request(
            params.target, workspace, params.pr.number
        )
        # The ASTs and source lines are read into memory here, so the analysis
        # below is unaffected by the workspace being cleaned up.
        modules = load_modules(workspace)
    return analyze_workflow_surface(modules, max_depth=ReviewSettings().depth)


@activity.defn
async def adjudicate_frontier(
    params: AdjudicateInput,
) -> tuple[FrontierVerdict, ...]:
    """Run the model over each frontier item; return aligned verdicts."""
    from froot.adapters.determinism_judge import DeterminismFrontierJudge

    judge = DeterminismFrontierJudge()
    verdicts: list[FrontierVerdict] = []
    for item in params.frontier:
        verdicts.append(await judge.adjudicate(item))
    return tuple(verdicts)


@activity.defn
async def post_review(params: PostReviewInput) -> str | None:
    """Upsert (or clear) the advisory comment; log the ledger row.

    Posts when there are findings, or when a prior comment must be cleared to
    "all clear" (true decay — a PR whose hazards were fixed never keeps a stale
    finding list). A clean PR with no prior comment stays silent.
    """
    from froot.adapters.github import GitHubForge

    forge = GitHubForge()
    exists = await forge.find_marked_comment(
        params.target, params.pr.number, REVIEW_MARKER
    )
    url: str | None = None
    if should_post_review(
        has_findings=bool(params.findings), comment_exists=exists
    ):
        body = render_review_comment(params.findings, params.pr.head_sha)
        url = await forge.upsert_issue_comment(
            params.target, params.pr.number, REVIEW_MARKER, body
        )
    _review_log.info(
        json.dumps(
            {
                "event": "loop_outcome",
                "loop": "determinism-review",
                "repo": params.target.repo.slug,
                "pr": params.pr.number,
                "head_sha": params.pr.head_sha,
                "findings": len(params.findings),
                "rules": sorted({f.rule for f in params.findings}),
                "comment_url": url,
            }
        )
    )
    return url


# ── The a11y reviewer (the source-level design-system ring) ──────────────────
@activity.defn
async def scan_pr_a11y(params: PrA11yReviewParams) -> A11yAnalysis:
    """Check out the PR head and scan its changed templates for a11y risks.

    Scoped to the PR's changed Vue/JSX templates (shift-left: review what came
    in), so the advisory stays bounded and high-signal. The source lines are
    read into memory in the activity, so the pure scan is unaffected by the
    workspace being cleaned up.
    """
    from froot.adapters.github import GitHubForge
    from froot.adapters.web_source import load_web_sources

    forge = GitHubForge()
    changed = await forge.list_pull_request_files(
        params.target, params.pr.number
    )
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        await forge.checkout_pull_request(
            params.target, workspace, params.pr.number
        )
        sources = load_web_sources(workspace, changed)
        candidates = scan_sources(sources)
    return A11yAnalysis(candidates=candidates, scanned_files=len(sources))


@activity.defn
async def adjudicate_a11y(
    params: AdjudicateA11yInput,
) -> tuple[A11yVerdict, ...]:
    """Run the model over each flagged candidate; return aligned verdicts."""
    from froot.adapters.a11y_judge import A11ySourceJudge

    judge = A11ySourceJudge()
    verdicts: list[A11yVerdict] = []
    for candidate in params.candidates:
        verdicts.append(await judge.adjudicate(candidate))
    return tuple(verdicts)


@activity.defn
async def post_a11y_review(params: PostA11yInput) -> str | None:
    """Upsert (or clear) the advisory comment; log the ledger row.

    Posts when there are findings, or when a prior comment must be cleared to
    "all clear" (true decay — a PR whose gaps were fixed never keeps a stale
    finding list, the bug the determinism reviewer leaves). A clean PR with
    no prior comment stays silent, so a clean PR is never spammed.
    """
    from froot.adapters.github import GitHubForge

    forge = GitHubForge()
    exists = await forge.find_marked_comment(
        params.target, params.pr.number, A11Y_MARKER
    )
    url: str | None = None
    if should_post(has_findings=bool(params.findings), comment_exists=exists):
        body = render_a11y_comment(params.findings, params.pr.head_sha)
        url = await forge.upsert_issue_comment(
            params.target, params.pr.number, A11Y_MARKER, body
        )
    _a11y_log.info(
        json.dumps(
            {
                "event": "loop_outcome",
                "loop": "a11y-review",
                "repo": params.target.repo.slug,
                "pr": params.pr.number,
                "head_sha": params.pr.head_sha,
                "findings": len(params.findings),
                "kinds": sorted({f.kind for f in params.findings}),
                "comment_url": url,
            }
        )
    )
    return url


@activity.defn
async def dispatch_pr_a11y_review(params: DispatchA11yInput) -> None:
    """Start a PR's a11y review (idempotent per PR + head SHA)."""
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.workflow.pr_a11y_review_workflow import PrA11yReviewWorkflow
    from froot.workflow.temporal_client import client, task_queue

    temporal = await client()
    try:
        await temporal.start_workflow(
            PrA11yReviewWorkflow.run,
            PrA11yReviewParams(target=params.target, pr=params.pr),
            id=pr_a11y_review_workflow_id(
                params.target, params.pr.number, params.pr.head_sha
            ),
            task_queue=task_queue(),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        # This (PR, head SHA) already has an a11y review — a no-op, so
        # re-polling never double-reviews the same commit.
        return
