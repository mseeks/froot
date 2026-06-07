"""The earned-autonomy policy — the gate's logic, now load-bearing.

The pure logic that says, per the Many Hands Engineering trust economy
(§3.6-3.7), whether a *class* of work (a loop, on a repo) has earned its gate
move, and whether a given PR auto-merges under that grant. The acting gate
(Phase 4) reuses these same functions: on an **allowlisted** repo, a class that
clears them has its clean+green bumps merged by the loop itself. Everywhere else
— the default, the allowlist empty — the very same verdict stays advisory and
the dashboard renders it as the *shadow gate* a steward watches before opting a
repo in. Pure throughout; nothing here mutates anything (the merge is an effect
the spine runs only once every condition, allowlist included, is met).

The grant has MHE's five properties. **Earned**: a class earns its gate by a
track record — a high enough *approval rate* over enough *decided* PRs.
**Narrow**: the class is one loop on one repo; dependency-patch and
security-patch are separate trust classes (§3.9), never sharing a record.
**Conditional**: a PR rides the grant only if its own changelog read clean and
its CI went green. **Revocable**: the grant is gated behind an explicit
per-repo allowlist a steward controls, and lapses on its own when the rate
falls. **Expiring**: the rate is measured over a recent window, not all of
history (§2.11) — a class that has not acted lately starts from a lower
baseline.

MHE is blunt that the approval rate is the headline, *not the whole truth* —
"track record alone can lie" (§3.7). So the gate triangulates it (§3.8): a class
earns only when the rate **and** the post-merge **defect rate** both clear,
each with enough evidence behind it — two bearings that fail independently and
cannot both lie at once. Two further legs MHE names — *sampled deep review* and
*adversarial probing* — strengthen the triangle and arrive in later slices; the
*environment*-reset (a judge-model swap or refactor resets the record, §3.7's
fuller "conditional") rides alongside them.
"""

from __future__ import annotations

from froot.domain.base import Frozen


class AutonomyPolicy(Frozen):
    """The thresholds a class must clear to earn its gate move.

    Attributes:
        min_rate: The approval (merge) rate a class needs over the window —
            the first bearing (track record). High alone is a *smell*, not
            proof (a 95% gate "is rubber-stamping", §2.10), so it never earns
            the gate by itself.
        min_decided: How many PRs must have been decided in the window before
            the rate means anything — a 100% rate on one PR is not a record.
        window_days: The look-back window; trust is recent, not lifetime.
        min_determined: How many merges must have a *confirmed* post-merge
            outcome (held / broke / reverted) before the defect bearing counts
            — the rate can lie, so the outcome bearing needs evidence too
            (§3.7). Until then the class is not earned.
        max_defect_rate: The ceiling on the post-merge defect rate — the second,
            independent bearing (§3.8: a target needs ≥2 metrics that gaming
            would harm). Zero by default: one confirmed merge that broke or was
            reverted blocks the gate until it ages out of the window.
        allowlisted_repos: The repos a steward has opted into auto-merge for.
            Empty by default — the revocable switch, off until trust is granted.
    """

    min_rate: float = 0.95
    min_decided: int = 5
    window_days: int = 90
    min_determined: int = 3
    max_defect_rate: float = 0.0
    allowlisted_repos: frozenset[str] = frozenset()


class AutonomyVerdict(Frozen):
    """Whether a PR would auto-merge under the grant, and the reason either way.

    Attributes:
        would_merge: True iff every condition is met, the allowlist included —
        so on an allowlisted repo this is the loop's actual merge decision,
        and elsewhere (the default) the advisory shadow-gate verdict.
        reason: The deciding factor — the grant met, or the first blocker.
    """

    would_merge: bool
    reason: str


def class_earned(
    *,
    decided: int,
    merged: int,
    determined: int,
    defects: int,
    policy: AutonomyPolicy,
) -> tuple[bool, str | None]:
    """Whether a class has earned its gate move, and why not if it hasn't.

    Triangulates two *independent* bearings (§3.8): the approval **rate** (did
    the steward say yes) and the post-merge **defect rate** (did reality punish
    the merge). They fail differently — the rate to rubber-stamping, the defect
    rate to a weak oracle — so a class earns only when both clear *and* there is
    enough evidence behind each. Checks run cheapest-first, and the first to
    fail is the blocker, so the reason is the thing to fix.

    Args:
        decided: PRs of this class decided (merged or closed) in the window.
        merged: How many of those were merged.
        determined: Merges with a confirmed post-merge outcome in the window
            (held / broke / reverted) — the defect bearing's evidence.
        defects: Of those, how many broke the branch or were reverted.
        policy: The thresholds.

    Returns:
        ``(earned, blocker)`` — ``blocker`` is ``None`` when earned, else the
        short reason the gate has not moved.
    """
    if decided < policy.min_decided or decided == 0:
        return False, f"only {decided}/{policy.min_decided} decided recently"
    rate = merged / decided
    if rate < policy.min_rate:
        return False, (f"approval rate {rate:.0%} < {policy.min_rate:.0%}")
    if determined < policy.min_determined:
        return False, (
            f"only {determined}/{policy.min_determined} merges confirmed held"
        )
    defect_rate = defects / determined
    if defect_rate > policy.max_defect_rate:
        return False, (
            f"defect rate {defect_rate:.0%} > {policy.max_defect_rate:.0%}"
        )
    return True, None


def pr_autonomy(
    *,
    repo: str,
    verdict: str | None,
    ci: str | None,
    earned: bool,
    blocker: str | None,
    policy: AutonomyPolicy,
) -> AutonomyVerdict:
    """Whether one open PR would auto-merge under its class's grant.

    Reports the *substantive* blockers first — the earned grant, then this PR's
    own clean-and-green conditions — and the steward's own revocable switch
    (the allowlist) *last*. That ordering is what makes the shadow gate
    watchable in its default, allowlist-off state: a held PR shows the real
    thing to fix (``CI pending`` / ``class not earned``), and the bare
    ``auto-merge not enabled`` reason appears only once a PR is otherwise fully
    ready — i.e. exactly when flipping the switch would change the outcome.
    ``would_merge`` still requires *every* condition, the allowlist included.
    """
    if not earned:
        return AutonomyVerdict(
            would_merge=False, reason=f"class not earned ({blocker})"
        )
    if verdict != "clean":
        return AutonomyVerdict(
            would_merge=False, reason=f"verdict is {verdict or 'unknown'}"
        )
    if ci != "passed":
        return AutonomyVerdict(
            would_merge=False, reason=f"CI {ci or 'pending'}"
        )
    if repo not in policy.allowlisted_repos:
        return AutonomyVerdict(
            would_merge=False, reason="auto-merge not enabled for this repo"
        )
    return AutonomyVerdict(
        would_merge=True, reason="clean + green on an earned class"
    )
