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

from temporalio import activity

from froot.domain.candidate import PatchCandidate
from froot.domain.changelog import ChangelogVerdict, UnknownVerdict
from froot.domain.ci import CIStatus
from froot.domain.pull_request import PullRequestRef
from froot.domain.repo import TargetRepo
from froot.policy.candidates import select_patch_candidates
from froot.policy.compose import outcome_labels, pull_request_draft
from froot.policy.naming import branch_name, bump_workflow_id
from froot.workflow.types import (
    CiCheckInput,
    DispatchInput,
    OpenPrInput,
    RecordInput,
)

_log = logging.getLogger("froot.outcome")


def _manifest_dir(target: TargetRepo, workspace: Path) -> Path:
    """The directory the manifest lives in (a monorepo subdir, or the root)."""
    return workspace / target.manifest_dir if target.manifest_dir else workspace


@activity.defn
async def scan_candidates(
    target: TargetRepo,
) -> tuple[PatchCandidate, ...]:
    """Check out the repo, read available upgrades, select patch candidates."""
    from froot.adapters.github import GitHubForge
    from froot.adapters.npm import NpmPackageManager

    forge = GitHubForge()
    package_manager = NpmPackageManager()
    with tempfile.TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        await forge.checkout(target, workspace)
        upgrades = await package_manager.list_upgrades(
            target, _manifest_dir(target, workspace)
        )
    return select_patch_candidates(upgrades)


@activity.defn
async def judge_changelog(candidate: PatchCandidate) -> ChangelogVerdict:
    """Fetch the candidate's changelog and get the model's typed verdict."""
    from froot.adapters.changelog_http import HttpChangelogSource
    from froot.adapters.model_judge import PydanticAiJudge

    changelog = await HttpChangelogSource().fetch(candidate)
    if changelog is None:
        return UnknownVerdict(rationale="No changelog could be fetched.")
    return await PydanticAiJudge().judge(changelog)


@activity.defn
async def open_pull_request(params: OpenPrInput) -> PullRequestRef:
    """Regenerate manifest+lockfile and open (idempotently) the bump's PR."""
    from froot.adapters.github import GitHubForge
    from froot.adapters.npm import NpmPackageManager

    forge = GitHubForge()
    package_manager = NpmPackageManager()
    branch = branch_name(params.candidate)
    existing = await forge.find_open_pull_request(params.target, branch)
    if existing is not None:
        return existing
    draft = pull_request_draft(params.target, params.candidate, params.verdict)
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
    """Label the PR and log the run telemetry — the signal-update."""
    from froot.adapters.github import GitHubForge

    outcome = params.outcome
    await GitHubForge().add_labels(
        params.target, outcome.pr.number, outcome_labels(outcome)
    )
    _log.info(
        json.dumps(
            {
                "event": "loop_outcome",
                "loop": "dependency-patch",
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
    """Start the bump loop for a candidate (idempotent per bump identity)."""
    from temporalio.common import WorkflowIDReusePolicy
    from temporalio.exceptions import WorkflowAlreadyStartedError

    from froot.workflow.bump_workflow import BumpWorkflow
    from froot.workflow.temporal_client import client, task_queue
    from froot.workflow.types import BumpParams

    temporal = await client()
    try:
        await temporal.start_workflow(
            BumpWorkflow.run,
            BumpParams(target=params.target, candidate=params.candidate),
            id=bump_workflow_id(params.target, params.candidate),
            task_queue=task_queue(),
            id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
        )
    except WorkflowAlreadyStartedError:
        # This bump already has a loop (running or completed) — a no-op, so
        # re-scanning never opens a second PR for the same bump.
        return
