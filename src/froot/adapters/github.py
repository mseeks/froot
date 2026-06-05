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

import time
from dataclasses import dataclass
from datetime import timedelta
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
    from collections.abc import AsyncIterator
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


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """The server-advised wait before retrying a rate-limited request, if any.

    Honors the secondary-limit ``Retry-After`` header (delta-seconds form), then
    the primary-limit ``X-RateLimit-Reset`` (epoch) when the remaining quota is
    zero. Returns ``None`` when GitHub gives no usable hint (let Temporal's own
    backoff decide).
    """
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None  # HTTP-date form is rare from GitHub; fall through.
    if response.headers.get("x-ratelimit-remaining") == "0":
        reset = response.headers.get("x-ratelimit-reset")
        if reset is not None:
            try:
                return max(0.0, float(reset) - time.time())
            except ValueError:
                return None
    return None


def _is_rate_limited(response: httpx.Response) -> bool:
    """Whether a 403/429 is GitHub *rate limiting* (transient), not auth.

    GitHub overloads 403 for both a permanent permission fault AND its secondary
    rate limit, so the two are told apart by the rate-limit markers: an explicit
    ``Retry-After``, an exhausted ``X-RateLimit-Remaining``, or a "rate limit"
    note in the body (the secondary-limit form often only says so there).
    """
    if response.status_code == 429:
        return True
    if response.status_code != 403:
        return False
    if "retry-after" in response.headers:
        return True
    if response.headers.get("x-ratelimit-remaining") == "0":
        return True
    return "rate limit" in response.text.lower()


def _raise_for_status(response: httpx.Response) -> None:
    """Raise on error, classifying retryability the way the loop needs.

    A 401 is always a permanent auth fault. A 403/429 doubles as GitHub's
    rate-limit signal: when it carries a rate-limit marker the fault is
    TRANSIENT, so raise a *retryable* error (honoring the server's advised wait)
    and let Temporal back off rather than killing the loop — this is the
    call-heaviest path (the durable CI poll), so a transient limit must not be
    fatal. A 403 without those markers is a real permission fault and stays
    non-retryable.
    """
    if response.status_code == 401:
        raise ApplicationError("GitHub auth failed (401)", non_retryable=True)
    if response.status_code in (403, 429) and _is_rate_limited(response):
        delay = _retry_after_seconds(response)
        raise ApplicationError(
            f"GitHub rate-limited ({response.status_code}); backing off",
            type="GitHubRateLimited",
            next_retry_delay=(
                timedelta(seconds=delay) if delay is not None else None
            ),
        )
    if response.status_code == 403:
        raise ApplicationError("GitHub auth failed (403)", non_retryable=True)
    response.raise_for_status()


def _next_link(response: httpx.Response) -> str | None:
    """The ``rel="next"`` page URL from the Link header, or None at the end."""
    nxt = response.links.get("next")
    return nxt.get("url") if nxt else None


async def _iter_pages(
    client: httpx.AsyncClient,
    url: str,
    params: dict[str, Any] | None = None,
) -> AsyncIterator[httpx.Response]:
    """Yield each page of a GitHub list endpoint, following Link ``rel=next``.

    GitHub caps a page at 100 items; a single ``per_page=100`` read silently
    truncates a busy repo — which here would *misread the CI oracle* (a failing
    101st check goes unseen) or *break comment idempotency* (froot's marker on a
    later page is missed, so it posts a duplicate). Following the Link header
    reads the whole set; the data, not a fixed cap, bounds the loop.
    """
    next_url: str | None = url
    # First page carries the caller's filters + per_page; later pages use the
    # absolute Link URL verbatim (it already encodes them), so params drop off.
    next_params: dict[str, Any] | None = {**(params or {}), "per_page": 100}
    while next_url is not None:
        resp = await client.get(next_url, params=next_params)
        _raise_for_status(resp)
        yield resp
        next_url = _next_link(resp)
        next_params = None


async def _marked_comment_id(
    client: httpx.AsyncClient, slug: str, number: int, marker: str
) -> int | None:
    """The id of froot's ``marker``-tagged comment on a PR, across all pages.

    Searches every comment page (stopping at the first hit) so a chatty PR that
    pushes the marker past the first 100 comments cannot fool the upsert into
    posting a duplicate.
    """
    async for page in _iter_pages(
        client, f"/repos/{slug}/issues/{number}/comments"
    ):
        for comment in page.json():
            if isinstance(comment, dict) and marker in str(
                comment.get("body", "")
            ):
                return int(comment["id"])
    return None


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
        refs: list[PullRequestRef] = []
        async with _client() as client:
            async for page in _iter_pages(
                client,
                f"/repos/{target.repo.slug}/pulls",
                {"state": "open"},
            ):
                payload = page.json()
                if isinstance(payload, list):
                    refs.extend(_pull_request_ref(p) for p in payload)
        return tuple(refs)

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
        """Read the repo's combined CI status for a commit (the oracle).

        The check-runs are paginated (a commit can have >100 checks, and missing
        a failing one would falsely read green); the legacy combined status is a
        single rolled-up ``state`` over all statuses, so it needs no paging.
        """
        slug = target.repo.slug
        rows: list[CheckRow] = []
        async with _client() as client:
            async for page in _iter_pages(
                client, f"/repos/{slug}/commits/{head_sha}/check-runs"
            ):
                rows.extend(
                    CheckRow(
                        name=str(run["name"]),
                        status=str(run["status"]),
                        conclusion=(
                            str(run["conclusion"])
                            if run.get("conclusion") is not None
                            else None
                        ),
                    )
                    for run in page.json().get("check_runs", [])
                )
            status_resp = await client.get(
                f"/repos/{slug}/commits/{head_sha}/status"
            )
        _raise_for_status(status_resp)
        status_json = status_resp.json()
        combined = (
            str(status_json["state"])
            if int(status_json.get("total_count", 0)) > 0
            else None
        )
        return ci_status_from_checks(tuple(rows), combined)

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
            existing_id = await _marked_comment_id(client, slug, number, marker)
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
