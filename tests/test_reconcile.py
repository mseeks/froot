from __future__ import annotations

from froot.policy.reconcile import reconciliations
from tests.support import make_pr, make_upgrade


def test_superseded_pr_is_closed_and_live_one_kept():
    # left-pad: installed 1.4.2, newest patch 1.4.4. The PR at 1.4.3 is stale;
    # the PR at 1.4.4 is the current proposal and must be kept.
    upgrades = (
        make_upgrade("left-pad", current="1.4.2", available=("1.4.3", "1.4.4")),
    )
    stale = make_pr(number=5, branch="froot/dependency-patch/left-pad-1.4.3")
    live = make_pr(number=6, branch="froot/dependency-patch/left-pad-1.4.4")
    closures = reconciliations((stale, live), upgrades)
    assert [c.pr.number for c in closures] == [5]
    assert "1.4.4" in closures[0].comment  # superseding target named


def test_satisfied_pr_is_closed():
    # beta has only a major upgrade available (no patch candidate), and the base
    # already sits at 1.4.3 — a lingering PR targeting 1.4.2 is moot.
    upgrades = (make_upgrade("beta", current="1.4.3", available=("2.0.0",)),)
    pr = make_pr(number=8, branch="froot/dependency-patch/beta-1.4.2")
    closures = reconciliations((pr,), upgrades)
    assert [c.pr.number for c in closures] == [8]
    assert "1.4.3" in closures[0].comment  # installed version named


def test_unmatched_package_left_open():
    # gamma is not in the upgrade set (fully up to date / unknown), so reconcile
    # cannot match its PR to ground truth and deliberately leaves it open.
    upgrades = (
        make_upgrade("left-pad", current="1.4.2", available=("1.4.3",)),
    )
    pr = make_pr(number=9, branch="froot/dependency-patch/gamma-1.0.0")
    assert reconciliations((pr,), upgrades) == ()


def test_non_froot_pr_left_open():
    upgrades = (
        make_upgrade("left-pad", current="1.4.2", available=("1.4.3",)),
    )
    pr = make_pr(number=10, branch="feature/some-human-branch")
    assert reconciliations((pr,), upgrades) == ()


def test_slug_collision_attributes_to_the_right_package():
    # "foo" and "foo-bar" both have prefixes that could match a foo-bar branch;
    # parsing the version tail attributes it to foo-bar (target 2.0.1), so its
    # stale 2.0.0 PR is superseded — never mis-read against foo's 1.0.1.
    upgrades = (
        make_upgrade("foo", current="1.0.0", available=("1.0.1",)),
        make_upgrade("foo-bar", current="2.0.0", available=("2.0.1",)),
    )
    pr = make_pr(number=11, branch="froot/dependency-patch/foo-bar-2.0.0")
    closures = reconciliations((pr,), upgrades)
    assert [c.pr.number for c in closures] == [11]
    assert "2.0.1" in closures[0].comment  # foo-bar's target, not foo's 1.0.1


def test_closures_sorted_by_pr_number():
    upgrades = (
        make_upgrade("a", current="1.0.0", available=("1.0.2",)),
        make_upgrade("b", current="2.0.0", available=("2.0.2",)),
    )
    # Both PRs are superseded (older patch than the current target).
    p_hi = make_pr(number=20, branch="froot/dependency-patch/a-1.0.1")
    p_lo = make_pr(number=4, branch="froot/dependency-patch/b-2.0.1")
    closures = reconciliations((p_hi, p_lo), upgrades)
    assert [c.pr.number for c in closures] == [4, 20]


def test_no_open_prs_is_empty():
    upgrades = (
        make_upgrade("left-pad", current="1.4.2", available=("1.4.3",)),
    )
    assert reconciliations((), upgrades) == ()
