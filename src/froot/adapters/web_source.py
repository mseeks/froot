"""Load a checked-out repo's changed web templates for the a11y sweep.

The I/O boundary for the source-level a11y signal: given the PR's changed paths
and the checkout, read each *template* file (``.vue``/``.jsx``/``.tsx``) into
memory as a :class:`~froot.policy.a11y_scan.WebSource` the pure scan consumes.
Non-template paths are skipped, and a file that won't read is skipped too — a
best-effort map is better than a failed review. This never runs in a workflow
sandbox; it is called only from an activity.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.policy.a11y_scan import WebSource, dialect_for

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path


def load_web_sources(
    repo: Path, rel_paths: Iterable[str]
) -> tuple[WebSource, ...]:
    """Read each changed template under ``repo`` into a ``WebSource``."""
    sources: list[WebSource] = []
    for rel in rel_paths:
        dialect = dialect_for(rel)
        if dialect is None:
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        sources.append(
            WebSource(
                path=rel,
                dialect=dialect,
                lines=tuple(text.splitlines()),
            )
        )
    return tuple(sources)
