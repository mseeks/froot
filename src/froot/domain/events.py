"""Lifecycle events: the decided inputs that drive the state machine.

Each event carries an already-decided result — the model judged the changelog,
the PR was opened, CI resolved — so by the time an event reaches
:func:`froot.policy.state_machine.advance`, the machine only decides *where the
loop goes next*, never *what the judgment was*. All interpretation (the model
call, the CI poll) happens in the spine's activities and arrives here as data.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.changelog import ChangelogVerdict
from froot.domain.ci import CIStatus
from froot.domain.pull_request import PullRequestRef


class ChangelogJudged(Frozen):
    """The model returned its verdict on the candidate's changelog."""

    kind: Literal["changelog_judged"] = "changelog_judged"
    verdict: ChangelogVerdict


class PullRequestReady(Frozen):
    """The PR for this bump is open (newly created or already existing)."""

    kind: Literal["pull_request_ready"] = "pull_request_ready"
    pr: PullRequestRef


class CiResolved(Frozen):
    """CI reached a terminal status (never ``CIPending``; the spine waits)."""

    kind: Literal["ci_resolved"] = "ci_resolved"
    status: CIStatus


class OutcomeRecorded(Frozen):
    """The outcome was recorded; the loop has nothing left to do."""

    kind: Literal["outcome_recorded"] = "outcome_recorded"


# A decided input to the loop state machine.
LoopEvent = Annotated[
    ChangelogJudged | PullRequestReady | CiResolved | OutcomeRecorded,
    Field(discriminator="kind"),
]
