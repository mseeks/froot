"""Domain types for the documentation-reference (doc-refs) reviewer.

The mechanical sweep (:mod:`froot.policy.doc_refs_scan`) flags references in a
PR's changed Markdown that point at something which no longer exists — a
relative link or a backtick-quoted file path to a missing file, or a
``make <target>`` mention whose Makefile target is gone. The model then confirms
each in context (a broken-looking ref can be intentional or historical), and the
confirmed ones become the advisory comment. It never merges; a human fixes the
doc.

Its sharpest signal is a reference broken by the PR's OWN deletion or rename
(``broken_by_pr``) — the consumer edge to froot's dead-code / dependency-patch
loops, whose merges remove files a doc still points at.

Every type is :class:`~froot.domain.base.Frozen` so it serializes across the
Temporal boundary: the scan runs in an activity and its result rides back to the
(deterministic) workflow.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from froot.domain.base import Frozen

DocRefKind = Literal["broken-link", "missing-path", "missing-make"]
"""The three mechanical drift kinds: a dead Markdown link, a dead backtick file
path, or a removed ``make`` target."""


class DocRefCandidate(Frozen):
    """A raw scan hit — a doc reference whose target appears to be missing.

    The model adjudicates each in context; ``broken_by_pr`` marks the
    high-confidence case where the referent is a path the PR itself removed or
    renamed away from (so the doc was almost certainly left dangling by it).
    """

    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    kind: DocRefKind
    referent: str = Field(min_length=1)
    """The link target / file path / make target that resolves to nothing."""
    snippet: str = ""
    """The trimmed source line — the model's context."""
    broken_by_pr: bool = False
    """The referent is a path this PR removed or renamed away from."""


class DocRefAnalysis(Frozen):
    """The scan's output for one PR's changed Markdown."""

    candidates: tuple[DocRefCandidate, ...] = ()
    scanned_files: int = Field(default=0, ge=0)
