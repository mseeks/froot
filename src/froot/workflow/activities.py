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

from froot.domain.candidate import Candidate
from froot.domain.changelog import ChangelogVerdict, UnknownVerdict
from froot.domain.ci import CIStatus
from froot.domain.determinism import AnalysisResult, FrontierVerdict
from froot.domain.loop import Loop
from froot.domain.pull_request import PullRequestRef
from froot.domain.repo import TargetRepo
from froot.policy.compose import pr_labels, pull_request_draft
from froot.policy.determinism import analyze_workflow_surface
from froot.policy.naming import (
    branch_name,
    bump_workflow_id,
    pr_review_workflow_id,
)
from froot.policy.review_comment import REVIEW_MARKER, render_review_comment
from froot.workflow.types import (
    AdjudicateInput,
    AutoMergeInput,
    CiCheckInput,
    CloseInput,
    DispatchInput,
    DispatchReviewInput,
    JudgeInput,
    MergeInput,
    OpenPrInput,
    PostReviewInput,
    PrReviewParams,
    ReconcileInput,
    RecordInput,
    ScanCandidatesInput,
)

if TYPE_CHECKING:
    from froot.ports.protocols import PackageManager

_log = logging.getLogger("froot.outcome")
_review_log = logging.getLogger("froot.review")
_reconcile_log = logging.getLogger("froot.reconcile")
_scan_log = logging.getLogger("froot.scan")


def _manifest_dir(target: TargetRepo, workspace: Path) -> Path:
    """The directory the manifest lives in (a monorepo subdir, or the root)."""
    return workspace / target.manifest_dir if target.manifest_dir else workspace


async def _select_candidates(
    loop: Loop,
    target: TargetRepo,
    package_manager: PackageManager,
    manifest_dir: Path,
) -> tuple[int, tuple[Candidate, ...]]:
    """Gather this loop's signal from the checkout and select its candidates.

    The one genuinely per-loop seam: dependency-patch reads the available
    upgrades and picks the highest patch; security-patch reads the installed,
    asks OSV for advisories, and picks the lowest version clearing each. The
    impure sources are lazy-imported per arm so neither drags the other's stack
    into a sandbox. Both feed a pure selection policy.

    Returns ``(considered, candidates)`` — ``considered`` is the size of the
    upstream signal (available upgrades / advisories found) so the scan can make
    its selectivity legible (how much was seen versus how much was kept).
    """
    match loop:
        case Loop.DEPENDENCY_PATCH:
            from froot.policy.candidates import select_patch_candidates

            upgrades = await package_manager.list_upgrades(target, manifest_dir)
            return len(upgrades), select_patch_candidates(upgrades)
        case Loop.SECURITY_PATCH:
            return await _select_security_candidates(
                target, package_manager, manifest_dir
            )
    assert_never(loop)


async def _select_security_candidates(
    target: TargetRepo, package_manager: PackageManager, manifest_dir: Path
) -> tuple[int, tuple[Candidate, ...]]:
    """Security signal: installed set, OSV advisories, clearing targets.

    ``considered`` is the count of advisories OSV returned for the installed
    set — the vulnerabilities in scope this tick, before selection narrows to
    the ones a forward-stable bump can actually clear.
    """
    from froot.adapters.osv import OsvAdvisorySource
    from froot.policy.candidates import select_security_candidates

    installed = await package_manager.list_installed(target, manifest_dir)
    advisories = await OsvAdvisorySource().advisories(installed)
    return len(advisories), select_security_candidates(installed, advisories)


@activity.defn
async def scan_candidates(
    params: ScanCandidatesInput,
) -> tuple[Candidate, ...]:
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

    changelog = await HttpChangelogSource().fetch(params.candidate)
    if changelog is None:
        return UnknownVerdict(rationale="No changelog could be fetched.")
    try:
        return await PydanticAiJudge().judge(changelog, params.loop)
    except Exception as exc:
        activity.logger.warning(
            "changelog judge unavailable for %s; degrading to unknown: %r",
            params.candidate.package,
            exc,
        )
        return UnknownVerdict(
            rationale=f"Changelog judge unavailable ({type(exc).__name__})."
        )


@activity.defn
async def open_pull_request(params: OpenPrInput) -> PullRequestRef:
    """Regenerate manifest+lockfile and open (idempotently) the bump's PR."""
    from froot.adapters.github import GitHubForge
    from froot.adapters.registry import package_manager_for

    forge = GitHubForge()
    package_manager = package_manager_for(params.target.ecosystem)
    branch = branch_name(params.candidate, params.loop)
    existing = await forge.find_open_pull_request(params.target, branch)
    if existing is not None:
        return existing
    draft = pull_request_draft(
        params.target, params.candidate, params.verdict, params.loop
    )
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        await forge.checkout(params.target, workspace)
        await package_manager.apply_patch_bump(
            params.candidate, _manifest_dir(params.target, workspace)
        )
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
    labels = (
        *pr_labels(params.loop),
        env_label(ModelSettings().ollama_model),
    )
    await GitHubForge().add_labels(params.target, outcome.pr.number, labels)
    _log.info(
        json.dumps(
            {
                "event": "loop_outcome",
                "loop": params.loop.value,
                "repo": params.target.repo.slug,
                "package": outcome.candidate.package,
                "from": str(outcome.candidate.current),
                "to": str(outcome.candidate.target),
                "changelog": outcome.verdict.kind,
                "ci": outcome.ci.kind,
                "ci_passed": outcome.ci_passed,
                "pr": outcome.pr.number,
                "pr_url": outcome.pr.url,
            }
        )
    )


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
    """Upsert the advisory comment (when there are findings); log the ledger."""
    from froot.adapters.github import GitHubForge

    body = render_review_comment(params.findings, params.pr.head_sha)
    url: str | None = None
    if body is not None:
        url = await GitHubForge().upsert_issue_comment(
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
