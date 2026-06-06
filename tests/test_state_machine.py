from __future__ import annotations

from froot.domain.changelog import CleanVerdict
from froot.domain.ci import CIFailed, CIPassed, CIPending
from froot.domain.effects import (
    AwaitCi,
    ClosePullRequest,
    JudgeChangelog,
    OpenPullRequest,
    RecordOutcome,
)
from froot.domain.events import (
    ChangelogJudged,
    CiResolved,
    LoopEvent,
    OutcomeRecorded,
    PullRequestClosed,
    PullRequestReady,
)
from froot.domain.outcome import LoopOutcome
from froot.domain.state import (
    AwaitingCi,
    BumpState,
    Closing,
    Discovered,
    Judged,
    Recorded,
)
from froot.policy.state_machine import TransitionKind, advance, start
from tests.support import make_candidate, make_pr

_VERDICT = CleanVerdict(rationale="patch only")


def test_start_enters_discovered_and_judges():
    transition = start(make_candidate())
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Discovered)
    assert len(transition.effects) == 1
    assert isinstance(transition.effects[0], JudgeChangelog)


def test_happy_path_drives_to_recorded():
    candidate = make_candidate()
    pr = make_pr()
    transition = start(candidate)

    transition = advance(transition.next, ChangelogJudged(verdict=_VERDICT))
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Judged)
    assert isinstance(transition.effects[0], OpenPullRequest)

    transition = advance(transition.next, PullRequestReady(pr=pr))
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, AwaitingCi)
    assert isinstance(transition.effects[0], AwaitCi)

    transition = advance(transition.next, CiResolved(status=CIPassed()))
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)
    assert transition.next.outcome.ci_passed

    transition = advance(transition.next, OutcomeRecorded())
    assert transition.kind is TransitionKind.IGNORED
    assert transition.effects == ()


def test_pending_ci_is_rejected_not_recorded():
    state = AwaitingCi(
        candidate=make_candidate(), verdict=_VERDICT, pr=make_pr()
    )
    transition = advance(state, CiResolved(status=CIPending()))
    assert transition.kind is TransitionKind.REJECTED
    assert transition.next == state


def test_red_ci_closes_pr_when_close_on_red_on():
    state = AwaitingCi(
        candidate=make_candidate(), verdict=_VERDICT, pr=make_pr()
    )
    transition = advance(
        state,
        CiResolved(status=CIFailed(failing=("build",))),
        close_on_red=True,
    )
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Closing)
    effect = transition.effects[0]
    assert isinstance(effect, ClosePullRequest)
    assert effect.failing == ("build",)
    # The outcome is preserved on the Closing state to record after the close.
    assert isinstance(transition.next.outcome.ci, CIFailed)


def test_red_ci_records_directly_when_close_on_red_off():
    state = AwaitingCi(
        candidate=make_candidate(), verdict=_VERDICT, pr=make_pr()
    )
    transition = advance(
        state, CiResolved(status=CIFailed()), close_on_red=False
    )
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)


def test_closing_records_on_pull_request_closed():
    outcome = LoopOutcome(
        candidate=make_candidate(),
        verdict=_VERDICT,
        pr=make_pr(),
        ci=CIFailed(failing=("build",)),
    )
    transition = advance(Closing(outcome=outcome), PullRequestClosed())
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)
    assert transition.next.outcome is outcome


def test_unexpected_events_are_rejected_in_each_state():
    candidate = make_candidate()
    pr = make_pr()
    recorded = Recorded(
        outcome=LoopOutcome(
            candidate=candidate, verdict=_VERDICT, pr=pr, ci=CIPassed()
        )
    )
    rejections: list[tuple[BumpState, LoopEvent]] = [
        (Discovered(candidate=candidate), PullRequestReady(pr=pr)),
        (Judged(candidate=candidate, verdict=_VERDICT), OutcomeRecorded()),
        (
            AwaitingCi(candidate=candidate, verdict=_VERDICT, pr=pr),
            ChangelogJudged(verdict=_VERDICT),
        ),
        (Closing(outcome=recorded.outcome), ChangelogJudged(verdict=_VERDICT)),
        (recorded, PullRequestReady(pr=pr)),
    ]
    for state, event in rejections:
        transition = advance(state, event)
        assert transition.kind is TransitionKind.REJECTED
        assert transition.next == state
