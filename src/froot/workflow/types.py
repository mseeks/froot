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
from froot.domain.outcome import LoopOutcome
from froot.domain.repo import TargetRepo

# One day, in seconds — the default scan cadence (weekly/daily is plenty).
_DEFAULT_INTERVAL_SECONDS = 86_400


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
