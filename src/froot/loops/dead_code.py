"""The dead-code loop: remove the dead weight a static analyzer flags.

Signal: a static analyzer (npm via knip) flags three shapes of dead code — an
unused dependency, a whole unused file, and an export no other module imports.
Judgment: the safe-to-remove judge vetoes each *at the signal* (a tool used
without an import, a framework entry loaded by convention — these are dropped
before a workflow ever starts), so this loop's one thin model call lives inside
``observe``, not as an in-loop changelog judge (``judge_context`` is therefore
``None``). Work item: the survivors (a removal, a dead file, or an un-export).
Disposition: commit — the spine opens a PR and gates the merge (CI is oracle).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from temporalio import activity

from froot.domain.loop import Loop
from froot.domain.removal import Removal
from froot.loops.registry import CommitTail, LoopSpec, register

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.dead_source import DeadExport, DeadFile
    from froot.domain.repo import TargetRepo
    from froot.domain.work import WorkItem
    from froot.ports.protocols import PackageManager


# Vet up to this many items at once. The local Ollama serves ~4 concurrent
# calls, so a large dead-code backlog's safe-to-remove judgments overlap instead
# of serializing: a repo with ~70 flagged items at ~30s/judgment would otherwise
# run ~35 min sequentially and trip the scan activity's ceiling.
_JUDGE_CONCURRENCY = 4


async def observe(
    target: TargetRepo,
    package_manager: PackageManager,
    manifest_dir: Path,
) -> tuple[int, tuple[WorkItem, ...]]:
    """Dead code flagged, then vetoed safe-to-remove (the veto is the judge).

    The static analyzer flags every shape of dead code; the safe-to-remove judge
    then vetoes each — a dependency through the dependency veto, a file/export
    through the source veto — and only a ``clean`` survives to become a PR. A
    judge error drops that item (fail-safe: never propose what was not vetted).
    ``considered`` is the flagged count; the kept count is the survivors, so the
    scan tick shows how much the veto filtered.
    """
    from froot.adapters.model_judge import PydanticAiJudge

    flagged = await package_manager.list_unused(target, manifest_dir)
    if not flagged:
        return 0, ()
    judge = PydanticAiJudge()
    gate = asyncio.Semaphore(_JUDGE_CONCURRENCY)

    async def _vet(item: Removal | DeadFile | DeadExport) -> WorkItem | None:
        """Judged clean -> enriched item; else ``None`` (fail-safe)."""
        async with gate:
            try:
                verdict = (
                    await judge.judge_removal(item)
                    if isinstance(item, Removal)
                    else await judge.judge_dead_source(item)
                )
            except Exception as exc:
                activity.logger.warning(
                    "safe-to-remove judge unavailable for %s; skipping: %r",
                    item.subject,
                    exc,
                )
                return None
        if verdict.kind != "clean":
            return None
        # Carry the judge's reasoning into the work item so the PR body explains
        # why the change is safe, beside the detector note.
        enriched = (
            f"{item.justification}; {verdict.rationale}"
            if item.justification
            else verdict.rationale
        )
        return item.model_copy(update={"justification": enriched})

    # Fan out under the semaphore; gather preserves the flagged order.
    vetted: list[WorkItem | None] = await asyncio.gather(
        *(_vet(item) for item in flagged)
    )
    kept = tuple(item for item in vetted if item is not None)
    return len(flagged), kept


register(
    LoopSpec(
        loop=Loop.DEAD_CODE,
        dashboard_icon="scissors",
        tail=CommitTail(
            observe=observe,
            title_prefix="dead-code",
            # Dead-code judges at the signal (the veto), not the changelog.
            judge_context=None,
            # No dead-code item carries a version to be overtaken — nothing to
            # reconcile.
            reconciles=False,
        ),
    )
)
