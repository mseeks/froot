"""Workflow inputs and results — the serializable params crossing Temporal.

Frozen, domain-shaped models the Pydantic data converter (de)serializes for
workflow and activity calls. Each activity that needs more than one value takes
a single bundled input here, so the activity signatures stay stable and typed.
"""

from __future__ import annotations

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.changelog import ChangelogVerdict
from froot.domain.determinism import FrontierItem, ReviewFinding
from froot.domain.loop import Loop
from froot.domain.outcome import LoopOutcome
from froot.domain.pull_request import PullRequestRef
from froot.domain.repo import TargetRepo
from froot.domain.work import WorkItem

# One day, in seconds — the default scan cadence (weekly/daily is plenty).
_DEFAULT_INTERVAL_SECONDS = 86_400
# Five minutes — the default determinism-review poll cadence (advisory, so it
# need not race the merge).
_DEFAULT_REVIEW_INTERVAL_SECONDS = 300


class ScanParams(Frozen):
    """Input to the self-scheduling scan loop.

    ``loop`` selects which maintenance loop this scan runs (its signal, its
    candidate policy, and the branch/label/id namespace); it defaults to
    dependency-patch so existing starts are unchanged.
    """

    target: TargetRepo
    interval_seconds: int = Field(default=_DEFAULT_INTERVAL_SECONDS, gt=0)
    continuous: bool = False
    loop: Loop = Loop.DEPENDENCY_PATCH


class ScanCandidatesInput(Frozen):
    """Input to the scan-candidates activity (which loop's signal to run)."""

    target: TargetRepo
    loop: Loop = Loop.DEPENDENCY_PATCH


class ReconcileInput(Frozen):
    """Input to the reconcile activity (which loop's stale PRs to close)."""

    target: TargetRepo
    loop: Loop = Loop.DEPENDENCY_PATCH


class GateSelfTestInput(Frozen):
    """Input to the gate self-test activity (the adversarial probe's stimulus).

    The probe is policy-scoped, not repo-scoped — it tests the *live gate*, the
    same for every repo. ``target``/``loop`` ride along only as log context, so
    the alarm names the tick that fired it.
    """

    target: TargetRepo
    loop: Loop = Loop.DEPENDENCY_PATCH


class ScanResult(Frozen):
    """The result of one scan tick.

    Attributes:
        found: Patch candidates selected this tick.
        dispatched: Candidates handed to a bump loop. Dispatch is idempotent
            (a no-op when a bump for that identity is already in flight), so
            this counts candidates dispatched, not necessarily newly started.
        reconciled: froot PRs closed this tick as superseded or already
            satisfied (zero when the reconcile sweep is disabled).
    """

    found: int
    dispatched: int
    reconciled: int = 0


class BumpParams(Frozen):
    """Input to a single bump's loop.

    Attributes:
        target: The repo the bump is proposed against.
        candidate: The bump being proposed.
        close_on_red: Whether a red CI result should close the PR (and delete
            its branch). Pinned at dispatch from ``FROOT_CLOSE_ON_RED`` so the
            running bump keeps the value it started with, never reading config
            from inside the deterministic workflow.
    """

    target: TargetRepo
    candidate: WorkItem
    close_on_red: bool = True
    loop: Loop = Loop.DEPENDENCY_PATCH


class JudgeInput(Frozen):
    """Input to the changelog-judge activity (candidate + which loop asks)."""

    candidate: WorkItem
    loop: Loop = Loop.DEPENDENCY_PATCH


class GateReviewInput(Frozen):
    """Input to the gate-review activity (the fourth trust leg's deep read).

    The candidate to re-read and the PR it is about to merge (for the log); the
    loop frames the adversarial prompt just as the first judge pass is framed.
    """

    candidate: WorkItem
    pr: PullRequestRef
    loop: Loop = Loop.DEPENDENCY_PATCH


class OpenPrInput(Frozen):
    """Input to the open-pull-request activity."""

    target: TargetRepo
    candidate: WorkItem
    verdict: ChangelogVerdict
    loop: Loop = Loop.DEPENDENCY_PATCH


class CiCheckInput(Frozen):
    """Input to the CI-status activity."""

    target: TargetRepo
    head_sha: str


class RecordInput(Frozen):
    """Input to the record-outcome activity."""

    target: TargetRepo
    outcome: LoopOutcome
    loop: Loop = Loop.DEPENDENCY_PATCH


class CloseInput(Frozen):
    """Input to the close-pull-request activity (the close-on-red path).

    Attributes:
        target: The repo the PR lives on.
        pr: The PR to close (its branch is deleted with it).
        failing: The names of the checks that failed, for the close comment.
        loop: Which loop owns the PR (for the structured close log).
    """

    target: TargetRepo
    pr: PullRequestRef
    failing: tuple[str, ...] = ()
    loop: Loop = Loop.DEPENDENCY_PATCH


class MergeInput(Frozen):
    """Input to the merge-pull-request activity (the acting gate's write)."""

    target: TargetRepo
    pr: PullRequestRef
    loop: Loop = Loop.DEPENDENCY_PATCH


class AutoMergeInput(Frozen):
    """Input to the auto-merge-eligibility activity (the class-level grant).

    The activity asks whether this ``(target, loop)`` class has *earned* the
    auto-merge grant on an allowlisted repo — the class-level half of the gate
    the pure machine can't compute (it needs the class's history). A no-op
    returning False for any repo a steward has not allowlisted.
    """

    target: TargetRepo
    loop: Loop = Loop.DEPENDENCY_PATCH


class DispatchInput(Frozen):
    """Input to the dispatch-bump activity (start a bump loop)."""

    target: TargetRepo
    candidate: WorkItem
    loop: Loop = Loop.DEPENDENCY_PATCH


class ReviewScanParams(Frozen):
    """Input to the self-scheduling determinism-review loop (per repo)."""

    target: TargetRepo
    interval_seconds: int = Field(
        default=_DEFAULT_REVIEW_INTERVAL_SECONDS, gt=0
    )
    continuous: bool = False


class ReviewScanResult(Frozen):
    """The result of one review-scan tick.

    Attributes:
        reviewed: Open PRs seen this tick.
        dispatched: PR reviews handed off (idempotent per PR + head SHA).
    """

    reviewed: int
    dispatched: int


class PrReviewParams(Frozen):
    """Input to a single PR's determinism review."""

    target: TargetRepo
    pr: PullRequestRef


class DispatchReviewInput(Frozen):
    """Input to the dispatch-pr-review activity (start a PR review loop)."""

    target: TargetRepo
    pr: PullRequestRef


class AdjudicateInput(Frozen):
    """Input to the frontier-adjudication activity (the model pass)."""

    frontier: tuple[FrontierItem, ...]


class PostReviewInput(Frozen):
    """Input to the post-review activity (upsert the advisory comment)."""

    target: TargetRepo
    pr: PullRequestRef
    findings: tuple[ReviewFinding, ...]
