"""GitHub reader: froot's PRs as the durable outcome ledger.

One issues-list call per repo (PRs are issues) filtered to the ``froot`` label
returns every proposed bump with its outcome — state, timestamps, and the
deterministic title/body froot writes (``compose.py``). Package + target parse
from the title (``deps: bump <pkg> to <ver>``); the from-version and the model's
changelog verdict parse from the body, so the judgment survives even after the
bump ages out of Temporal's window. Read-only: the dashboard needs no write
scope (it reuses ``FROOT_GITHUB_TOKEN`` only because it is already in the pod).

The parsers are pure and unit-tested apart from the network; the HTTP shape is
read at the boundary as untyped JSON and coerced here.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Final

import httpx

from froot.config.settings import GitHubSettings
from froot.domain.base import Frozen

_API: Final = "https://api.github.com"
_API_VERSION: Final = "2022-11-28"
_TIMEOUT: Final = 15.0
_LABEL: Final = "froot"
_PER_PAGE: Final = 100

_TITLE_RE: Final = re.compile(r"^deps: bump (?P<pkg>.+) to (?P<ver>\S+)\s*$")
_FROM_RE: Final = re.compile(r"from (?P<from>\S+) to (?P<to>\S+)")


class GithubPr(Frozen):
    """A froot pull request, reduced to what the read-model needs."""

    repo: str
    number: int
    url: str
    package: str | None
    from_version: str | None
    to_version: str | None
    verdict: str | None
    state: str  # open | merged | closed
    opened_at: datetime | None
    merged_at: datetime | None


def parse_title(title: str) -> tuple[str, str] | None:
    """Parse ``deps: bump <pkg> to <ver>`` into ``(package, target)`` (pure)."""
    match = _TITLE_RE.match(title.strip())
    if match is None:
        return None
    return match.group("pkg"), match.group("ver")


def parse_from_version(body: str | None) -> str | None:
    """Pull the from-version out of froot's PR body template (pure)."""
    if not body:
        return None
    match = _FROM_RE.search(body)
    return match.group("from") if match else None


def parse_verdict(body: str | None) -> str | None:
    """Recover the changelog verdict from froot's body template (pure).

    Mirrors ``policy/compose.py``'s ``_verdict_summary`` openers, so an old PR
    whose Temporal run has aged out still shows the judgment it carried.
    """
    if not body:
        return None
    if "Changelog reads clean" in body:
        return "clean"
    if "Review carefully" in body:
        return "risky"
    if "Changelog unavailable" in body:
        return "unknown"
    return None


def _parse_dt(value: Any) -> datetime | None:
    """Coerce a GitHub ISO-8601 timestamp into an aware datetime (boundary)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_pr(repo: str, payload: Any) -> GithubPr | None:
    """Coerce one issues-API row into a :class:`GithubPr`, or skip non-PRs."""
    if not isinstance(payload, dict):
        return None
    pull_request = payload.get("pull_request")
    if not isinstance(pull_request, dict):
        return None  # a plain issue, not a PR
    merged_at = _parse_dt(pull_request.get("merged_at"))
    if merged_at is not None:
        state = "merged"
    elif payload.get("state") == "open":
        state = "open"
    else:
        state = "closed"
    parsed = parse_title(str(payload.get("title", "")))
    package, to_version = parsed if parsed is not None else (None, None)
    body = payload.get("body")
    return GithubPr(
        repo=repo,
        number=int(payload["number"]),
        url=str(payload.get("html_url", "")),
        package=package,
        from_version=parse_from_version(body),
        to_version=to_version,
        verdict=parse_verdict(body),
        state=state,
        opened_at=_parse_dt(payload.get("created_at")),
        merged_at=merged_at,
    )


async def fetch(
    repos: tuple[str, ...],
) -> tuple[tuple[GithubPr, ...], str | None]:
    """Read every froot PR across ``repos``; never raises.

    Returns:
        ``(prs, error)`` — ``error`` is ``None`` on success, else a short
        reason and ``prs`` is whatever was gathered before the failure.
    """
    token = GitHubSettings().github_token
    if token is None:
        return (), "FROOT_GITHUB_TOKEN unset"
    headers = {
        "Authorization": f"Bearer {token.get_secret_value()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
    }
    prs: list[GithubPr] = []
    try:
        async with httpx.AsyncClient(
            base_url=_API, timeout=_TIMEOUT, headers=headers
        ) as client:
            for repo in repos:
                resp = await client.get(
                    f"/repos/{repo}/issues",
                    params={
                        "labels": _LABEL,
                        "state": "all",
                        "per_page": _PER_PAGE,
                        "sort": "created",
                        "direction": "desc",
                    },
                )
                resp.raise_for_status()
                rows = resp.json()
                if isinstance(rows, list):
                    prs.extend(
                        pr
                        for row in rows
                        if (pr := _to_pr(repo, row)) is not None
                    )
    except Exception as exc:  # never raise into gather — degrade to an error
        return tuple(prs), f"{type(exc).__name__}: {exc}"
    return tuple(prs), None
