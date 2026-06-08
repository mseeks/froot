"""The dead-code loop: remove unused dependencies.

Signal: the unused direct dependencies a static analyzer flags. Judgment: the
safe-to-remove judge vetoes each *at the signal* (a tool used without an import
— pytest, eslint — is dropped before a workflow ever starts), so this loop's one
thin model call lives inside ``observe``, not as an in-loop changelog judge
(``judge_context`` is therefore ``None``). Candidate: the surviving removals.
Disposition: commit — the spine opens a PR and gates the merge (CI is oracle).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from temporalio import activity

from froot.domain.loop import Loop
from froot.loops.registry import Disposition, LoopSpec, register

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.removal import Removal
    from froot.domain.repo import TargetRepo
    from froot.domain.work import WorkItem
    from froot.ports.protocols import PackageManager


async def observe(
    target: TargetRepo,
    package_manager: PackageManager,
    manifest_dir: Path,
) -> tuple[int, tuple[WorkItem, ...]]:
    """Unused deps flagged, then vetoed safe-to-remove (the veto is the judge).

    The static analyzer flags every unused direct dependency; the safe-to-remove
    judge then vetoes each — only a ``clean`` survives to become a PR. A judge
    error drops that removal (fail-safe: never propose what was not vetted).
    ``considered`` is the flagged count; the kept count is the survivors, so the
    scan tick shows how much the veto filtered.
    """
    from froot.adapters.model_judge import PydanticAiJudge

    flagged = await package_manager.list_unused(target, manifest_dir)
    if not flagged:
        return 0, ()
    judge = PydanticAiJudge()
    kept: list[Removal] = []
    for removal in flagged:
        try:
            verdict = await judge.judge_removal(removal)
        except Exception as exc:
            activity.logger.warning(
                "safe-to-remove judge unavailable for %s; skipping: %r",
                removal.package,
                exc,
            )
            continue
        if verdict.kind != "clean":
            continue
        # Carry the judge's reasoning into the work item so the PR body explains
        # why the removal is safe, beside the detector note.
        enriched = (
            f"{removal.justification}; {verdict.rationale}"
            if removal.justification
            else verdict.rationale
        )
        kept.append(removal.model_copy(update={"justification": enriched}))
    return len(flagged), tuple(kept)


register(
    LoopSpec(
        loop=Loop.DEAD_CODE,
        disposition=Disposition.COMMIT_OR_REVERT,
        observe=observe,
        id_segment=(Loop.DEAD_CODE.value,),
        # Dead-code judges at the signal (the veto above), not the changelog.
        judge_context=None,
        # A removal carries no version to be overtaken — nothing to reconcile.
        reconciles=False,
    )
)
