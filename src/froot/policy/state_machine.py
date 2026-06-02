"""The bump loop state machine: pure transitions, effects as data.

``start`` and ``advance`` are pure: given the current state and a decided event,
they return a :class:`Transition` — the next state plus the effects the spine
should run. No I/O, no clock, so a transition replays deterministically and is
fully testable. Dispatch is per-state and ends in ``assert_never`` so the type
checker proves every state is handled; an event a state does not expect yields a
``REJECTED`` transition (no state change), never an exception.

The loop is linear: each advance emits exactly one effect, the spine runs it to
obtain the next event, and the cycle repeats until ``Recorded`` (no effects). A
:class:`~froot.domain.events.CiResolved` that is still pending is rejected — the
spine must finish waiting before the machine will close the loop, so an outcome
can never be recorded against an unresolved CI status.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, assert_never

from froot.domain.base import Frozen
from froot.domain.ci import is_terminal
from froot.domain.effects import (
    AwaitCi,
    Effect,
    JudgeChangelog,
    OpenPullRequest,
    RecordOutcome,
)
from froot.domain.events import (
    ChangelogJudged,
    CiResolved,
    LoopEvent,
    OutcomeRecorded,
    PullRequestReady,
)
from froot.domain.outcome import LoopOutcome
from froot.domain.state import (
    AwaitingCi,
    BumpState,
    Discovered,
    Judged,
    Recorded,
)

if TYPE_CHECKING:
    from froot.domain.candidate import PatchCandidate


class TransitionKind(StrEnum):
    """The disposition of an :func:`advance` call."""

    ADVANCED = "advanced"
    IGNORED = "ignored"
    REJECTED = "rejected"


class Transition(Frozen):
    """The result of a transition.

    Attributes:
        kind: ``ADVANCED`` (moved and/or emitted effects), ``IGNORED`` (a legal
            no-op, e.g. the terminal acknowledgement), or ``REJECTED`` (the
            event is not valid in this state).
        next: The resulting state (unchanged for ``IGNORED``/``REJECTED``).
        effects: The effects the spine should run, in order. Empty terminates
            the loop driver.
        reason: A short explanation for an ``IGNORED``/``REJECTED`` transition.
    """

    kind: TransitionKind
    next: BumpState
    effects: tuple[Effect, ...] = ()
    reason: str | None = None


def _advanced(nxt: BumpState, *effects: Effect) -> Transition:
    return Transition(kind=TransitionKind.ADVANCED, next=nxt, effects=effects)


def _rejected(state: BumpState, reason: str) -> Transition:
    return Transition(kind=TransitionKind.REJECTED, next=state, reason=reason)


def start(candidate: PatchCandidate) -> Transition:
    """The opening transition: enter ``Discovered`` and judge the changelog."""
    return _advanced(
        Discovered(candidate=candidate),
        JudgeChangelog(candidate=candidate),
    )


def advance(state: BumpState, event: LoopEvent) -> Transition:
    """Advance the loop one step (pure).

    Args:
        state: The current bump state.
        event: The decided event that just occurred.

    Returns:
        The :class:`Transition` to apply.
    """
    match state:
        case Discovered():
            return _from_discovered(state, event)
        case Judged():
            return _from_judged(state, event)
        case AwaitingCi():
            return _from_awaiting_ci(state, event)
        case Recorded():
            return _from_recorded(state, event)
    assert_never(state)


def _from_discovered(state: Discovered, event: LoopEvent) -> Transition:
    match event:
        case ChangelogJudged():
            return _advanced(
                Judged(candidate=state.candidate, verdict=event.verdict),
                OpenPullRequest(
                    candidate=state.candidate, verdict=event.verdict
                ),
            )
        case _:
            return _rejected(state, f"unexpected {event.kind} in discovered")


def _from_judged(state: Judged, event: LoopEvent) -> Transition:
    match event:
        case PullRequestReady():
            return _advanced(
                AwaitingCi(
                    candidate=state.candidate,
                    verdict=state.verdict,
                    pr=event.pr,
                ),
                AwaitCi(pr=event.pr),
            )
        case _:
            return _rejected(state, f"unexpected {event.kind} in judged")


def _from_awaiting_ci(state: AwaitingCi, event: LoopEvent) -> Transition:
    match event:
        case CiResolved():
            if not is_terminal(event.status):
                return _rejected(state, "ci still pending; the spine must wait")
            outcome = LoopOutcome(
                candidate=state.candidate,
                verdict=state.verdict,
                pr=state.pr,
                ci=event.status,
            )
            return _advanced(
                Recorded(outcome=outcome), RecordOutcome(outcome=outcome)
            )
        case _:
            return _rejected(state, f"unexpected {event.kind} in awaiting_ci")


def _from_recorded(state: Recorded, event: LoopEvent) -> Transition:
    # Terminal: the only expected event is the record acknowledgement, a no-op
    # that ends the driver loop (no effects).
    match event:
        case OutcomeRecorded():
            return Transition(
                kind=TransitionKind.IGNORED, next=state, reason="loop complete"
            )
        case _:
            return _rejected(state, f"unexpected {event.kind} after recorded")
