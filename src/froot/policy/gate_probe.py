"""The adversarial gate self-test — would the live gate refuse a bad class?

The acting flip (Phase 4.3c) lets an earned class auto-merge its own clean+green
bumps. Its risk surface is a gate that *grants when it must not* — through a
code regression, or (the insidious one) a production **config** loosening a
steward makes by hand that no CI test ever sees: drop the ``MIN_RATE`` floor or
raise the ``MAX_DEFECT_RATE`` ceiling (the ``FROOT_AUTOMERGE_*`` env) and the
gate quietly starts trusting classes it shouldn't. That is §3.7's "silent
drift": trust comes apart without a single visible failure.

This is the §2.11 deliberate disturbance aimed straight at that surface — the
third trust leg, adversarial probing. A battery of synthetic class histories
that a *healthy* gate must refuse, each engineered to fail a different
threshold, run against the **live** policy. Any scenario the gate would grant is
an escape: the alarm. It needs no volume (informative at N=1, unlike the rate
and defect bearings) and runs every tick, so a loosened gate is caught the
moment config drifts — not after a bad bump has merged.

Pure: scenarios and a policy in, the names that escaped out. The schedule and
the structured alarm are the impure wiring (the scan tick + the activity log).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from froot.domain.base import Frozen
from froot.policy.autonomy import class_earned

if TYPE_CHECKING:
    from froot.policy.autonomy import AutonomyPolicy


class GateScenario(Frozen):
    """One synthetic class history a healthy gate must never auto-merge-grant.

    The same shape :func:`~froot.policy.autonomy.class_earned` reads — a class's
    windowed record — so the probe exercises the *real* gate, not a model of it.

    Attributes:
        name: What makes this history untrustworthy (the threshold it probes).
        decided: PRs decided in the window.
        merged: How many were merged (the rate's numerator).
        determined: Merges with a confirmed post-merge outcome.
        defects: Of those, how many broke or were reverted.
    """

    name: str
    decided: int
    merged: int
    determined: int
    defects: int


# The battery. Each scenario clears every threshold *but one*, so each guards a
# distinct knob against being loosened: evidence, rate, confirmation, defects.
KNOWN_BAD: Final[tuple[GateScenario, ...]] = (
    # No record at all — the cold-start floor (zero evidence).
    GateScenario(
        name="no record", decided=0, merged=0, determined=0, defects=0
    ),
    # A perfect but thin record — a 100% rate on too few PRs is not a record.
    GateScenario(
        name="thin record", decided=1, merged=1, determined=1, defects=0
    ),
    # Plenty of volume, but the steward rejects half — a poor track record.
    GateScenario(
        name="low approval rate",
        decided=20,
        merged=10,
        determined=10,
        defects=0,
    ),
    # A spotless rate, but almost no merge has a *confirmed* outcome yet — the
    # defect bearing has no evidence behind it.
    GateScenario(
        name="unconfirmed merges",
        decided=20,
        merged=20,
        determined=1,
        defects=0,
    ),
    # Everything clears except reality: one confirmed merge broke or reverted.
    GateScenario(
        name="a defect on record",
        decided=20,
        merged=20,
        determined=10,
        defects=1,
    ),
)


def gate_escapes(policy: AutonomyPolicy) -> tuple[str, ...]:
    """Names of known-bad scenarios the live gate would *wrongly* grant.

    Empty is healthy: every deliberately-bad class is refused. Non-empty is the
    alarm — the gate has loosened (in code or, more likely, in config) enough to
    trust a class it must not. Pure over the supplied policy.
    """
    return tuple(
        s.name
        for s in KNOWN_BAD
        if class_earned(
            decided=s.decided,
            merged=s.merged,
            determined=s.determined,
            defects=s.defects,
            policy=policy,
        )[0]
    )
