"""The adversarial gate self-test — known-bad classes must never be granted."""

from __future__ import annotations

from froot.policy.autonomy import AutonomyPolicy
from froot.policy.gate_probe import KNOWN_BAD, gate_escapes


def test_default_policy_refuses_every_known_bad_class():
    # The healthy state: the live gate (default thresholds) grants none of the
    # deliberately-bad scenarios, so nothing escapes.
    assert gate_escapes(AutonomyPolicy()) == ()


def test_each_scenario_probes_a_distinct_threshold():
    # Each known-bad history is bad for its own reason — no duplicates — so each
    # guards a different knob against being loosened.
    names = [s.name for s in KNOWN_BAD]
    assert len(names) == len(set(names))
    assert len(names) >= 4


def test_a_loosened_defect_ceiling_lets_the_defect_class_escape():
    # Raise the defect ceiling to allow any defect rate: the "a defect on
    # record" class — clean on every other bearing — now slips through. This is
    # the config-drift the probe exists to catch.
    loosened = AutonomyPolicy(max_defect_rate=1.0)
    assert "a defect on record" in gate_escapes(loosened)


def test_a_dropped_rate_floor_lets_the_low_rate_class_escape():
    # Drop the approval-rate floor and the evidence/confirmation minimums: the
    # "low approval rate" class (a spotless defect record) is now trusted.
    loosened = AutonomyPolicy(
        min_rate=0.0, min_decided=1, min_determined=1, max_defect_rate=0.0
    )
    assert "low approval rate" in gate_escapes(loosened)


def test_a_fully_open_gate_lets_everything_with_evidence_escape():
    # The worst drift — every threshold off. Every scenario that has *any*
    # decided PR escapes; only the literal empty record (no evidence at all) is
    # still refused, because a rate over zero PRs is undefined.
    wide_open = AutonomyPolicy(
        min_rate=0.0,
        min_decided=0,
        min_determined=0,
        max_defect_rate=1.0,
    )
    escaped = gate_escapes(wide_open)
    assert "no record" not in escaped
    assert set(escaped) == {s.name for s in KNOWN_BAD if s.decided > 0}
