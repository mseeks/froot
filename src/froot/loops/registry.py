"""The loop registry: froot's open loop catalog, keyed by :class:`Loop`.

The chassis schedules, dispatches, verifies, and gates; a :class:`LoopSpec` is a
shared core (the loop key, the dashboard icon) plus a disposition-tagged
*tail* — a :class:`CommitTail` (an acting loop's signal→candidate ``observe``,
PR-title verb, changelog framing, reconcile trait) or an :class:`AdvisoryTail`
(an advisory loop's comment marker and dashboard title). The tail's TYPE is the
discriminant, so :attr:`LoopSpec.disposition` is derived, never stored beside
inert fields of the other family. Everything else (the scan/dispatch chassis,
the merge gate, earned autonomy, the dashboard, the workflow-id namespace) is
loop-agnostic and stays in the spine.

This cut registers the three acting (CommitTail) loops; the advisory loops fold
in behind :class:`AdvisoryTail` next.

Loops self-register at import. The registry is populated lazily on first read
(see :func:`_ensure`) so importing a consumer never forces a particular import
order, and the per-loop adapter imports stay inside each ``observe`` body.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path

    from froot.domain.loop import Loop
    from froot.domain.repo import TargetRepo
    from froot.domain.work import WorkItem
    from froot.ports.protocols import PackageManager

    # Check out a repo's manifest and select this loop's work items, returning
    # (considered, items) — ``considered`` is the upstream signal size, so the
    # scan tick can show how much was seen versus kept.
    ObserveFn = Callable[
        [TargetRepo, PackageManager, Path],
        Awaitable[tuple[int, tuple[WorkItem, ...]]],
    ]


class Disposition(StrEnum):
    """How a loop's work item terminates (the commit-vs-emit fork)."""

    # Propose a PR; the spine gates the merge (the acting loops).
    COMMIT_OR_REVERT = "commit-or-revert"
    # Upsert a decaying advisory comment/label; no merge, no gate (advisory).
    EMIT_SIGNAL = "emit-signal"


@dataclass(frozen=True)
class CommitTail:
    """The COMMIT_OR_REVERT per-loop seams (an acting loop that opens a PR).

    Attributes:
        observe: The signal→candidate seam — the one genuinely per-loop body.
        title_prefix: The PR-title verb (``deps`` / ``security`` /
            ``dead-code``) — a per-loop label, not derivable from the loop name.
        judge_context: The framing line for the in-loop changelog judge, or
            ``None`` when the loop does no changelog judging (e.g. dead-code,
            whose judgment is a safe-to-remove veto *at the signal*).
        reconciles: Whether version-supersession reconcile applies — ``True``
            for bump loops, ``False`` for a removal (no version to overtake).
    """

    observe: ObserveFn
    title_prefix: str
    judge_context: str | None = None
    reconciles: bool = True


@dataclass(frozen=True)
class AdvisoryTail:
    """The EMIT_SIGNAL per-loop seams (an advisory loop that comments on PRs).

    An advisory loop scans a repo's open PRs and upserts one decaying comment
    per PR — no candidate, no PR of its own, no gate, no merge.

    Attributes:
        marker: The HTML-comment marker that finds this loop's single per-PR
            comment (the upsert/decay key, also the dashboard's query key).
        panel_title: The dashboard tab/panel title (e.g. "Determinism review").
    """

    marker: str
    panel_title: str


@dataclass(frozen=True)
class LoopSpec:
    """One loop's entry — a shared core plus a disposition-tagged tail.

    The tail's TYPE is the discriminant: a :class:`CommitTail` is an acting
    (commit-or-revert) loop, an :class:`AdvisoryTail` is an emit-signal loop. No
    spec ever carries an inert ``observe`` beside an inert ``marker`` — the
    family machinery lives behind the tail, not beside it.

    Attributes:
        loop: The loop this spec specialises (the registry key).
        dashboard_icon: The icon key for this loop's dashboard tab (one of the
            renderer's ``_ICONS``) — shared by both families.
        tail: The per-loop seams for this loop's family (commit vs advisory).

    The workflow-id/branch namespace segment is NOT carried here: it is a pure
    derivation in :mod:`froot.policy.naming`.
    """

    loop: Loop
    dashboard_icon: str
    tail: CommitTail | AdvisoryTail

    @property
    def disposition(self) -> Disposition:
        """The family, derived from the tail's type (one conceptual field)."""
        return (
            Disposition.COMMIT_OR_REVERT
            if isinstance(self.tail, CommitTail)
            else Disposition.EMIT_SIGNAL
        )


_LOOPS: dict[Loop, LoopSpec] = {}
_REGISTERED = False


def register(spec: LoopSpec) -> None:
    """Register a loop spec (idempotent on re-import; last write wins)."""
    _LOOPS[spec.loop] = spec


def _ensure() -> None:
    """Import the loop modules once so they self-register (lazy, idempotent)."""
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True
    # Importing each module runs its module-level register(...) call. Kept here,
    # not at package import, so the registry has no import-order constraints.
    from froot.loops import (  # noqa: F401
        dead_code,
        dependency_patch,
        security_patch,
    )


def get(loop: Loop) -> LoopSpec:
    """The registered spec for a loop (raises ``KeyError`` if unregistered)."""
    _ensure()
    return _LOOPS[loop]


def commit_tail(loop: Loop) -> CommitTail:
    """The :class:`CommitTail` of an acting loop (asserts it is one).

    The acting spine reads its per-loop seams (observe / title / judge /
    reconcile) through this, so a non-commit loop reaching an acting code path
    fails loudly instead of returning a half-typed tail.
    """
    tail = get(loop).tail
    if not isinstance(tail, CommitTail):
        msg = f"{loop} is not a commit-or-revert loop"
        raise TypeError(msg)
    return tail


def all_specs() -> tuple[LoopSpec, ...]:
    """Every registered loop spec, in registration order."""
    _ensure()
    return tuple(_LOOPS.values())
