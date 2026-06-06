from __future__ import annotations

from froot.domain.loop import Loop
from froot.policy.reconcile import reconciliations
from tests.support import make_candidate, make_pr


def test_superseded_pr_is_closed_and_live_one_kept():
    # left-pad's current target is 1.4.4; the PR at 1.4.3 is stale, the PR at
    # 1.4.4 is the live one and must be kept.
    candidates = (make_candidate("left-pad", current="1.4.2", target="1.4.4"),)
    stale = make_pr(number=5, branch="froot/dependency-patch/left-pad-1.4.3")
    live = make_pr(number=6, branch="froot/dependency-patch/left-pad-1.4.4")
    closures = reconciliations((stale, live), candidates)
    assert [c.pr.number for c in closures] == [5]
    assert "1.4.4" in closures[0].comment  # the superseding target named


def test_no_candidate_for_package_leaves_pr_open():
    # No current candidate matches the PR's package, so reconcile can't map
    # it to ground truth and deliberately leaves it open.
    pr = make_pr(number=9, branch="froot/dependency-patch/gamma-1.0.0")
    assert reconciliations((pr,), ()) == ()


def test_non_froot_pr_left_open():
    candidates = (make_candidate("left-pad", current="1.4.2", target="1.4.3"),)
    pr = make_pr(number=10, branch="feature/some-human-branch")
    assert reconciliations((pr,), candidates) == ()


def test_slug_collision_attributes_to_the_right_package():
    # "foo" and "foo-bar" both have prefixes that could match a foo-bar branch;
    # parsing the version tail attributes it to foo-bar (target 2.0.1).
    candidates = (
        make_candidate("foo", current="1.0.0", target="1.0.1"),
        make_candidate("foo-bar", current="2.0.0", target="2.0.1"),
    )
    pr = make_pr(number=11, branch="froot/dependency-patch/foo-bar-2.0.0")
    closures = reconciliations((pr,), candidates)
    assert [c.pr.number for c in closures] == [11]
    assert "2.0.1" in closures[0].comment  # foo-bar's target, not foo's 1.0.1


def test_reconcile_is_scoped_to_its_own_loop():
    # The dependency-patch reconcile must not touch a security PR, even for
    # the same package and version — the branch namespace keeps them apart.
    candidates = (make_candidate("left-pad", current="1.4.2", target="1.4.4"),)
    dep_pr = make_pr(number=1, branch="froot/dependency-patch/left-pad-1.4.3")
    sec_pr = make_pr(number=2, branch="froot/security-patch/left-pad-1.4.3")
    closures = reconciliations(
        (dep_pr, sec_pr), candidates, Loop.DEPENDENCY_PATCH
    )
    assert [c.pr.number for c in closures] == [1]


def test_closures_sorted_by_pr_number():
    candidates = (
        make_candidate("a", current="1.0.0", target="1.0.2"),
        make_candidate("b", current="2.0.0", target="2.0.2"),
    )
    p_hi = make_pr(number=20, branch="froot/dependency-patch/a-1.0.1")
    p_lo = make_pr(number=4, branch="froot/dependency-patch/b-2.0.1")
    closures = reconciliations((p_hi, p_lo), candidates)
    assert [c.pr.number for c in closures] == [4, 20]


def test_no_open_prs_is_empty():
    candidates = (make_candidate("left-pad", current="1.4.2", target="1.4.3"),)
    assert reconciliations((), candidates) == ()
