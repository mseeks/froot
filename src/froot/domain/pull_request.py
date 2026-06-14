"""The pull request a loop opens — its bounded action and durable artifact.

The PR is froot's whole output: a reversible, reviewable change the human
approves. The branch name is the loop's idempotency key (one PR per bump,
deterministic), so re-running never opens a duplicate — see
:mod:`froot.policy.naming`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from froot.domain.base import Frozen


class BranchName(Frozen):
    """A git branch name, validated to a ref-safe subset.

    Deterministically derived from the bump identity (see
    :func:`froot.policy.naming.branch_name`), so it doubles as the dedup key
    for "have I already proposed this bump?".
    """

    value: str = Field(min_length=1, pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

    def __str__(self) -> str:
        """Render as the bare branch string."""
        return self.value


class PullRequestRef(Frozen):
    """A handle to an opened pull request.

    Attributes:
        number: The PR number on the repo.
        url: The PR's web URL (surfaced to the human).
        branch: The head branch the change lives on.
        head_sha: The head commit SHA — what CI runs against and what the loop
            polls a status for.
    """

    number: int = Field(ge=1)
    url: str = Field(min_length=1)
    branch: BranchName
    head_sha: str = Field(min_length=7)


class PullRequestDraft(Frozen):
    """The content of a pull request the loop wants to open.

    Composed deterministically by
    :func:`froot.policy.compose.pull_request_draft` (spine-heavy: the title and
    body are a template, not a model call). The branch already carries the
    bump's changes when this is handed to the forge.

    Attributes:
        branch: The head branch the change lives on (the dedup key).
        base: The branch the PR merges into (the repo's default branch).
        title: The PR title.
        body: The PR description (the changelog framing, the bump, the source).
    """

    branch: BranchName
    base: str = Field(min_length=1)
    title: str = Field(min_length=1)
    body: str


# GitHub's documented per-file change statuses in a pull request.
PrFileStatus = Literal[
    "added", "modified", "removed", "renamed", "copied", "changed", "unchanged"
]


class PrFileChange(Frozen):
    """One file a pull request changed, with its status — the richer feed.

    The path-only ``list_pull_request_files`` feed drops removed and renamed
    files; a loop that reasons about references a PR *broke* needs them — a
    deleted target breaks a doc link, a rename moves it. For a rename (or copy),
    ``previous_filename`` is the pre-rename path.

    Attributes:
        filename: The file's path at the PR head (the new path for a rename).
        status: GitHub's change status for the file.
        previous_filename: The pre-rename path when ``status`` is ``renamed`` /
            ``copied``, else ``None``.
    """

    filename: str = Field(min_length=1)
    status: PrFileStatus
    previous_filename: str | None = None
