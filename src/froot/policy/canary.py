"""The adversarial-probe policy — does the guardrail still catch a bad bump?

The third trust bearing's stimulus. A *canary* is a deliberately-bad bump
injected on a schedule; a healthy loop must **refuse to merge it** — fail to
apply the bogus version, or open it and let CI go red and close it, but never
land it. This module is the pure half: what a canary bump *is*, how to recognise
one after the fact, and how to score a probe's outcome. The injection
(dispatching the bump) and the schedule are the impure wiring.

Why a probe at all, when the other two bearings already exist (§3.7): the rate
and the post-merge defect rate both need *volume* to mean anything, and froot's
per-class volume is tiny. A probe needs none — one is informative at N=1. So it
is the bearing that carries weight while the rate-based ones accumulate, and the
deliberate-disturbance self-test (§2.11) that catches the guardrail going stale
*before* a real bad bump arrives, not after.

The canary target is a valid semver (froot's strict three-part) that is strictly
newer and stable — so it satisfies the :class:`Candidate` forward-stable
invariant and flows through the *real* loop unchanged — yet one no registry
will ever resolve, so applying it must fail. The crudest badness, caught at the
floor; a subtler installable-but-breaking canary is a later repo-specific
refinement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from froot.domain.candidate import Candidate
from froot.domain.version import Version

if TYPE_CHECKING:
    from froot.domain.ecosystem import Ecosystem

# A version no registry resolves, but a legal forward-stable target so the
# canary rides the ordinary loop (and is recognisable on the PR by this tail).
CANARY_TARGET: Final = Version(major=99, minor=99, patch=99)
CANARY_TARGET_STR: Final = "99.99.99"


def canary_candidate(
    package: str, ecosystem: Ecosystem, current: Version
) -> Candidate:
    """A deliberately-bad bump of ``package`` to the unresolvable sentinel.

    Forward-stable by construction (``99.99.99`` is strictly newer and not a
    prerelease), so it passes :class:`Candidate`'s invariant and the loop treats
    it like any other bump — which is the point: it tests the *real* guardrail.
    """
    return Candidate(
        package=package,
        ecosystem=ecosystem,
        current=current,
        target=CANARY_TARGET,
        justification=(
            "canary: a deliberately-unresolvable bump; a healthy loop must "
            "refuse to merge it (the adversarial probe, §2.11)"
        ),
    )


def is_canary(to_version: str | Version) -> bool:
    """True if a bump's target is the canary sentinel (pure, on PR or domain).

    Accepts the parsed :class:`Version` (the loop side) or the raw target string
    the dashboard reads off the PR title, so both callers recognise a probe.
    """
    if isinstance(to_version, Version):
        return to_version == CANARY_TARGET
    return to_version == CANARY_TARGET_STR


def score_probe(state: str) -> str:
    """Score one canary probe from its PR state — caught / escaped / pending.

    The bar is deliberately strict: a known-bad bump must never *merge*. So a
    canary that ``merged`` **escaped** the guardrail; one that is ``closed`` (CI
    went red and it was closed, or reconcile retired it) — or that never opened
    at all, the registry having refused the bogus version — was **caught**; one
    still ``open`` is **pending**. (An apply-time refusal leaves no PR, so it is
    caught by absence and surfaces in the failures panel, not here.)
    """
    if state == "merged":
        return "escaped"
    if state == "open":
        return "pending"
    return "caught"
