"""The judge eval's grade, reduction, alert decision, and golden set.

The eval's logic lives in the pure half (:mod:`froot.policy.judge_eval`); these
pin it without a model. The asymmetric grade is the crux — a risky changelog
read as ``clean`` must fail, a risky one read as ``unknown`` must pass — so it
gets the most attention. Two offline tests then drive the live-run wiring
(:func:`froot.judge_eval._evaluate`) with a hand fake judge: the regression this
whole feature exists to catch (the judge waving everything through as clean must
alarm and name the risky cases) and its silent happy path.
"""

from __future__ import annotations

from froot.domain.changelog import (
    Changelog,
    ChangelogVerdict,
    CleanVerdict,
    RiskyVerdict,
    UnknownVerdict,
)
from froot.domain.loop import Loop
from froot.judge_eval import _evaluate
from froot.policy.judge_eval import (
    GOLDEN,
    CaseOutcome,
    EvalCase,
    EvalSummary,
    eval_alert,
    grade,
    outcome,
    summarize,
)
from tests.support import ver


def _case(expect_clean: bool, name: str = "c") -> EvalCase:
    return EvalCase(
        name=name,
        changelog=Changelog(package="p", version=ver("1.0.0"), text="notes"),
        expect_clean=expect_clean,
    )


def _outcome(
    name: str, *, passed: bool, expect_clean: bool = False
) -> CaseOutcome:
    return CaseOutcome(
        name=name,
        expect_clean=expect_clean,
        got="clean",
        rationale="looks fine",
        passed=passed,
    )


def test_grade_clean_case_requires_clean():
    case = _case(expect_clean=True)
    assert grade(case, CleanVerdict(rationale="r")) is True
    assert grade(case, RiskyVerdict(rationale="r")) is False
    assert grade(case, UnknownVerdict(rationale="r")) is False


def test_grade_risky_case_rejects_clean_but_accepts_unknown():
    # The asymmetric crux: the unsafe drift is risky-read-as-clean, so only
    # ``clean`` fails a risky case; ``risky`` and ``unknown`` both pass.
    case = _case(expect_clean=False)
    assert grade(case, CleanVerdict(rationale="r")) is False
    assert grade(case, RiskyVerdict(rationale="r")) is True
    assert grade(case, UnknownVerdict(rationale="r")) is True


def test_outcome_records_verdict_kind_rationale_and_pass():
    out = outcome(
        _case(expect_clean=True, name="x"),
        RiskyVerdict(rationale="behaves differently"),
    )
    assert out.name == "x"
    assert out.got == "risky"
    assert out.rationale == "behaves differently"
    assert out.passed is False


def test_summarize_counts_passes_and_collects_only_failures():
    summary = summarize(
        (
            _outcome("a", passed=True),
            _outcome("b", passed=False),
            _outcome("c", passed=True),
        )
    )
    assert summary.total == 3
    assert summary.passed == 2
    assert tuple(o.name for o in summary.failures) == ("b",)


def test_eval_alert_silent_when_all_pass():
    assert eval_alert(EvalSummary(total=3, passed=3)) is None


def test_eval_alert_names_each_mismatch_with_what_it_got():
    summary = EvalSummary(
        total=2,
        passed=1,
        failures=(_outcome("behavior-hidden", passed=False),),
    )
    alert = eval_alert(summary)
    assert alert is not None
    title, message = alert
    assert "1 mismatch" in title and "of 2" in title
    assert "behavior-hidden" in message
    assert "got clean" in message


def test_eval_alert_pluralizes_the_count():
    summary = EvalSummary(
        total=4,
        passed=2,
        failures=(_outcome("a", passed=False), _outcome("b", passed=False)),
    )
    alert = eval_alert(summary)
    assert alert is not None
    assert "2 mismatches" in alert[0]


def test_golden_set_is_balanced_unique_and_well_formed():
    assert len(GOLDEN) >= 4
    names = [c.name for c in GOLDEN]
    assert len(names) == len(set(names))  # stable, unique identifiers
    assert any(c.expect_clean for c in GOLDEN)  # has clean cases
    assert any(not c.expect_clean for c in GOLDEN)  # has risky cases
    for case in GOLDEN:
        assert case.changelog.text.strip()  # every fixture feeds real text
        assert case.changelog.package


class _AlwaysClean:
    """A judge that has regressed to waving everything through as clean."""

    async def judge(
        self, changelog: Changelog, loop: Loop = Loop.DEPENDENCY_PATCH
    ) -> ChangelogVerdict:
        return CleanVerdict(rationale="canned clean")


class _GoldenOracle:
    """A judge that returns each golden case's known-right verdict."""

    def __init__(self) -> None:
        self._want = {c.changelog: c.expect_clean for c in GOLDEN}

    async def judge(
        self, changelog: Changelog, loop: Loop = Loop.DEPENDENCY_PATCH
    ) -> ChangelogVerdict:
        if self._want[changelog]:
            return CleanVerdict(rationale="ok")
        return RiskyVerdict(rationale="behavior change")


async def test_evaluate_alerts_when_judge_regresses_to_all_clean(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def _fake_notify(
        settings, *, title, message, tags="", priority="default"
    ):
        sent.append((title, message))
        return True

    monkeypatch.setattr("froot.adapters.ntfy.notify", _fake_notify)
    await _evaluate(judge=_AlwaysClean())

    assert len(sent) == 1
    title, message = sent[0]
    risky = [c.name for c in GOLDEN if not c.expect_clean]
    assert f"{len(risky)} mismatch" in title
    for name in risky:
        assert name in message


async def test_evaluate_stays_silent_when_judge_matches_golden(monkeypatch):
    sent: list[tuple[str, str]] = []

    async def _fake_notify(
        settings, *, title, message, tags="", priority="default"
    ):
        sent.append((title, message))
        return True

    monkeypatch.setattr("froot.adapters.ntfy.notify", _fake_notify)
    await _evaluate(judge=_GoldenOracle())

    assert sent == []
