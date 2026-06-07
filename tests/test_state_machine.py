from __future__ import annotations

from froot.domain.changelog import CleanVerdict, RiskyVerdict
from froot.domain.ci import CIAbsent, CIFailed, CIPassed, CIPending
from froot.domain.effects import (
    AwaitCi,
    ClosePullRequest,
    JudgeChangelog,
    MergePullRequest,
    OpenPullRequest,
    RecordOutcome,
    ReviewBump,
)
from froot.domain.events import (
    ChangelogJudged,
    CiResolved,
    GateReviewed,
    LoopEvent,
    OutcomeRecorded,
    PullRequestClosed,
    PullRequestMerged,
    PullRequestReady,
)
from froot.domain.outcome import LoopOutcome
from froot.domain.state import (
    AwaitingCi,
    BumpState,
    Closing,
    Discovered,
    GateReviewing,
    Judged,
    Merging,
    Recorded,
)
from froot.policy.state_machine import TransitionKind, advance, start
from tests.support import make_candidate, make_pr, make_removal

_VERDICT = CleanVerdict(rationale="patch only")


def test_start_enters_discovered_and_judges():
    transition = start(make_candidate())
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Discovered)
    assert len(transition.effects) == 1
    assert isinstance(transition.effects[0], JudgeChangelog)


def test_removal_flows_through_the_spine_unchanged():
    # The work-item widening: a non-bump kind (a removal, no version) rides the
    # same pure spine. The machine never inspects the payload — it carries the
    # removal through start -> judge -> PR -> CI -> record untouched.
    removal = make_removal(package="left-pad")
    pr = make_pr()

    transition = start(removal)
    assert isinstance(transition.next, Discovered)
    assert transition.next.candidate is removal
    judge = transition.effects[0]
    assert isinstance(judge, JudgeChangelog)
    assert judge.candidate is removal

    transition = advance(transition.next, ChangelogJudged(verdict=_VERDICT))
    transition = advance(transition.next, PullRequestReady(pr=pr))
    transition = advance(transition.next, CiResolved(status=CIPassed()))
    assert isinstance(transition.next, Recorded)
    assert transition.next.outcome.candidate is removal


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


# ── The acting gate (auto-merge on an earned class) ──────────────────────────
def test_green_clean_eligible_class_enters_gate_review():
    # An earned, clean, green bump does not merge straight away: it first goes
    # to the independent deep review (the fourth leg), carrying its outcome.
    state = AwaitingCi(
        candidate=make_candidate(), verdict=_VERDICT, pr=make_pr()
    )
    transition = advance(
        state, CiResolved(status=CIPassed()), auto_merge_eligible=True
    )
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, GateReviewing)
    assert isinstance(transition.effects[0], ReviewBump)
    # The outcome is preserved on GateReviewing to merge/record afterwards.
    assert transition.next.outcome.ci_passed


def test_gate_review_clean_then_merges():
    outcome = LoopOutcome(
        candidate=make_candidate(),
        verdict=_VERDICT,
        pr=make_pr(),
        ci=CIPassed(),
    )
    transition = advance(
        GateReviewing(outcome=outcome),
        GateReviewed(verdict=CleanVerdict(rationale="re-read clean")),
    )
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Merging)
    assert isinstance(transition.effects[0], MergePullRequest)
    assert transition.next.outcome is outcome


def test_gate_review_hold_records_and_leaves_open():
    # A non-clean deep review holds: record the outcome, leave the PR open for
    # the human — never merge. Fail-closed for unknown too.
    outcome = LoopOutcome(
        candidate=make_candidate(),
        verdict=_VERDICT,
        pr=make_pr(),
        ci=CIPassed(),
    )
    transition = advance(
        GateReviewing(outcome=outcome),
        GateReviewed(verdict=RiskyVerdict(rationale="found a deprecation")),
    )
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)
    assert transition.next.outcome is outcome


def test_green_clean_not_eligible_records_and_leaves_open():
    # The default: no class grant -> propose-only, record, leave for the human.
    state = AwaitingCi(
        candidate=make_candidate(), verdict=_VERDICT, pr=make_pr()
    )
    transition = advance(state, CiResolved(status=CIPassed()))
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)


def test_risky_verdict_does_not_auto_merge_even_if_eligible():
    # The per-PR condition (clean changelog) is checked in the machine; a risky
    # verdict never auto-merges, regardless of the class grant.
    state = AwaitingCi(
        candidate=make_candidate(),
        verdict=RiskyVerdict(rationale="a deprecation"),
        pr=make_pr(),
    )
    transition = advance(
        state, CiResolved(status=CIPassed()), auto_merge_eligible=True
    )
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)


def test_absent_ci_does_not_auto_merge_even_if_clean_and_eligible():
    # No oracle is never a pass: absent CI records, never auto-merges.
    state = AwaitingCi(
        candidate=make_candidate(), verdict=_VERDICT, pr=make_pr()
    )
    transition = advance(
        state, CiResolved(status=CIAbsent()), auto_merge_eligible=True
    )
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)


def test_merging_records_on_pull_request_merged():
    outcome = LoopOutcome(
        candidate=make_candidate(),
        verdict=_VERDICT,
        pr=make_pr(),
        ci=CIPassed(),
    )
    transition = advance(Merging(outcome=outcome), PullRequestMerged())
    assert transition.kind is TransitionKind.ADVANCED
    assert isinstance(transition.next, Recorded)
    assert isinstance(transition.effects[0], RecordOutcome)
    assert transition.next.outcome is outcome


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
        (
            GateReviewing(outcome=recorded.outcome),
            ChangelogJudged(verdict=_VERDICT),
        ),
        (Merging(outcome=recorded.outcome), ChangelogJudged(verdict=_VERDICT)),
        (recorded, PullRequestReady(pr=pr)),
    ]
    for state, event in rejections:
        transition = advance(state, event)
        assert transition.kind is TransitionKind.REJECTED
        assert transition.next == state
