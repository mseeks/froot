"""The maintenance loops froot runs, and how each is namespaced.

froot's durable chassis is loop-agnostic; only the signal, the candidate policy,
and a little namespacing make a loop a specialist. Two loops ship:
:data:`Loop.DEPENDENCY_PATCH` (keep dependencies patched) and
:data:`Loop.SECURITY_PATCH` (bump dependencies to clear known advisories).

A loop's *value* is the kebab name that namespaces everything it owns — the
branch prefix (``froot/<loop>``), the PR label, the workflow ids, and the
structured-log identity — so two loops never collide on a branch or a workflow
id even when they touch the same package. A further loop is one more member plus
its signal and candidate policy; the chassis it runs on does not change.
"""

from __future__ import annotations

from enum import StrEnum


class Loop(StrEnum):
    """A maintenance loop froot points at a repo."""

    DEPENDENCY_PATCH = "dependency-patch"
    SECURITY_PATCH = "security-patch"
