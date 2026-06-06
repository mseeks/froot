"""The earned-autonomy policy — read-only today, the gate's logic tomorrow.

froot is record-only: every PR is human-approved. This is the pure logic that
says, per the Many Hands Engineering trust economy (§3.6-3.7), whether a *class*
of work (a loop, on a repo) has earned its gate move, and whether a given PR
*would* auto-merge under that grant. Today the dashboard renders the verdict
and nothing acts on it — the "shadow gate", the dry run that lets a steward
watch the decision for weeks before granting authority. Phase 4 flips it to
action by reusing these same functions; nothing here mutates anything.

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

A caveat MHE is blunt about: the approval rate is the headline, *not the whole
truth* — "track record alone can lie" (§3.7). A real grant triangulates it with
post-merge rollback rate and sampled review, and resets when the *environment*
it was earned in changes (a judge-model swap, a refactor) — MHE's fuller sense
of "conditional". Those are deliberately not here yet, which is exactly why
this stays advisory.
"""

from __future__ import annotations

from froot.domain.base import Frozen


class AutonomyPolicy(Frozen):
    """The thresholds a class must clear to earn its gate move (advisory).

    Attributes:
        min_rate: The approval (merge) rate a class needs over the window.
        min_decided: How many PRs must have been decided in the window before
            the rate means anything — a 100% rate on one PR is not a record.
        window_days: The look-back window; trust is recent, not lifetime.
        allowlisted_repos: The repos a steward has opted into auto-merge for.
            Empty by default — the revocable switch, off until trust is granted.
    """

    min_rate: float = 0.95
    min_decided: int = 5
    window_days: int = 90
    allowlisted_repos: frozenset[str] = frozenset()


class AutonomyVerdict(Frozen):
    """Whether a PR would auto-merge under the grant, and the reason either way.

    Attributes:
        would_merge: True iff every condition is met (advisory — nothing acts).
        reason: The deciding factor — the grant met, or the first blocker.
    """

    would_merge: bool
    reason: str


def class_earned(
    decided: int, merged: int, policy: AutonomyPolicy
) -> tuple[bool, str | None]:
    """Whether a class has earned its gate move, and why not if it hasn't.

    Args:
        decided: PRs of this class decided (merged or closed) in the window.
        merged: How many of those were merged.
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
