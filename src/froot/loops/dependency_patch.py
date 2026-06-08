"""The dependency-patch loop: keep dependencies patched (the first loop).

Signal: the available upgrades the package manager reports. Candidate: the
highest patch-level target per package (pure selection). Disposition: commit —
the spine opens a PR and gates the merge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.loop import Loop
from froot.loops.registry import Disposition, LoopSpec, register

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.repo import TargetRepo
    from froot.domain.work import WorkItem
    from froot.ports.protocols import PackageManager

# The framing line for the in-loop changelog judge.
_JUDGE_CONTEXT = (
    "This is a patch-level upgrade; weigh whether the notes hide "
    "any behavioral change behind a 'patch'."
)


async def observe(
    target: TargetRepo,
    package_manager: PackageManager,
    manifest_dir: Path,
) -> tuple[int, tuple[WorkItem, ...]]:
    """Read the available upgrades and pick the highest patch per package."""
    from froot.policy.candidates import select_patch_candidates

    upgrades = await package_manager.list_upgrades(target, manifest_dir)
    return len(upgrades), select_patch_candidates(upgrades)


register(
    LoopSpec(
        loop=Loop.DEPENDENCY_PATCH,
        disposition=Disposition.COMMIT_OR_REVERT,
        observe=observe,
        # Legacy-compat: dependency-patch ids carry no segment (the first loop).
        id_segment=(),
        judge_context=_JUDGE_CONTEXT,
    )
)
