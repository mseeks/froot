"""The bump lifecycle states — one frozen model per stage of a single bump.

A bump moves Discovered -> Judged -> AwaitingCi -> Recorded, and each state
carries exactly the data valid at that stage and no more: ``Discovered`` has
only a candidate; ``AwaitingCi`` necessarily has a verdict *and* an open PR.
A state that holds a PR but no verdict, or an outcome before CI resolved, is
unrepresentable. ``Recorded`` is terminal.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.candidate import PatchCandidate
from froot.domain.changelog import ChangelogVerdict
from froot.domain.outcome import LoopOutcome
from froot.domain.pull_request import PullRequestRef


class Discovered(Frozen):
    """A fresh candidate, not yet judged. The loop's entry state."""

    kind: Literal["discovered"] = "discovered"
    candidate: PatchCandidate


class Judged(Frozen):
    """The changelog has been assessed; ready to open the PR."""

    kind: Literal["judged"] = "judged"
    candidate: PatchCandidate
    verdict: ChangelogVerdict


class AwaitingCi(Frozen):
    """The PR is open; the loop is durably waiting on the repo's CI."""

    kind: Literal["awaiting_ci"] = "awaiting_ci"
    candidate: PatchCandidate
    verdict: ChangelogVerdict
    pr: PullRequestRef


class Recorded(Frozen):
    """Terminal: CI resolved and the outcome was recorded."""

    kind: Literal["recorded"] = "recorded"
    outcome: LoopOutcome


# The state of a single bump's loop.
BumpState = Annotated[
    Discovered | Judged | AwaitingCi | Recorded,
    Field(discriminator="kind"),
]
