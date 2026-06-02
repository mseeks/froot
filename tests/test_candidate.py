from __future__ import annotations

import pytest
from pydantic import ValidationError

from froot.domain.candidate import AvailableUpgrade, PatchCandidate
from froot.domain.ecosystem import Ecosystem
from tests.support import make_candidate, ver


def test_valid_patch_candidate():
    candidate = make_candidate(current="1.4.2", target="1.4.3")
    assert str(candidate) == "left-pad 1.4.2 -> 1.4.3"


@pytest.mark.parametrize(
    "current,target",
    [
        ("1.4.2", "1.5.0"),  # minor bump
        ("1.9.9", "2.0.0"),  # major bump
        ("1.4.3", "1.4.2"),  # backward
        ("1.4.2", "1.4.2"),  # no change
    ],
)
def test_non_patch_candidate_is_unrepresentable(current: str, target: str):
    with pytest.raises(ValidationError):
        make_candidate(current=current, target=target)


def test_prerelease_target_rejected():
    with pytest.raises(ValidationError):
        PatchCandidate(
            package="x",
            ecosystem=Ecosystem.NPM,
            current=ver("1.4.2"),
            target=ver("1.4.3-rc.1"),
        )


def test_available_upgrade_holds_raw_versions():
    upgrade = AvailableUpgrade(
        package="left-pad",
        ecosystem=Ecosystem.NPM,
        current=ver("1.4.2"),
        available=(ver("1.4.3"), ver("1.5.0")),
    )
    assert upgrade.current == ver("1.4.2")
    assert len(upgrade.available) == 2
