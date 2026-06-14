"""Load a checked-out repo's Markdown + path index for the doc-refs sweep.

The I/O boundary for the doc-refs signal: given the PR's changed paths and the
checkout, read each changed ``.md`` into a :class:`~froot.policy.doc_refs_scan.
DocSource`, index every existing repo path (for the reference-existence check),
and parse the head Makefile's targets. A file that won't read is skipped — a
best-effort map beats a failed review. This never runs in a workflow sandbox; it
is called only from an activity.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

from froot.policy.doc_refs_scan import DocSource

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

# Directories whose contents are never doc referents — pruned from the index
# (and never descended into, so a huge node_modules doesn't slow the walk).
_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "dist",
        "build",
    }
)
_MAKE_TARGET = re.compile(r"^([A-Za-z][\w-]*):")


def load_doc_sources(
    repo: Path, rel_paths: Iterable[str]
) -> tuple[DocSource, ...]:
    """Read each changed ``.md`` under ``repo`` into a ``DocSource``."""
    sources: list[DocSource] = []
    for rel in rel_paths:
        if not rel.lower().endswith(".md"):
            continue
        try:
            text = (repo / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        sources.append(DocSource(path=rel, lines=tuple(text.splitlines())))
    return tuple(sources)


def index_paths(repo: Path) -> frozenset[str]:
    """Index every existing repo-relative POSIX path (files and dirs).

    Directories are indexed too so a link to a folder resolves, matching
    ``Path.exists`` semantics. Skip-dirs are pruned, not descended.
    """
    paths: set[str] = set()
    for root, dirs, files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        base = repo.joinpath(root)
        for name in (*files, *dirs):
            paths.add(base.joinpath(name).relative_to(repo).as_posix())
    return frozenset(paths)


def make_targets(repo: Path) -> frozenset[str]:
    """Parse the head ``Makefile``'s target names (empty when there is none)."""
    try:
        text = (repo / "Makefile").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return frozenset()
    targets: set[str] = set()
    for line in text.splitlines():
        match = _MAKE_TARGET.match(line)
        if match:
            targets.add(match.group(1))
    return frozenset(targets)
