"""Typed Protocols for the impure world the spine talks to.

Methods are ``async`` so an activity simply awaits a port; an adapter that wraps
a blocking tool (``npm``, ``git``) runs it off the event loop internally, and
one backed by an HTTP API uses an async client. The pure core and the spine
depend on these abstractions; :mod:`froot.adapters` provides the concrete
implementations and tests pass fakes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.advisory import Advisory
    from froot.domain.candidate import (
        AvailableUpgrade,
        Candidate,
        InstalledPackage,
    )
    from froot.domain.changelog import Changelog, ChangelogVerdict
    from froot.domain.ci import CIStatus
    from froot.domain.loop import Loop
    from froot.domain.pull_request import (
        BranchName,
        PullRequestDraft,
        PullRequestRef,
    )
    from froot.domain.repo import TargetRepo


class PackageManager(Protocol):
    """Reads dependency facts and regenerates the manifest + lockfile.

    The adapter carries the package manager (e.g. ``npm``) but never runs the
    project's tests or install scripts — lockfile regeneration only, so the
    worker stays light and no third-party dependency code executes in it.
    """

    async def list_upgrades(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[AvailableUpgrade, ...]:
        """Report each outdated dependency and the versions available to it."""
        ...

    async def list_installed(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[InstalledPackage, ...]:
        """Report the direct dependencies and their locked versions.

        The security signal's input: every *direct* dependency (froot can only
        bump those) at the version the lockfile pins, regardless of whether a
        newer one exists. Read from the lockfile only — no install.
        """
        ...

    async def apply_patch_bump(
        self, candidate: Candidate, workspace: Path
    ) -> None:
        """Rewrite the manifest + lockfile in ``workspace`` to the target.

        Lockfile-only and with install scripts disabled: it resolves and
        writes the dependency tree but runs no project or dependency code.
        """
        ...


class AdvisorySource(Protocol):
    """Looks up known security advisories for a set of installed packages."""

    async def advisories(
        self, installed: tuple[InstalledPackage, ...]
    ) -> tuple[Advisory, ...]:
        """Return the advisories affecting any of ``installed`` (one per vuln).

        Best-effort: a lookup that fails for a package yields no advisories for
        it rather than raising, so a flaky source never blocks the loop.
        """
        ...


class Forge(Protocol):
    """Git + GitHub: checkout, branch/PR, CI status, labels.

    The verification oracle is the repo's own CI (:meth:`ci_status`); froot
    never runs tests itself. PR creation is idempotent against the deterministic
    branch — see :meth:`find_open_pull_request`.
    """

    async def checkout(self, target: TargetRepo, workspace: Path) -> None:
        """Materialize the repo's default branch into ``workspace``."""
        ...

    async def checkout_pull_request(
        self, target: TargetRepo, workspace: Path, number: int
    ) -> None:
        """Materialize a PR's head into ``workspace`` via ``refs/pull/N/head``.

        Works uniformly for same-repo and fork PRs — the base repo exposes the
        head of every PR under ``refs/pull/<number>/head``, so no fork URL or
        cross-repo auth is needed.
        """
        ...

    async def push_branch(
        self, workspace: Path, branch: BranchName, commit_message: str
    ) -> str:
        """Commit the workspace changes onto ``branch`` and push it.

        The workspace's ``origin`` already authenticates against the repo (set
        up by :meth:`checkout`), so no target is needed here.

        Returns:
            The pushed head commit SHA.
        """
        ...

    async def find_open_pull_request(
        self, target: TargetRepo, branch: BranchName
    ) -> PullRequestRef | None:
        """Return the open PR for ``branch`` if one already exists (dedup)."""
        ...

    async def list_open_pull_requests(
        self, target: TargetRepo
    ) -> tuple[PullRequestRef, ...]:
        """List the repo's open PRs (the determinism reviewer's work feed)."""
        ...

    async def upsert_issue_comment(
        self, target: TargetRepo, number: int, marker: str, body: str
    ) -> str:
        """Create or update the PR's ``marker``-tagged comment; return its URL.

        Finds the existing comment containing ``marker`` and edits it in place,
        else posts a new one — so re-reviewing a PR never stacks comments.
        """
        ...

    async def open_pull_request(
        self, target: TargetRepo, draft: PullRequestDraft
    ) -> PullRequestRef:
        """Open the PR for an already-pushed branch."""
        ...

    async def ci_status(self, target: TargetRepo, head_sha: str) -> CIStatus:
        """Read the repo's combined CI status for a commit (the oracle)."""
        ...

    async def add_labels(
        self, target: TargetRepo, number: int, labels: tuple[str, ...]
    ) -> None:
        """Attach labels to a PR (the human-readable signal-update)."""
        ...

    async def close_pull_request(
        self,
        target: TargetRepo,
        number: int,
        branch: BranchName,
        *,
        delete_branch: bool = True,
    ) -> None:
        """Close the PR and (by default) delete its head branch.

        Idempotent: closing an already-closed PR is a no-op, and a missing
        branch is tolerated — so a retried close never fails on a half-done
        prior attempt. Deleting the branch keeps a re-derived bump from later
        colliding with a stale ref (a non-fast-forward push). Any human-facing
        explanation is posted separately via :meth:`upsert_issue_comment`, so
        this stays a pure lifecycle action.
        """
        ...

    async def merge_pull_request(
        self,
        target: TargetRepo,
        number: int,
        *,
        head_sha: str | None = None,
        merge_method: str = "squash",
    ) -> None:
        """Merge the PR (the acting gate's one write).

        Passes the expected ``head_sha`` so the merge is refused if the head
        moved since the gate decided. An unmergeable state surfaces as an error
        rather than a silent success.
        """
        ...


class ChangelogSource(Protocol):
    """Best-effort fetch of a target version's changelog / release notes."""

    async def fetch(self, candidate: Candidate) -> Changelog | None:
        """Return the changelog for the candidate's target, or ``None``."""
        ...


class ModelJudge(Protocol):
    """The thin model judgment: how risky is this bump's changelog?"""

    async def judge(
        self, changelog: Changelog, loop: Loop = ...
    ) -> ChangelogVerdict:
        """Assess a changelog into a verdict, framed by the loop."""
        ...

    async def gate_review(
        self, changelog: Changelog, loop: Loop = ...
    ) -> ChangelogVerdict:
        """Independently deep-review a bump at the gate (adversarial pass).

        A second, stricter reading run only when a bump is about to auto-merge:
        ``clean`` approves the merge, anything else holds it. Independent of the
        first :meth:`judge` pass (its own model and prompt) so the two can
        disagree — the fourth trust leg (§3.7).
        """
        ...
