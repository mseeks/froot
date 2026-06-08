"""The loop registry: froot's open loop catalog, keyed by :class:`Loop`.

The chassis schedules, dispatches, verifies, and gates; a :class:`LoopSpec`
fills only the genuinely per-loop seams — the signal→candidate ``observe``
function, the changelog-judge framing line (when the loop judges changelogs as
an in-loop effect), and the workflow-id namespace segment. Everything else (the
scan/dispatch chassis, the merge gate, earned autonomy, the dashboard) is
loop-agnostic and stays in the spine.

A loop's *disposition* declares how its work item terminates — COMMIT_OR_REVERT
(propose a PR; the spine gates the merge) or EMIT_SIGNAL (upsert a decaying
advisory; no merge, no gate). The commit machinery keys on that field. This cut
registers the three acting (COMMIT_OR_REVERT) loops; the advisory loops fold in
behind the same field later.

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
    """How a loop's work item terminates (the gate machinery keys on it)."""

    # Propose a PR; the spine gates the merge (the acting loops).
    COMMIT_OR_REVERT = "commit-or-revert"
    # Upsert a decaying advisory comment/label; no merge, no gate (advisory).
    EMIT_SIGNAL = "emit-signal"


@dataclass(frozen=True)
class LoopSpec:
    """One loop's declarative entry — the per-loop seams, nothing chassis-owned.

    Attributes:
        loop: The loop this spec specialises (the registry key).
        disposition: How its work item terminates (commit vs emit-signal).
        observe: The signal→candidate seam — the one genuinely per-loop body.
        id_segment: The workflow-id/branch namespace segment. Empty for
            ``dependency-patch`` (legacy-compat: its ids predate a second loop
            and must stay byte-for-byte so a running loop is never orphaned);
            every loop added after carries its name as a segment.
        judge_context: The framing line for the in-loop changelog judge, or
            ``None`` when the loop does no changelog judging (e.g. dead-code,
            whose judgment is a safe-to-remove veto *at the signal*, inside
            ``observe``).
        reconciles: Whether version-supersession reconcile applies — ``True``
            for bump loops, ``False`` for a loop whose work item carries no
            version to be overtaken (dead-code removals). The reconcile activity
            keys on this instead of naming the loop.
        dashboard_icon: The icon key for this loop's dashboard tab (one of the
            renderer's ``_ICONS``). Carried here so a new loop's tab is fully
            presented from its spec — no per-loop arm in the renderer.
    """

    loop: Loop
    disposition: Disposition
    observe: ObserveFn
    id_segment: tuple[str, ...]
    judge_context: str | None = None
    reconciles: bool = True
    dashboard_icon: str = "package"


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


def all_specs() -> tuple[LoopSpec, ...]:
    """Every registered loop spec, in registration order."""
    _ensure()
    return tuple(_LOOPS.values())
