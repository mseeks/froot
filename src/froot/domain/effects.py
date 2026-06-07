"""Effects: data describing what the spine should do next.

The loop's state machine is pure and performs no I/O. On each transition it
emits an *effect* — judge the changelog, open the PR, wait on CI, record the
outcome. The Temporal spine interprets each effect into an activity (or, for
:class:`AwaitCi`, a durable poll-and-sleep loop) and feeds the resulting event
back in. Effects are values, so a transition is fully testable without touching
npm, GitHub, or a model.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.candidate import Candidate
from froot.domain.changelog import ChangelogVerdict
from froot.domain.outcome import LoopOutcome
from froot.domain.pull_request import PullRequestRef


class JudgeChangelog(Frozen):
    """Fetch the candidate's changelog and get the model's typed verdict."""

    kind: Literal["judge_changelog"] = "judge_changelog"
    candidate: Candidate


class OpenPullRequest(Frozen):
    """Regenerate manifest+lockfile and open (idempotently) the bump's PR."""

    kind: Literal["open_pull_request"] = "open_pull_request"
    candidate: Candidate
    verdict: ChangelogVerdict


class AwaitCi(Frozen):
    """Durably wait on the PR's CI until it resolves or the deadline passes."""

    kind: Literal["await_ci"] = "await_ci"
    pr: PullRequestRef


class ClosePullRequest(Frozen):
    """Close a red bump's PR (comment why, close it, delete its branch).

    Emitted in place of going straight to the record when CI came back failed
    and close-on-red is enabled: the loop leaves no rotting red PR behind. The
    failing check names ride along so the spine can comment what failed; the
    record still follows (this state's outcome), so the red outcome is logged.
    """

    kind: Literal["close_pull_request"] = "close_pull_request"
    pr: PullRequestRef
    failing: tuple[str, ...] = ()


class ReviewBump(Frozen):
    """Independently deep-review a bump at the gate, before it auto-merges.

    The fourth trust leg (§3.7's *sampled deep review*, here run on every
    auto-merge candidate). Emitted when a green, clean, earned bump is about to
    merge: the spine asks a second, independent, adversarial model pass to read
    the changelog with a "find the reason to hold" stance. Only its approval
    lets the merge proceed; anything else holds the PR for the human. The
    expensive leg, spent only at the high-stakes moment.
    """

    kind: Literal["review_bump"] = "review_bump"
    candidate: Candidate
    pr: PullRequestRef


class MergePullRequest(Frozen):
    """Auto-merge a clean+green bump whose class has earned the grant.

    Emitted in place of going straight to the record when CI came back green,
    the changelog read clean, the (repo, loop) class has earned auto-merge on an
    allowlisted repo, *and* the independent gate review approved (the acting
    gate — §3.4 Stage 5). The record still follows (this state's outcome), so
    the merged outcome is logged either way. Nothing reaches here unless a
    steward has opted the repo into the allowlist; the default is empty, so the
    loop stays propose-only.
    """

    kind: Literal["merge_pull_request"] = "merge_pull_request"
    pr: PullRequestRef


class RecordOutcome(Frozen):
    """Record the closed-loop outcome (label the PR, emit run telemetry)."""

    kind: Literal["record_outcome"] = "record_outcome"
    outcome: LoopOutcome


# What the spine should do after a transition.
Effect = Annotated[
    JudgeChangelog
    | OpenPullRequest
    | AwaitCi
    | ClosePullRequest
    | ReviewBump
    | MergePullRequest
    | RecordOutcome,
    Field(discriminator="kind"),
]
