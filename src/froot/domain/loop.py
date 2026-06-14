"""The maintenance loops froot runs, and how each is namespaced.

froot's durable chassis is loop-agnostic; only the signal, the candidate policy,
and a little namespacing make a loop a specialist. Two families ship. The acting
(commit-or-revert) loops propose a PR the spine gates and merges:
:data:`Loop.DEPENDENCY_PATCH` (keep dependencies patched),
:data:`Loop.SECURITY_PATCH` (clear known advisories), and :data:`Loop.DEAD_CODE`
(remove unused dependencies). The advisory (emit-signal) loops read open PRs and
leave one decaying comment, never a merge:
:data:`Loop.DETERMINISM_REVIEW` (transitive Temporal-determinism hazards),
:data:`Loop.A11Y_REVIEW` (source-level accessibility gaps), and
:data:`Loop.DOC_REFS` (dangling documentation references). The family is the
loop's :class:`~froot.loops.registry.LoopSpec` tail; this enum is just the key.

A loop's *value* is the kebab name that namespaces everything it owns — the
branch prefix (``froot/<loop>``), the PR label, the workflow ids, and the
structured-log identity — so two loops never collide on a branch or a workflow
id even when they touch the same package. A further loop is one more member plus
its registered spec; the chassis it runs on does not change.
"""

from __future__ import annotations

from enum import StrEnum


class Loop(StrEnum):
    """A maintenance loop froot points at a repo."""

    DEPENDENCY_PATCH = "dependency-patch"
    SECURITY_PATCH = "security-patch"
    DEAD_CODE = "dead-code"
    DETERMINISM_REVIEW = "determinism-review"
    A11Y_REVIEW = "a11y-review"
    DOC_REFS = "doc-refs"
