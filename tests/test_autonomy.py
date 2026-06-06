from __future__ import annotations

from froot.policy.autonomy import (
    AutonomyPolicy,
    class_earned,
    pr_autonomy,
)

REPO = "mseeks/revisionist"


def _policy(**overrides: object) -> AutonomyPolicy:
    base = {
        "min_rate": 0.95,
        "min_decided": 5,
        "window_days": 90,
        "allowlisted_repos": frozenset({REPO}),
    }
    base.update(overrides)
    return AutonomyPolicy(**base)  # type: ignore[arg-type]


# ── class_earned ─────────────────────────────────────────────────────────────
def test_class_not_earned_below_min_decided():
    earned, blocker = class_earned(2, 2, _policy())
    assert earned is False
    assert blocker == "only 2/5 decided recently"


def test_class_not_earned_below_min_rate():
    # 4 of 6 merged = 67% < 95%
    earned, blocker = class_earned(6, 4, _policy())
    assert earned is False
    assert blocker is not None
    assert "approval rate" in blocker
    assert "67%" in blocker


def test_class_earned_when_rate_and_count_clear():
    earned, blocker = class_earned(8, 8, _policy())
    assert earned is True
    assert blocker is None


def test_class_earned_exactly_at_thresholds():
    # min_decided met exactly, rate exactly at the bar (1.0 >= 0.95).
    earned, blocker = class_earned(5, 5, _policy())
    assert earned is True
    assert blocker is None


def test_class_earned_handles_zero_decided_without_dividing():
    # A degenerate min_decided=0 must not fall through to 0/0; an empty class
    # is simply not earned (every configured class is evaluated, incl. empty).
    earned, blocker = class_earned(0, 0, _policy(min_decided=0))
    assert earned is False
    assert blocker == "only 0/0 decided recently"


# ── pr_autonomy: the conditions, in trust order ──────────────────────────────
def test_pr_held_when_repo_not_allowlisted():
    v = pr_autonomy(
        repo="other/repo",
        verdict="clean",
        ci="passed",
        earned=True,
        blocker=None,
        policy=_policy(),
    )
    assert v.would_merge is False
    assert v.reason == "auto-merge not enabled for this repo"


def test_pr_held_when_class_not_earned():
    v = pr_autonomy(
        repo=REPO,
        verdict="clean",
        ci="passed",
        earned=False,
        blocker="only 2/5 decided recently",
        policy=_policy(),
    )
    assert v.would_merge is False
    assert "class not earned" in v.reason
    assert "2/5" in v.reason


def test_pr_held_when_verdict_not_clean():
    v = pr_autonomy(
        repo=REPO,
        verdict="risky",
        ci="passed",
        earned=True,
        blocker=None,
        policy=_policy(),
    )
    assert v.would_merge is False
    assert v.reason == "verdict is risky"


def test_pr_held_when_verdict_unknown_reads_unknown():
    v = pr_autonomy(
        repo=REPO,
        verdict=None,
        ci="passed",
        earned=True,
        blocker=None,
        policy=_policy(),
    )
    assert v.would_merge is False
    assert v.reason == "verdict is unknown"


def test_pr_held_when_ci_not_passed():
    v = pr_autonomy(
        repo=REPO,
        verdict="clean",
        ci="failed",
        earned=True,
        blocker=None,
        policy=_policy(),
    )
    assert v.would_merge is False
    assert v.reason == "CI failed"


def test_pr_held_when_ci_pending_reads_pending():
    v = pr_autonomy(
        repo=REPO,
        verdict="clean",
        ci=None,
        earned=True,
        blocker=None,
        policy=_policy(),
    )
    assert v.would_merge is False
    assert v.reason == "CI pending"


def test_pr_would_merge_when_every_condition_met():
    v = pr_autonomy(
        repo=REPO,
        verdict="clean",
        ci="passed",
        earned=True,
        blocker=None,
        policy=_policy(),
    )
    assert v.would_merge is True
    assert "clean" in v.reason and "earned" in v.reason


def test_substantive_blocker_reported_before_allowlist_switch():
    # A non-allowlisted, un-earned PR surfaces the substantive blocker (the
    # thing to fix), NOT the steward's own switch — that switch is reported
    # last, only once a PR is otherwise fully ready. This keeps the shadow
    # gate watchable in its default, allowlist-off state.
    v = pr_autonomy(
        repo="other/repo",
        verdict="clean",
        ci="passed",
        earned=False,
        blocker="only 1/5 decided recently",
        policy=_policy(),
    )
    assert v.would_merge is False
    assert "class not earned" in v.reason


def test_allowlist_reason_appears_only_when_otherwise_ready():
    # Earned + clean + green, but the repo is not allowlisted: now the bare
    # switch reason shows, because flipping it is the only thing left.
    v = pr_autonomy(
        repo="other/repo",
        verdict="clean",
        ci="passed",
        earned=True,
        blocker=None,
        policy=_policy(),
    )
    assert v.would_merge is False
    assert v.reason == "auto-merge not enabled for this repo"


def test_empty_allowlist_holds_everything_by_default():
    v = pr_autonomy(
        repo=REPO,
        verdict="clean",
        ci="passed",
        earned=True,
        blocker=None,
        policy=AutonomyPolicy(),  # default: empty allowlist
    )
    assert v.would_merge is False
    assert v.reason == "auto-merge not enabled for this repo"
