from __future__ import annotations

from froot.domain.ecosystem import Ecosystem
from froot.policy.candidates import select_security_candidates
from tests.support import make_advisory, make_installed, ver


def test_partial_fix_is_proposed_and_says_others_remain():
    # One advisory is fixable (1.4.3), one has no fix; froot still proposes the
    # bump (it reduces the surface) but the justification must not imply it
    # clears the unfixable one.
    installed = (make_installed("left-pad", "1.4.2"),)
    advisories = (
        make_advisory("left-pad", "GHSA-fix", ranges=(("0", "1.4.3"),)),
        make_advisory("left-pad", "GHSA-nofix", ranges=(("0", None),)),
    )
    (candidate,) = select_security_candidates(installed, advisories)
    assert candidate.target == ver("1.4.3")
    assert candidate.justification is not None
    assert "GHSA-fix" in candidate.justification
    assert "GHSA-nofix" not in candidate.justification
    assert "no usable fix" in candidate.justification


def test_uv_ecosystem_security_candidate():
    installed = (make_installed("jinja2", "2.10.0", ecosystem=Ecosystem.UV),)
    advisories = (
        make_advisory(
            "jinja2",
            "GHSA-py",
            ranges=(("0", "2.10.1"),),
            ecosystem=Ecosystem.UV,
        ),
    )
    (candidate,) = select_security_candidates(installed, advisories)
    assert candidate.ecosystem is Ecosystem.UV
    assert candidate.target == ver("2.10.1")


def test_unparseable_introduced_bound_is_not_a_candidate():
    # A lower bound that doesn't parse can't be reasoned about, so the range
    # never matches and froot proposes nothing (conservative).
    installed = (make_installed("left-pad", "1.4.2"),)
    advisories = (
        make_advisory("left-pad", "GHSA-bad", ranges=(("garbage", "1.4.3"),)),
    )
    assert select_security_candidates(installed, advisories) == ()


def test_single_advisory_targets_its_fix():
    installed = (make_installed("left-pad", "1.4.2"),)
    advisories = (
        make_advisory("left-pad", "GHSA-1", ranges=(("0", "1.4.3"),)),
    )
    (candidate,) = select_security_candidates(installed, advisories)
    assert candidate.package == "left-pad"
    assert candidate.current == ver("1.4.2")
    assert candidate.target == ver("1.4.3")
    assert candidate.justification is not None
    assert "GHSA-1" in candidate.justification


def test_max_of_fixes_clears_all_advisories():
    # Two advisories on one package fixed in 1.4.3 and 1.5.0; the bump reaches
    # the higher one to clear both.
    installed = (make_installed("left-pad", "1.4.2"),)
    advisories = (
        make_advisory("left-pad", "GHSA-1", ranges=(("0", "1.4.3"),)),
        make_advisory("left-pad", "GHSA-2", ranges=(("0", "1.5.0"),)),
    )
    (candidate,) = select_security_candidates(installed, advisories)
    assert candidate.target == ver("1.5.0")
    assert candidate.justification is not None
    assert "GHSA-1" in candidate.justification
    assert "GHSA-2" in candidate.justification


def test_picks_the_range_holding_the_installed_version():
    # minimist-style: vulnerable in [0, 0.2.1) and [1.0.0, 1.2.3); 1.2.0 is in
    # the second branch, so the fix is 1.2.3, not 0.2.1.
    installed = (make_installed("minimist", "1.2.0"),)
    advisories = (
        make_advisory(
            "minimist", "GHSA-x", ranges=(("0", "0.2.1"), ("1.0.0", "1.2.3"))
        ),
    )
    (candidate,) = select_security_candidates(installed, advisories)
    assert candidate.target == ver("1.2.3")


def test_advisory_with_no_fix_is_dropped():
    installed = (make_installed("left-pad", "1.4.2"),)
    advisories = (
        make_advisory("left-pad", "GHSA-nofix", ranges=(("0", None),)),
    )
    assert select_security_candidates(installed, advisories) == ()


def test_fix_at_or_below_installed_is_not_a_candidate():
    # The installed version is already past the fix → no range holds it → drop.
    installed = (make_installed("left-pad", "1.4.2"),)
    advisories = (
        make_advisory("left-pad", "GHSA-old", ranges=(("0", "1.4.0"),)),
    )
    assert select_security_candidates(installed, advisories) == ()


def test_package_without_advisories_yields_nothing():
    installed = (make_installed("left-pad", "1.4.2"),)
    assert select_security_candidates(installed, ()) == ()


def test_aliases_named_in_justification_and_sorted_by_package():
    installed = (
        make_installed("zeta", "1.0.0"),
        make_installed("alpha", "2.0.0"),
    )
    advisories = (
        make_advisory(
            "zeta", "GHSA-z", ranges=(("0", "1.0.1"),), aliases=("CVE-9",)
        ),
        make_advisory("alpha", "GHSA-a", ranges=(("0", "2.0.1"),)),
    )
    candidates = select_security_candidates(installed, advisories)
    assert [c.package for c in candidates] == ["alpha", "zeta"]
    assert candidates[1].justification is not None
    assert "CVE-9" in candidates[1].justification
