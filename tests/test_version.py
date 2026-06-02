from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from froot.domain.version import Version
from froot.result import Err, unwrap


def v(text: str) -> Version:
    return unwrap(Version.parse(text))


def test_parse_valid():
    assert v("1.4.2") == Version(major=1, minor=4, patch=2)
    assert v("v2.0.0").major == 2
    assert unwrap(Version.parse("1.0.0-rc.1")).prerelease == "rc.1"
    assert v("1.2.3+build.7").patch == 3  # build metadata ignored


def test_parse_invalid_returns_err():
    assert isinstance(Version.parse("not-a-version"), Err)
    assert isinstance(Version.parse("1.2"), Err)
    assert isinstance(Version.parse(""), Err)


def test_str_roundtrip():
    assert str(v("1.4.2")) == "1.4.2"
    assert str(unwrap(Version.parse("1.0.0-rc.1"))) == "1.0.0-rc.1"


def test_ordering_and_max():
    assert v("1.4.2") < v("1.4.3") < v("1.5.0") < v("2.0.0")
    assert max([v("1.4.1"), v("1.4.7"), v("1.4.3")]) == v("1.4.7")
    assert unwrap(Version.parse("1.0.0-rc.1")) < v("1.0.0")


def test_is_patch_bump_of():
    assert v("1.4.3").is_patch_bump_of(v("1.4.2"))
    assert not v("1.5.0").is_patch_bump_of(v("1.4.2"))  # minor
    assert not v("2.0.0").is_patch_bump_of(v("1.9.9"))  # major
    assert not v("1.4.1").is_patch_bump_of(v("1.4.2"))  # backward
    assert not v("1.4.2").is_patch_bump_of(v("1.4.2"))  # equal
    # a prerelease is never a clean patch bump (either end)
    assert not unwrap(Version.parse("1.4.3-rc.1")).is_patch_bump_of(v("1.4.2"))
    assert not v("1.4.3").is_patch_bump_of(unwrap(Version.parse("1.4.2-rc.1")))


def test_is_stable():
    assert v("1.0.0").is_stable
    assert not unwrap(Version.parse("1.0.0-rc.1")).is_stable


@given(st.integers(0, 50), st.integers(0, 50), st.integers(0, 50))
def test_property_parse_str_roundtrip(major: int, minor: int, patch: int):
    version = Version(major=major, minor=minor, patch=patch)
    assert unwrap(Version.parse(str(version))) == version


@given(st.integers(0, 50), st.integers(0, 50), st.integers(0, 50))
def test_property_next_patch_is_a_bump(major: int, minor: int, patch: int):
    lower = Version(major=major, minor=minor, patch=patch)
    higher = Version(major=major, minor=minor, patch=patch + 1)
    assert higher.is_patch_bump_of(lower)
    assert not lower.is_patch_bump_of(higher)
