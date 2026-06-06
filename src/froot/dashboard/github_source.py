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
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from froot.config.settings import GitHubSettings
from froot.domain.base import Frozen
from froot.domain.loop import Loop

_API: Final = "https://api.github.com"
_API_VERSION: Final = "2022-11-28"
_TIMEOUT: Final = 15.0
_LABEL: Final = "froot"
_PER_PAGE: Final = 100

_TITLE_RE: Final = re.compile(r"^deps: bump (?P<pkg>.+) to (?P<ver>\S+)\s*$")
_FROM_RE: Final = re.compile(r"from (?P<from>\S+) to (?P<to>\S+)")
# froot's squash merges leave a ``(#N)`` tail on the default-branch commit, so a
# merged PR can be matched to its merge commit without a per-PR API call.
_PR_REF_RE: Final = re.compile(r"\(#(\d+)\)")

# Check-run conclusions, split into "the branch held" vs "the branch broke". A
# commit with no check runs at all is neither — it is ``unknown`` (no oracle on
# the branch), never silently counted as a pass.
_OK_CONCLUSIONS: Final = frozenset({"success", "neutral", "skipped", "stale"})
_BAD_CONCLUSIONS: Final = frozenset(
    {"failure", "cancelled", "timed_out", "action_required", "startup_failure"}
)


class GithubPr(Frozen):
    """A froot pull request, reduced to what the read-model needs."""

    repo: str
    number: int
    url: str
    # The loop label (``dependency-patch`` | ``security-patch``); defaults to
    # dependency-patch so a PR with no loop label (or a hand-built test row)
    # attributes to the original loop rather than failing to construct.
    loop: str = "dependency-patch"
    package: str | None
    from_version: str | None
    to_version: str | None
    verdict: str | None
    state: str  # open | merged | closed
    opened_at: datetime | None
    merged_at: datetime | None


def _loop_from_labels(payload: Any) -> str:
    """The loop a PR belongs to, from its labels (defaults dependency-patch).

    Every froot PR carries its loop's label alongside the ``froot`` label, so
    the loop is durable on the PR even after its Temporal run ages out.
    """
    labels = payload.get("labels")
    names = (
        {lbl.get("name") for lbl in labels if isinstance(lbl, dict)}
        if isinstance(labels, list)
        else set()
    )
    for loop in Loop:
        if loop.value in names:
            return loop.value
    return Loop.DEPENDENCY_PATCH.value


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
    """Coerce a GitHub ISO-8601 timestamp into an *aware* datetime (boundary).

    GitHub stamps everything ``...Z`` (UTC), which ``fromisoformat`` parses as
    aware — but a missing/odd offset would yield a naive datetime, and the
    read-model subtracts these against an aware ``now`` (a naive operand raises
    ``TypeError`` and would blank the whole page). So any naive result is
    pinned to UTC here, at the one boundary, the way the other readers do.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


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
        loop=_loop_from_labels(payload),
        package=package,
        from_version=parse_from_version(body),
        to_version=to_version,
        verdict=parse_verdict(body),
        state=state,
        opened_at=_parse_dt(payload.get("created_at")),
        merged_at=merged_at,
    )


def _commit_pr_refs(message: str) -> list[int]:
    """PR numbers referenced as ``(#N)`` in a commit message (pure)."""
    return [int(ref) for ref in _PR_REF_RE.findall(message)]


def _is_revert(message: str) -> bool:
    """True if a commit message reads as a git revert (``Revert "..."``)."""
    return message.lstrip().lower().startswith("revert")


def classify_check_runs(payload: Any) -> str:
    """Reduce a commit's check-runs to held / broke / unknown (pure boundary).

    ``broke`` if any run reported a failing conclusion; ``held`` if runs exist
    and none failed; ``unknown`` if no check ran on the commit — i.e. there is
    no oracle on the branch, which is never conflated with a pass (the same
    discipline the verification panel keeps for ``absent`` CI).
    """
    runs = payload.get("check_runs") if isinstance(payload, dict) else None
    if not isinstance(runs, list) or not runs:
        return "unknown"
    conclusions = {r.get("conclusion") for r in runs if isinstance(r, dict)}
    if conclusions & _BAD_CONCLUSIONS:
        return "broke"
    if conclusions & _OK_CONCLUSIONS:
        return "held"
    return "unknown"


def _merge_index(
    commits: Any, merged_numbers: frozenset[int]
) -> tuple[dict[int, str], set[int]]:
    """From a default-branch commit list, map PR# → merge SHA and the reverted.

    Commits arrive newest-first, so the first commit referencing ``(#N)`` is the
    merge; a ``Revert`` commit's refs mark those PRs reverted instead. Only
    froot's own merged numbers are considered, so an unrelated ``(#N)`` can't
    cross-attribute. Pure over already-fetched JSON.
    """
    merge_sha: dict[int, str] = {}
    reverted: set[int] = set()
    if not isinstance(commits, list):
        return merge_sha, reverted
    for entry in commits:
        if not isinstance(entry, dict):
            continue
        sha = entry.get("sha")
        commit = entry.get("commit")
        message = commit.get("message", "") if isinstance(commit, dict) else ""
        refs = [n for n in _commit_pr_refs(message) if n in merged_numbers]
        if not refs:
            continue
        if _is_revert(message):
            reverted.update(refs)
        elif isinstance(sha, str):
            for number in refs:
                merge_sha.setdefault(number, sha)
    return merge_sha, reverted


async def fetch_outcomes(
    repos: tuple[str, ...],
    prs: tuple[GithubPr, ...],
    *,
    now: datetime,
    window_days: int,
) -> tuple[dict[tuple[str, int], str], str | None]:
    """Best-effort post-merge outcome per recently-merged PR; never raises.

    Per repo: read the default branch's recent commits once (to match froot's
    ``(#N)`` squash tail to the merge commit and spot ``Revert`` commits), then
    read each merge commit's check-runs to see whether the branch's CI held.
    Returns ``{(repo, number): "held"|"broke"|"reverted"|"unknown"}``.

    Deliberately coarse and low-recall: a *manual* or *bundled* revert is
    invisible here (most are — git-reverts are the minority), and a merge older
    than one commit page falls to ``unknown`` rather than a false ``held``. This
    is the natural-traffic floor; the adversarial canary leg is what exercises
    it. ``(prs, error)``-style: degrades to a reason, keeping partial results.
    """
    token = GitHubSettings().github_token
    if token is None:
        return {}, "FROOT_GITHUB_TOKEN unset"
    headers = {
        "Authorization": f"Bearer {token.get_secret_value()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": _API_VERSION,
    }
    horizon = window_days * 86400.0
    outcomes: dict[tuple[str, int], str] = {}
    try:
        async with httpx.AsyncClient(
            base_url=_API, timeout=_TIMEOUT, headers=headers
        ) as client:
            for repo in repos:
                merged = [
                    pr
                    for pr in prs
                    if pr.repo == repo
                    and pr.state == "merged"
                    and pr.merged_at is not None
                    and (now - pr.merged_at).total_seconds() <= horizon
                ]
                if not merged:
                    continue
                resp = await client.get(
                    f"/repos/{repo}/commits", params={"per_page": _PER_PAGE}
                )
                resp.raise_for_status()
                merge_sha, reverted = _merge_index(
                    resp.json(), frozenset(pr.number for pr in merged)
                )
                for pr in merged:
                    if pr.number in reverted:
                        outcomes[(repo, pr.number)] = "reverted"
                        continue
                    sha = merge_sha.get(pr.number)
                    if sha is None:
                        outcomes[(repo, pr.number)] = "unknown"
                        continue
                    checks = await client.get(
                        f"/repos/{repo}/commits/{sha}/check-runs"
                    )
                    checks.raise_for_status()
                    outcomes[(repo, pr.number)] = classify_check_runs(
                        checks.json()
                    )
    except Exception as exc:  # never raise into gather — degrade to an error
        return outcomes, f"{type(exc).__name__}: {exc}"
    return outcomes, None


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
