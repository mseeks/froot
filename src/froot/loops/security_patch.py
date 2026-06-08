"""The security-patch loop: bump dependencies to clear known advisories.

Signal: OSV advisories against the installed set. Candidate: the lowest version
that clears each advisory while staying forward-stable (pure selection).
Disposition: commit — the spine opens a PR and gates the merge.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.loop import Loop
from froot.loops.registry import CommitTail, LoopSpec, register

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.repo import TargetRepo
    from froot.domain.work import WorkItem
    from froot.ports.protocols import PackageManager

# The framing line for the in-loop changelog judge: a security bump may cross a
# minor/major line, so the judge weighs breaking changes the human should know.
_JUDGE_CONTEXT = (
    "This is a SECURITY upgrade that may cross a minor or major "
    "line to clear a vulnerability; weigh breaking changes the "
    "human should know before merging — the fix is still worth it."
)


async def observe(
    target: TargetRepo,
    package_manager: PackageManager,
    manifest_dir: Path,
) -> tuple[int, tuple[WorkItem, ...]]:
    """Installed set → OSV advisories → the clearing targets.

    ``considered`` is the count of advisories OSV returned for the installed
    set — the vulnerabilities in scope this tick, before selection narrows to
    the ones a forward-stable bump can actually clear.
    """
    from froot.adapters.osv import OsvAdvisorySource
    from froot.policy.candidates import select_security_candidates

    installed = await package_manager.list_installed(target, manifest_dir)
    advisories = await OsvAdvisorySource().advisories(installed)
    return len(advisories), select_security_candidates(installed, advisories)


register(
    LoopSpec(
        loop=Loop.SECURITY_PATCH,
        dashboard_icon="shield",
        tail=CommitTail(
            observe=observe,
            title_prefix="security",
            judge_context=_JUDGE_CONTEXT,
        ),
    )
)
