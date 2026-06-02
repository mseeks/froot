"""CI status — the loop's verification, owned by the target repo's own CI.

froot never re-runs a repo's tests (SPEC: CI is the oracle). It opens a PR and
reads the repo's existing checks. :class:`CIPending` means keep waiting;
everything else is terminal — :class:`CIAbsent` (the repo has no checks to
trust) and :class:`CITimedOut` (froot stopped waiting) are distinct from a real
:class:`CIPassed` / :class:`CIFailed` so the recorded outcome never conflates
"green" with "couldn't tell". The recorded outcome is typed to the
:data:`TerminalCIStatus` subset, so a pending status can never be recorded.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeIs

from pydantic import Field

from froot.domain.base import Frozen


class CIPending(Frozen):
    """Checks are still running; the loop keeps waiting (not terminal)."""

    kind: Literal["pending"] = "pending"


class CIPassed(Frozen):
    """All required checks succeeded — the PR is ready for a human merge."""

    kind: Literal["passed"] = "passed"


class CIFailed(Frozen):
    """At least one check failed; the PR stays open, flagged for the human."""

    kind: Literal["failed"] = "failed"
    failing: tuple[str, ...] = ()


class CIAbsent(Frozen):
    """The repo configured no checks for this commit — nothing to verify."""

    kind: Literal["absent"] = "absent"


class CITimedOut(Frozen):
    """The loop's CI-wait deadline elapsed before checks resolved."""

    kind: Literal["timed_out"] = "timed_out"


# A point-in-time CI reading. Only ``CIPending`` is non-terminal.
CIStatus = Annotated[
    CIPending | CIPassed | CIFailed | CIAbsent | CITimedOut,
    Field(discriminator="kind"),
]

# A terminal CI reading — every reading except still-pending. The recorded loop
# outcome is typed to this, so a pending CI can never be recorded as an outcome.
TerminalCIStatus = Annotated[
    CIPassed | CIFailed | CIAbsent | CITimedOut,
    Field(discriminator="kind"),
]


def is_terminal(status: CIStatus) -> TypeIs[TerminalCIStatus]:
    """Whether a CI reading is final (narrows to :data:`TerminalCIStatus`)."""
    return not isinstance(status, CIPending)
