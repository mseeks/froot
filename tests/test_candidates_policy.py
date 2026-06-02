from __future__ import annotations

from froot.domain.candidate import AvailableUpgrade
from froot.domain.ecosystem import Ecosystem
from froot.policy.candidates import select_patch_candidates
from tests.support import ver


def _upgrade(package: str, current: str, *available: str) -> AvailableUpgrade:
    return AvailableUpgrade(
        package=package,
        ecosystem=Ecosystem.NPM,
        current=ver(current),
        available=tuple(ver(a) for a in available),
    )


def test_selects_highest_patch():
    upgrade = _upgrade("left-pad", "1.4.2", "1.4.1", "1.4.3", "1.4.7", "1.5.0")
    (candidate,) = select_patch_candidates([upgrade])
    assert candidate.target == ver("1.4.7")


def test_drops_packages_with_no_patch_upgrade():
    upgrade = _upgrade("x", "1.4.2", "1.5.0", "2.0.0")
    assert select_patch_candidates([upgrade]) == ()


def test_sorted_by_package_and_one_per_dependency():
    upgrades = [
        _upgrade("zeta", "1.0.0", "1.0.1"),
        _upgrade("alpha", "2.3.4", "2.3.5", "2.3.9"),
    ]
    result = select_patch_candidates(upgrades)
    assert [c.package for c in result] == ["alpha", "zeta"]
    assert result[0].target == ver("2.3.9")


def test_empty_input():
    assert select_patch_candidates([]) == ()
