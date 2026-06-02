"""Shared test builders and fake port implementations.

Builders construct valid domain values tersely; the fakes implement the
:mod:`froot.ports` Protocols in memory so the activities can be exercised
without npm, git, GitHub, or a model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.candidate import AvailableUpgrade, PatchCandidate
from froot.domain.changelog import (
    Changelog,
    ChangelogVerdict,
    CleanVerdict,
)
from froot.domain.ci import CIPassed, CIStatus
from froot.domain.ecosystem import Ecosystem
from froot.domain.pull_request import (
    BranchName,
    PullRequestDraft,
    PullRequestRef,
)
from froot.domain.repo import RepoRef, TargetRepo
from froot.domain.version import Version
from froot.result import unwrap

if TYPE_CHECKING:
    from pathlib import Path


def ver(text: str) -> Version:
    return unwrap(Version.parse(text))


def make_candidate(
    package: str = "left-pad",
    current: str = "1.4.2",
    target: str = "1.4.3",
    ecosystem: Ecosystem = Ecosystem.NPM,
) -> PatchCandidate:
    return PatchCandidate(
        package=package,
        ecosystem=ecosystem,
        current=ver(current),
        target=ver(target),
    )


def make_repo(
    slug: str = "acme/widgets", default_branch: str = "main"
) -> TargetRepo:
    return TargetRepo(
        repo=unwrap(RepoRef.parse(slug)), default_branch=default_branch
    )


def make_pr(
    number: int = 1,
    branch: str = "froot/dependency-patch/left-pad-1.4.3",
    head_sha: str = "abc1234",
) -> PullRequestRef:
    return PullRequestRef(
        number=number,
        url=f"https://github.com/acme/widgets/pull/{number}",
        branch=BranchName(value=branch),
        head_sha=head_sha,
    )


class FakeForge:
    """In-memory :class:`~froot.ports.protocols.Forge` that records calls."""

    def __init__(
        self,
        *,
        existing_pr: PullRequestRef | None = None,
        opened_pr: PullRequestRef | None = None,
        ci: CIStatus | None = None,
    ) -> None:
        self.existing_pr = existing_pr
        self.opened_pr = opened_pr or make_pr()
        self.ci: CIStatus = ci or CIPassed()
        self.checked_out = False
        self.pushed: BranchName | None = None
        self.labeled: tuple[str, ...] | None = None

    async def checkout(self, target: TargetRepo, workspace: Path) -> None:
        self.checked_out = True

    async def push_branch(
        self, workspace: Path, branch: BranchName, commit_message: str
    ) -> str:
        self.pushed = branch
        return "deadbeef1234567"

    async def find_open_pull_request(
        self, target: TargetRepo, branch: BranchName
    ) -> PullRequestRef | None:
        return self.existing_pr

    async def open_pull_request(
        self, target: TargetRepo, draft: PullRequestDraft
    ) -> PullRequestRef:
        return self.opened_pr

    async def ci_status(self, target: TargetRepo, head_sha: str) -> CIStatus:
        return self.ci

    async def add_labels(
        self, target: TargetRepo, number: int, labels: tuple[str, ...]
    ) -> None:
        self.labeled = labels


class FakePackageManager:
    """In-memory :class:`~froot.ports.protocols.PackageManager`."""

    def __init__(self, upgrades: tuple[AvailableUpgrade, ...] = ()) -> None:
        self.upgrades = upgrades
        self.applied: PatchCandidate | None = None

    async def list_upgrades(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[AvailableUpgrade, ...]:
        return self.upgrades

    async def apply_patch_bump(
        self, candidate: PatchCandidate, workspace: Path
    ) -> None:
        self.applied = candidate


class FakeChangelogSource:
    """In-memory :class:`~froot.ports.protocols.ChangelogSource`."""

    def __init__(self, changelog: Changelog | None = None) -> None:
        self.changelog = changelog

    async def fetch(self, candidate: PatchCandidate) -> Changelog | None:
        return self.changelog


class FakeJudge:
    """In-memory :class:`~froot.ports.protocols.ModelJudge`."""

    def __init__(self, verdict: ChangelogVerdict | None = None) -> None:
        self.verdict: ChangelogVerdict = verdict or CleanVerdict(rationale="ok")

    async def judge(self, changelog: Changelog) -> ChangelogVerdict:
        return self.verdict
