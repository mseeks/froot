"""The GitHub forge adapter: git (checkout/push) + the GitHub REST API.

Backs :class:`~froot.ports.protocols.Forge`. Checkout and branch push go
through ``git``; pull requests, CI status, and labels go through the REST API
(httpx). The verification oracle is the repo's own CI — :meth:`ci_status` reads
it, froot never runs tests. PR creation is idempotent against the deterministic
head branch (:meth:`find_open_pull_request`), so a re-run never double-opens.

The CI mapping (:func:`ci_status_from_checks`) is a pure function over typed
check rows, unit-tested apart from the network; the GitHub JSON shapes are
read at the boundary as untyped payloads and coerced into the domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, final

import httpx
from temporalio.exceptions import ApplicationError

from froot.config.settings import GitHubSettings
from froot.domain.ci import (
    CIAbsent,
    CIFailed,
    CIPassed,
    CIPending,
    CIStatus,
)
from froot.domain.pull_request import BranchName, PullRequestRef

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.pull_request import PullRequestDraft
    from froot.domain.repo import TargetRepo

from froot.adapters._proc import run_text

_API = "https://api.github.com"
_API_VERSION = "2022-11-28"
_TIMEOUT = 30.0
_COMMITTER_NAME = "froot"
_COMMITTER_EMAIL = "froot@users.noreply.github.com"

# Check-run conclusions that mean the change is not safe to merge.
_BAD_CONCLUSIONS = frozenset(
    {
        "failure",
        "timed_out",
        "cancelled",
        "action_required",
        "startup_failure",
        "stale",
    }
)


@final
@dataclass(frozen=True, slots=True)
class CheckRow:
    """One GitHub check run, reduced to what the CI mapping needs."""

    name: str
    status: str
    conclusion: str | None


def ci_status_from_checks(
    checks: tuple[CheckRow, ...], combined_state: str | None
) -> CIStatus:
    """Map GitHub check rows + the combined commit status to a CI status.

    Args:
        checks: The commit's check runs (GitHub Checks API).
        combined_state: The legacy combined commit status (``success`` /
            ``failure`` / ``pending``), or ``None`` when no statuses exist.

    Returns:
        ``CIAbsent`` when nothing reports, ``CIPending`` while anything is
        unresolved, ``CIFailed`` (with the failing check names) on any bad
        conclusion or a failed combined status, else ``CIPassed``.
    """
    if not checks and combined_state is None:
        return CIAbsent()
    unresolved = combined_state == "pending" or any(
        row.status != "completed" for row in checks
    )
    if unresolved:
        return CIPending()
    failing = tuple(
        row.name for row in checks if row.conclusion in _BAD_CONCLUSIONS
    )
    if failing or combined_state == "failure":
        return CIFailed(failing=failing)
    return CIPassed()


def _token() -> str:
    token = GitHubSettings().github_token
    if token is None:
        # A missing token is a permanent misconfiguration, not a transient
        # fault — fail the activity fast instead of retrying forever.
        raise ApplicationError(
            "FROOT_GITHUB_TOKEN is required", non_retryable=True
        )
    return token.get_secret_value()


def _auth_remote(target: TargetRepo) -> str:
    return (
        f"https://x-access-token:{_token()}@github.com/{target.repo.slug}.git"
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=_API,
        timeout=_TIMEOUT,
        headers={
            "Authorization": f"Bearer {_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
        },
    )


def _raise_for_status(response: httpx.Response) -> None:
    """Raise on error; 401/403 is a permanent (non-retryable) auth fault."""
    if response.status_code in (401, 403):
        raise ApplicationError(
            f"GitHub auth failed ({response.status_code})", non_retryable=True
        )
    response.raise_for_status()


def _pull_request_ref(payload: Any) -> PullRequestRef:
    """Coerce a GitHub PR JSON payload into a domain ref (boundary)."""
    head = payload["head"]
    return PullRequestRef(
        number=int(payload["number"]),
        url=str(payload["html_url"]),
        branch=BranchName(value=str(head["ref"])),
        head_sha=str(head["sha"]),
    )


@final
class GitHubForge:
    """A :class:`~froot.ports.protocols.Forge` over git + the GitHub API."""

    async def checkout(self, target: TargetRepo, workspace: Path) -> None:
        """Shallow-clone the repo's default branch into ``workspace``."""
        code, out, err = await run_text(
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            target.default_branch,
            _auth_remote(target),
            ".",
            cwd=workspace,
        )
        if code != 0:
            raise RuntimeError(f"git clone failed ({code}): {err or out}")

    async def checkout_pull_request(
        self, target: TargetRepo, workspace: Path, number: int
    ) -> None:
        """Materialize a PR's head into ``workspace`` via ``refs/pull/N/head``.

        Fetches the PR head ref the base repo exposes for every PR (fork or
        not), so a community PR from a fork checks out the same way a same-repo
        one does — no fork URL, no cross-repo auth.
        """
        ref = f"pull/{number}/head"
        steps: tuple[tuple[str, ...], ...] = (
            ("git", "init", "-q"),
            ("git", "remote", "add", "origin", _auth_remote(target)),
            ("git", "fetch", "--depth", "1", "origin", ref),
            ("git", "checkout", "-q", "FETCH_HEAD"),
        )
        for step in steps:
            code, out, err = await run_text(*step, cwd=workspace)
            if code != 0:
                raise RuntimeError(
                    f"git {step[1]} ({ref}) failed ({code}): {err or out}"
                )

    async def push_branch(
        self, workspace: Path, branch: BranchName, commit_message: str
    ) -> str:
        """Commit the workspace changes onto ``branch`` and push; return SHA."""
        steps: tuple[tuple[str, ...], ...] = (
            ("git", "checkout", "-b", branch.value),
            ("git", "add", "-A"),
            (
                "git",
                "-c",
                f"user.name={_COMMITTER_NAME}",
                "-c",
                f"user.email={_COMMITTER_EMAIL}",
                "commit",
                "-m",
                commit_message,
            ),
            ("git", "push", "-u", "origin", branch.value),
        )
        for step in steps:
            code, out, err = await run_text(*step, cwd=workspace)
            if code != 0:
                raise RuntimeError(f"{step[0:2]} failed ({code}): {err or out}")
        code, sha, _ = await run_text("git", "rev-parse", "HEAD", cwd=workspace)
        if code != 0:
            raise RuntimeError(f"git rev-parse failed ({code})")
        return sha.strip()

    async def find_open_pull_request(
        self, target: TargetRepo, branch: BranchName
    ) -> PullRequestRef | None:
        """Return the open PR for ``branch`` if one already exists (dedup)."""
        async with _client() as client:
            resp = await client.get(
                f"/repos/{target.repo.slug}/pulls",
                params={
                    "head": f"{target.repo.owner}:{branch.value}",
                    "state": "open",
                },
            )
        _raise_for_status(resp)
        payloads = resp.json()
        if isinstance(payloads, list) and payloads:
            return _pull_request_ref(payloads[0])
        return None

    async def list_open_pull_requests(
        self, target: TargetRepo
    ) -> tuple[PullRequestRef, ...]:
        """List the repo's open PRs (the determinism reviewer's work feed)."""
        async with _client() as client:
            resp = await client.get(
                f"/repos/{target.repo.slug}/pulls",
                params={"state": "open", "per_page": 100},
            )
        _raise_for_status(resp)
        payloads = resp.json()
        if not isinstance(payloads, list):
            return ()
        return tuple(_pull_request_ref(payload) for payload in payloads)

    async def open_pull_request(
        self, target: TargetRepo, draft: PullRequestDraft
    ) -> PullRequestRef:
        """Open the PR for an already-pushed branch (idempotent on conflict)."""
        async with _client() as client:
            resp = await client.post(
                f"/repos/{target.repo.slug}/pulls",
                json={
                    "title": draft.title,
                    "head": draft.branch.value,
                    "base": draft.base,
                    "body": draft.body,
                },
            )
        if resp.status_code == 422:
            existing = await self.find_open_pull_request(target, draft.branch)
            if existing is not None:
                return existing
        _raise_for_status(resp)
        return _pull_request_ref(resp.json())

    async def ci_status(self, target: TargetRepo, head_sha: str) -> CIStatus:
        """Read the repo's combined CI status for a commit (the oracle)."""
        async with _client() as client:
            checks_resp = await client.get(
                f"/repos/{target.repo.slug}/commits/{head_sha}/check-runs",
                params={"per_page": 100},
            )
            status_resp = await client.get(
                f"/repos/{target.repo.slug}/commits/{head_sha}/status"
            )
        _raise_for_status(checks_resp)
        _raise_for_status(status_resp)
        rows = tuple(
            CheckRow(
                name=str(run["name"]),
                status=str(run["status"]),
                conclusion=(
                    str(run["conclusion"])
                    if run.get("conclusion") is not None
                    else None
                ),
            )
            for run in checks_resp.json().get("check_runs", [])
        )
        status_json = status_resp.json()
        combined = (
            str(status_json["state"])
            if int(status_json.get("total_count", 0)) > 0
            else None
        )
        return ci_status_from_checks(rows, combined)

    async def add_labels(
        self, target: TargetRepo, number: int, labels: tuple[str, ...]
    ) -> None:
        """Attach labels to a PR (the human-readable signal-update)."""
        async with _client() as client:
            resp = await client.post(
                f"/repos/{target.repo.slug}/issues/{number}/labels",
                json={"labels": list(labels)},
            )
        _raise_for_status(resp)

    async def close_pull_request(
        self,
        target: TargetRepo,
        number: int,
        branch: BranchName,
        *,
        delete_branch: bool = True,
    ) -> None:
        """Close the PR and (by default) delete its head branch.

        Two idempotent GitHub calls: PATCH the PR to ``state=closed`` (a no-op
        if it is already closed), then DELETE the head ref. A 404/422 on the
        delete (branch already gone — e.g. the repo auto-deletes head branches
        on close) is tolerated, so a retried close never fails on a branch a
        prior attempt already removed.
        """
        slug = target.repo.slug
        async with _client() as client:
            close_resp = await client.patch(
                f"/repos/{slug}/pulls/{number}",
                json={"state": "closed"},
            )
            _raise_for_status(close_resp)
            if not delete_branch:
                return
            delete_resp = await client.delete(
                f"/repos/{slug}/git/refs/heads/{branch.value}"
            )
        if delete_resp.status_code not in (404, 422):
            _raise_for_status(delete_resp)

    async def upsert_issue_comment(
        self, target: TargetRepo, number: int, marker: str, body: str
    ) -> str:
        """Create or update the PR's ``marker``-tagged comment; return its URL.

        A PR conversation (issue) comment, not an inline review comment: the
        determinism findings are structural (a call path), so a single advisory
        summary fits better than line anchors. The marker lets a re-review edit
        its own prior comment in place rather than stack a new one.
        """
        slug = target.repo.slug
        async with _client() as client:
            listing = await client.get(
                f"/repos/{slug}/issues/{number}/comments",
                params={"per_page": 100},
            )
            _raise_for_status(listing)
            existing_id: int | None = None
            for comment in listing.json():
                if isinstance(comment, dict) and marker in str(
                    comment.get("body", "")
                ):
                    existing_id = int(comment["id"])
                    break
            if existing_id is not None:
                resp = await client.patch(
                    f"/repos/{slug}/issues/comments/{existing_id}",
                    json={"body": body},
                )
            else:
                resp = await client.post(
                    f"/repos/{slug}/issues/{number}/comments",
                    json={"body": body},
                )
        _raise_for_status(resp)
        return str(resp.json()["html_url"])
