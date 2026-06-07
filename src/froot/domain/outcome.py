"""The loop outcome — the signal-update that closes the loop.

When a bump reaches a terminal CI status, the loop records a
:class:`LoopOutcome` and stops. froot stores no outcome of its own (SPEC:
derive, never store): the
record *is* the PR (left open for the human, labeled by this outcome) plus the
run telemetry. This value is what the recording effect carries to those two
external truths — GitHub and ClickStack.
"""

from __future__ import annotations

from froot.domain.base import Frozen
from froot.domain.changelog import ChangelogVerdict
from froot.domain.ci import CIPassed, TerminalCIStatus
from froot.domain.pull_request import PullRequestRef
from froot.domain.work import WorkItem


class LoopOutcome(Frozen):
    """How a single proposed bump fared, end to end.

    Attributes:
        candidate: The bump that was proposed.
        verdict: The model's changelog framing (recorded for the human).
        pr: The pull request that was opened.
        ci: The terminal CI reading (passed / failed / absent / timed out) —
            a still-pending status is not assignable here.
    """

    candidate: WorkItem
    verdict: ChangelogVerdict
    pr: PullRequestRef
    ci: TerminalCIStatus

    @property
    def ci_passed(self) -> bool:
        """True iff the repo's CI went green for this proposal."""
        return isinstance(self.ci, CIPassed)
