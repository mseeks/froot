from __future__ import annotations

from froot.domain.candidate import Candidate
from froot.domain.ecosystem import Ecosystem
from froot.domain.version import Version
from froot.policy.canary import (
    CANARY_TARGET,
    CANARY_TARGET_STR,
    canary_candidate,
    is_canary,
    score_probe,
)


def _v(text: str) -> Version:
    major, minor, patch = (int(p) for p in text.split("."))
    return Version(major=major, minor=minor, patch=patch)


def test_canary_candidate_targets_the_sentinel_and_is_forward_stable():
    # The whole point: it must be a *legal* Candidate (forward-stable), so it
    # rides the ordinary loop — yet target a version no registry resolves.
    c = canary_candidate("left-pad", Ecosystem.NPM, _v("1.2.3"))
    assert isinstance(c, Candidate)
    assert c.target == CANARY_TARGET
    assert c.current == _v("1.2.3")
    assert c.justification is not None and "canary" in c.justification


def test_canary_candidate_constructs_for_a_high_current_too():
    # Sentinel 99.99.99 stays strictly-newer than ordinary currents.
    c = canary_candidate("nuxt", Ecosystem.NPM, _v("3.21.7"))
    assert c.target == CANARY_TARGET


def test_is_canary_recognises_both_version_and_string_forms():
    assert is_canary(CANARY_TARGET) is True
    assert is_canary(CANARY_TARGET_STR) is True
    assert is_canary("99.99.99") is True
    # ordinary bumps are not canaries
    assert is_canary(_v("1.0.1")) is False
    assert is_canary("1.0.1") is False
    assert is_canary("3.2.6") is False


def test_score_probe_merged_is_escaped():
    # A known-bad bump must never merge; if it did, the guardrail failed.
    assert score_probe("merged") == "escaped"


def test_score_probe_closed_is_caught():
    # Opened then closed (CI red -> close, or reconcile) — the guardrail held.
    assert score_probe("closed") == "caught"


def test_score_probe_open_is_pending():
    assert score_probe("open") == "pending"


def test_score_probe_unknown_state_defaults_to_caught():
    # Any non-merged, non-open state is a non-landing — caught (conservative).
    assert score_probe("anything-else") == "caught"
