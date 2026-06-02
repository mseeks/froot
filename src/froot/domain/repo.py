"""The target a loop is pointed at: a GitHub repository and its ecosystem.

A loop is repo-agnostic; froot points it at a :class:`TargetRepo` and the same
chassis runs. The repo identity (:class:`RepoRef`) is also the source of truth
for the loop's reputation — outcomes are derived from this repo's PR history,
never stored (SPEC: derive, never store).
"""

from __future__ import annotations

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.ecosystem import Ecosystem
from froot.result import Err, Ok, Result

# A GitHub owner/repo path segment: letters, digits, '.', '_', '-', anchored to
# the whole value so a slash/space/newline can't slip through. \A..\z (not ^..$,
# which would allow a trailing newline); \z is the Rust-regex end anchor
# pydantic-core uses (\Z is Python-only and is rejected by pydantic-core).
_SEGMENT = r"\A[A-Za-z0-9._-]+\z"


class RepoRef(Frozen):
    """A GitHub repository identity (``owner/name``)."""

    owner: str = Field(min_length=1, pattern=_SEGMENT)
    name: str = Field(min_length=1, pattern=_SEGMENT)

    @classmethod
    def parse(cls, slug: str) -> Result[RepoRef, str]:
        """Parse an ``owner/name`` slug at the untrusted boundary.

        Args:
            slug: A string like ``"octocat/hello-world"``.

        Returns:
            ``Ok(RepoRef)`` or ``Err(message)`` if the slug is malformed.
        """
        parts = slug.split("/")
        if len(parts) != 2 or not all(parts):
            return Err(f"not an 'owner/name' slug: {slug!r}")
        owner, name = parts
        return Ok(cls(owner=owner, name=name))

    @property
    def slug(self) -> str:
        """The canonical ``owner/name`` form."""
        return f"{self.owner}/{self.name}"

    def __str__(self) -> str:
        """Render as ``owner/name``."""
        return self.slug


class TargetRepo(Frozen):
    """A repository a loop operates on, with the facts the chassis needs.

    Attributes:
        repo: The GitHub ``owner/name`` identity.
        ecosystem: Which package manager governs its dependencies.
        default_branch: The branch PRs target and checkouts start from.
        manifest_dir: The repo-relative directory holding the manifest, for
            monorepos or nested packages. Empty means the repository root.
    """

    repo: RepoRef
    ecosystem: Ecosystem = Ecosystem.NPM
    default_branch: str = Field(default="main", min_length=1)
    manifest_dir: str = ""
