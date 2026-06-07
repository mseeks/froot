"""Shared test builders and fake port implementations.

Builders construct valid domain values tersely; the fakes implement the
:mod:`froot.ports` Protocols in memory so the activities can be exercised
without npm, git, GitHub, or a model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.advisory import Advisory, VulnRange
from froot.domain.candidate import (
    AvailableUpgrade,
    Candidate,
    InstalledPackage,
)
from froot.domain.changelog import (
    Changelog,
    ChangelogVerdict,
    CleanVerdict,
)
from froot.domain.ci import CIPassed, CIStatus
from froot.domain.ecosystem import Ecosystem
from froot.domain.loop import Loop
from froot.domain.pull_request import (
    BranchName,
    PullRequestDraft,
    PullRequestRef,
)
from froot.domain.removal import Removal
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
) -> Candidate:
    return Candidate(
        package=package,
        ecosystem=ecosystem,
        current=ver(current),
        target=ver(target),
    )


def make_removal(
    package: str = "left-pad",
    ecosystem: Ecosystem = Ecosystem.NPM,
    dev: bool = False,
    justification: str | None = "unused (knip)",
) -> Removal:
    return Removal(
        package=package,
        ecosystem=ecosystem,
        dev=dev,
        justification=justification,
    )


def make_upgrade(
    package: str = "left-pad",
    current: str = "1.4.2",
    available: tuple[str, ...] = ("1.4.3",),
    ecosystem: Ecosystem = Ecosystem.NPM,
) -> AvailableUpgrade:
    return AvailableUpgrade(
        package=package,
        ecosystem=ecosystem,
        current=ver(current),
        available=tuple(ver(v) for v in available),
    )


def make_installed(
    package: str = "left-pad",
    version: str = "1.4.2",
    ecosystem: Ecosystem = Ecosystem.NPM,
) -> InstalledPackage:
    return InstalledPackage(
        package=package, ecosystem=ecosystem, version=ver(version)
    )


def make_advisory(
    package: str = "left-pad",
    advisory_id: str = "GHSA-test",
    ranges: tuple[tuple[str, str | None], ...] = (("0", "1.4.3"),),
    aliases: tuple[str, ...] = (),
    ecosystem: Ecosystem = Ecosystem.NPM,
) -> Advisory:
    return Advisory(
        id=advisory_id,
        aliases=aliases,
        package=package,
        ecosystem=ecosystem,
        ranges=tuple(VulnRange(introduced=i, fixed=f) for i, f in ranges),
    )


def make_repo(
    slug: str = "acme/widgets",
    default_branch: str = "main",
    ecosystem: Ecosystem = Ecosystem.NPM,
) -> TargetRepo:
    return TargetRepo(
        repo=unwrap(RepoRef.parse(slug)),
        default_branch=default_branch,
        ecosystem=ecosystem,
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
        ci_sequence: tuple[CIStatus, ...] = (),
        open_prs: tuple[PullRequestRef, ...] = (),
    ) -> None:
        self.existing_pr = existing_pr
        self.opened_pr = opened_pr or make_pr()
        self.ci: CIStatus = ci or CIPassed()
        # A scripted CI reply sequence the poll pops through (then falls back to
        # ``ci``), so a test can exercise the durable pending -> terminal wait.
        self._ci_replies = list(ci_sequence)
        self.open_prs = open_prs
        self.checked_out = False
        self.checked_out_pr: int | None = None
        self.pushed: BranchName | None = None
        self.labeled: tuple[str, ...] | None = None
        self.upserted: tuple[int, str] | None = None
        # Every close + branch-delete, in order, so reconcile/close-on-red
        # tests can assert exactly which PRs were closed.
        self.closed: list[int] = []
        self.deleted_branches: list[BranchName] = []
        self.comments: list[tuple[int, str]] = []
        # Every auto-merge, in order, so the acting-gate tests can assert it.
        self.merged: list[int] = []

    async def checkout(self, target: TargetRepo, workspace: Path) -> None:
        self.checked_out = True

    async def checkout_pull_request(
        self, target: TargetRepo, workspace: Path, number: int
    ) -> None:
        self.checked_out_pr = number

    async def push_branch(
        self, workspace: Path, branch: BranchName, commit_message: str
    ) -> str:
        self.pushed = branch
        return "deadbeef1234567"

    async def find_open_pull_request(
        self, target: TargetRepo, branch: BranchName
    ) -> PullRequestRef | None:
        return self.existing_pr

    async def list_open_pull_requests(
        self, target: TargetRepo
    ) -> tuple[PullRequestRef, ...]:
        return self.open_prs

    async def upsert_issue_comment(
        self, target: TargetRepo, number: int, marker: str, body: str
    ) -> str:
        self.upserted = (number, body)
        self.comments.append((number, body))
        return f"https://github.com/{target.repo.slug}/pull/{number}#comment"

    async def open_pull_request(
        self, target: TargetRepo, draft: PullRequestDraft
    ) -> PullRequestRef:
        return self.opened_pr

    async def ci_status(self, target: TargetRepo, head_sha: str) -> CIStatus:
        if self._ci_replies:
            return self._ci_replies.pop(0)
        return self.ci

    async def add_labels(
        self, target: TargetRepo, number: int, labels: tuple[str, ...]
    ) -> None:
        self.labeled = labels

    async def close_pull_request(
        self,
        target: TargetRepo,
        number: int,
        branch: BranchName,
        *,
        delete_branch: bool = True,
    ) -> None:
        self.closed.append(number)
        if delete_branch:
            self.deleted_branches.append(branch)

    async def merge_pull_request(
        self,
        target: TargetRepo,
        number: int,
        *,
        head_sha: str | None = None,
        merge_method: str = "squash",
    ) -> None:
        self.merged.append(number)


class FakePackageManager:
    """In-memory :class:`~froot.ports.protocols.PackageManager`."""

    def __init__(
        self,
        upgrades: tuple[AvailableUpgrade, ...] = (),
        installed: tuple[InstalledPackage, ...] = (),
        unused: tuple[Removal, ...] = (),
    ) -> None:
        self.upgrades = upgrades
        self.installed = installed
        self.unused = unused
        self.applied: Candidate | None = None
        # Every dependency removed, in order, so the dead-code tests can assert
        # exactly what the action did.
        self.removed: list[Removal] = []

    async def list_upgrades(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[AvailableUpgrade, ...]:
        return self.upgrades

    async def list_installed(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[InstalledPackage, ...]:
        return self.installed

    async def apply_patch_bump(
        self, candidate: Candidate, workspace: Path
    ) -> None:
        self.applied = candidate

    async def list_unused(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[Removal, ...]:
        return self.unused

    async def remove_dependency(
        self, removal: Removal, workspace: Path
    ) -> None:
        self.removed.append(removal)


class FakeAdvisorySource:
    """In-memory :class:`~froot.ports.protocols.AdvisorySource`."""

    def __init__(self, advisories: tuple[Advisory, ...] = ()) -> None:
        self.advisories_for = advisories

    async def advisories(
        self, installed: tuple[InstalledPackage, ...]
    ) -> tuple[Advisory, ...]:
        return self.advisories_for


class FakeChangelogSource:
    """In-memory :class:`~froot.ports.protocols.ChangelogSource`."""

    def __init__(self, changelog: Changelog | None = None) -> None:
        self.changelog = changelog

    async def fetch(self, candidate: Candidate) -> Changelog | None:
        return self.changelog


class FakeJudge:
    """In-memory :class:`~froot.ports.protocols.ModelJudge`."""

    def __init__(
        self,
        verdict: ChangelogVerdict | None = None,
        gate_verdict: ChangelogVerdict | None = None,
        removal_verdict: ChangelogVerdict | None = None,
    ) -> None:
        self.verdict: ChangelogVerdict = verdict or CleanVerdict(rationale="ok")
        # The gate reviewer's verdict; defaults to the judge's, so an
        # unconfigured fake approves a clean bump at the gate too.
        self.gate_verdict: ChangelogVerdict = gate_verdict or self.verdict
        # The safe-to-remove verdict; defaults to clean, so an unconfigured fake
        # lets a removal through the veto.
        self.removal_verdict: ChangelogVerdict = (
            removal_verdict or CleanVerdict(rationale="safe to remove")
        )
        self.loops: list[Loop] = []
        self.gate_loops: list[Loop] = []
        # Every removal judged, in order, so the veto tests can assert it.
        self.removals: list[Removal] = []

    async def judge(
        self, changelog: Changelog, loop: Loop = Loop.DEPENDENCY_PATCH
    ) -> ChangelogVerdict:
        self.loops.append(loop)
        return self.verdict

    async def gate_review(
        self, changelog: Changelog, loop: Loop = Loop.DEPENDENCY_PATCH
    ) -> ChangelogVerdict:
        self.gate_loops.append(loop)
        return self.gate_verdict

    async def judge_removal(self, removal: Removal) -> ChangelogVerdict:
        self.removals.append(removal)
        return self.removal_verdict
