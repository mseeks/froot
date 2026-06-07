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
from froot.domain.candidate import Candidate
from froot.domain.changelog import ChangelogVerdict
from froot.domain.outcome import LoopOutcome
from froot.domain.pull_request import PullRequestRef


class Discovered(Frozen):
    """A fresh candidate, not yet judged. The loop's entry state."""

    kind: Literal["discovered"] = "discovered"
    candidate: Candidate


class Judged(Frozen):
    """The changelog has been assessed; ready to open the PR."""

    kind: Literal["judged"] = "judged"
    candidate: Candidate
    verdict: ChangelogVerdict


class AwaitingCi(Frozen):
    """The PR is open; the loop is durably waiting on the repo's CI."""

    kind: Literal["awaiting_ci"] = "awaiting_ci"
    candidate: Candidate
    verdict: ChangelogVerdict
    pr: PullRequestRef


class Closing(Frozen):
    """CI failed and close-on-red is on: the PR is being closed before record.

    A transient stage between a red CI reading and the terminal record: the
    spine closes the PR (and deletes its branch), then the loop records the
    same outcome it would have anyway. Carries the already-built outcome so the
    record step needs nothing more.
    """

    kind: Literal["closing"] = "closing"
    outcome: LoopOutcome


class Merging(Frozen):
    """The PR is being auto-merged before record (green, clean, earned class).

    The mirror of :class:`Closing` on the success side — a transient stage
    between a green CI reading and the terminal record, where the spine merges
    the PR (§3.4 Stage 5) and then records the same outcome. Reached only when a
    steward has allowlisted the repo; otherwise the loop records and leaves the
    PR for the human.
    """

    kind: Literal["merging"] = "merging"
    outcome: LoopOutcome


class Recorded(Frozen):
    """Terminal: CI resolved and the outcome was recorded."""

    kind: Literal["recorded"] = "recorded"
    outcome: LoopOutcome


# The state of a single bump's loop.
BumpState = Annotated[
    Discovered | Judged | AwaitingCi | Closing | Merging | Recorded,
    Field(discriminator="kind"),
]
