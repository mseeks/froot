"""Workflow inputs and results — the serializable params crossing Temporal.

Frozen, domain-shaped models the Pydantic data converter (de)serializes for
workflow and activity calls. Each activity that needs more than one value takes
a single bundled input here, so the activity signatures stay stable and typed.
"""

from __future__ import annotations

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.candidate import PatchCandidate
from froot.domain.changelog import ChangelogVerdict
from froot.domain.determinism import FrontierItem, ReviewFinding
from froot.domain.outcome import LoopOutcome
from froot.domain.pull_request import PullRequestRef
from froot.domain.repo import TargetRepo

# One day, in seconds — the default scan cadence (weekly/daily is plenty).
_DEFAULT_INTERVAL_SECONDS = 86_400
# Five minutes — the default determinism-review poll cadence (advisory, so it
# need not race the merge).
_DEFAULT_REVIEW_INTERVAL_SECONDS = 300


class ScanParams(Frozen):
    """Input to the self-scheduling scan loop."""

    target: TargetRepo
    interval_seconds: int = Field(default=_DEFAULT_INTERVAL_SECONDS, gt=0)
    continuous: bool = False


class ScanResult(Frozen):
    """The result of one scan tick.

    Attributes:
        found: Patch candidates selected this tick.
        dispatched: Candidates handed to a bump loop. Dispatch is idempotent
            (a no-op when a bump for that identity is already in flight), so
            this counts candidates dispatched, not necessarily newly started.
    """

    found: int
    dispatched: int


class BumpParams(Frozen):
    """Input to a single bump's loop."""

    target: TargetRepo
    candidate: PatchCandidate


class OpenPrInput(Frozen):
    """Input to the open-pull-request activity."""

    target: TargetRepo
    candidate: PatchCandidate
    verdict: ChangelogVerdict


class CiCheckInput(Frozen):
    """Input to the CI-status activity."""

    target: TargetRepo
    head_sha: str


class RecordInput(Frozen):
    """Input to the record-outcome activity."""

    target: TargetRepo
    outcome: LoopOutcome


class DispatchInput(Frozen):
    """Input to the dispatch-bump activity (start a bump loop)."""

    target: TargetRepo
    candidate: PatchCandidate


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
