"""Best-effort changelog source: registry metadata + GitHub release notes.

There is no universal changelog format, so this fetches the one cheap, reliable
signal of *what changed*: the linked GitHub repo's release notes for the version
tag. It returns ``None`` when there are none. A package's registry *description*
is deliberately NOT used as a fallback — it describes what the package does, not
what changed between versions, and feeding it to the judge produces misleading
risk verdicts. The judge activity treats ``None`` as an ``UnknownVerdict``
without spending a model call (spine-heavy: never ask the model to assess a
non-changelog).

The GitHub repo is discovered per ecosystem — npm's ``repository.url`` or
PyPI's ``info.project_urls`` / ``home_page`` — and the release-notes fetch is
shared from there, since both ecosystems tag GitHub releases the same way. The
registry-URL parsing is pure and tested offline.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, assert_never

import httpx

from froot.domain.changelog import Changelog
from froot.domain.ecosystem import Ecosystem
from froot.domain.repo import RepoRef
from froot.result import Ok

if TYPE_CHECKING:
    from froot.domain.candidate import Candidate

_REGISTRY = "https://registry.npmjs.org"
_PYPI_JSON = "https://pypi.org/pypi"
_GITHUB_API = "https://api.github.com"
# The name group stops at '.', '#', and '?' so a ``.git`` suffix, a ``#readme``
# fragment, or a ``?tab=`` query never bleeds into the captured repo name.
_GITHUB_URL = re.compile(r"github\.com[/:]([^/]+)/([^/.#?]+)")
_TIMEOUT = 15.0
# PyPI ``project_urls`` labels that name the source repo, preferred over a
# homepage that may point somewhere other than the code. Deliberately the
# source-*role* words only: "github" is a platform name, not a role, and would
# wrongly promote a "GitHub Sponsors" funding link over the real "Source".
_SOURCE_HINTS = ("source", "repository", "code")
# First path segment of a github.com URL that is a reserved namespace, never a
# repo owner — so a funding/profile link like github.com/sponsors/<org> is not
# mistaken for the repo ``sponsors/<org>`` (which would 404 and suppress a real
# changelog).
_RESERVED_OWNERS = frozenset(
    {
        "sponsors",
        "orgs",
        "users",
        "marketplace",
        "apps",
        "topics",
        "collections",
        "about",
        "settings",
        "pricing",
        "features",
    }
)


def _github_repo(url: str) -> RepoRef | None:
    """Parse an ``owner/name`` GitHub repo out of a URL, if it is one."""
    found = _GITHUB_URL.search(url)
    if found is None or found.group(1).lower() in _RESERVED_OWNERS:
        return None
    match RepoRef.parse(f"{found.group(1)}/{found.group(2)}"):
        case Ok(ref):
            return ref
        case _:
            return None


def github_repo_from_registry(metadata: Any) -> RepoRef | None:
    """Extract the GitHub repo from npm registry ``repository.url``, if any."""
    repository = (
        metadata.get("repository") if isinstance(metadata, dict) else None
    )
    url = repository.get("url") if isinstance(repository, dict) else repository
    return _github_repo(url) if isinstance(url, str) else None


def _pypi_candidate_urls(info: Any) -> list[str]:
    """PyPI ``info`` URLs, source/repo links first, then the homepage."""
    project_urls = info.get("project_urls") if isinstance(info, dict) else None
    preferred: list[str] = []
    rest: list[str] = []
    if isinstance(project_urls, dict):
        for label, url in project_urls.items():
            if not isinstance(url, str):
                continue
            key = label.lower() if isinstance(label, str) else ""
            target = preferred if any(h in key for h in _SOURCE_HINTS) else rest
            target.append(url)
    home = info.get("home_page") if isinstance(info, dict) else None
    if isinstance(home, str):
        rest.append(home)
    return preferred + rest


def github_repo_from_pypi(metadata: Any) -> RepoRef | None:
    """Extract the GitHub repo from PyPI ``info`` project URLs, if any."""
    info = metadata.get("info") if isinstance(metadata, dict) else None
    for url in _pypi_candidate_urls(info):
        repo = _github_repo(url)
        if repo is not None:
            return repo
    return None


class HttpChangelogSource:
    """A :class:`~froot.ports.protocols.ChangelogSource` over HTTP."""

    async def fetch(self, candidate: Candidate) -> Changelog | None:
        """Fetch the target version's changelog, or ``None`` (best-effort)."""
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, follow_redirects=True
            ) as client:
                return await self._fetch(client, candidate)
        except (httpx.HTTPError, json.JSONDecodeError):
            # Best-effort: a network error or a malformed 200 body both mean
            # "no usable changelog", which the judge maps to UnknownVerdict.
            return None

    async def _fetch(
        self, client: httpx.AsyncClient, candidate: Candidate
    ) -> Changelog | None:
        repo = await self._discover_repo(client, candidate)
        if repo is None:
            return None
        target = str(candidate.target)
        text = await self._release_notes(client, repo, target)
        if text is None:
            return None
        return Changelog(
            package=candidate.package,
            version=candidate.target,
            text=text,
            source_url=f"https://github.com/{repo.slug}/releases/tag/v{target}",
        )

    @staticmethod
    async def _discover_repo(
        client: httpx.AsyncClient, candidate: Candidate
    ) -> RepoRef | None:
        """Find the package's GitHub repo from its registry metadata."""
        match candidate.ecosystem:
            case Ecosystem.NPM:
                meta = await client.get(f"{_REGISTRY}/{candidate.package}")
                resolve = github_repo_from_registry
            case Ecosystem.UV:
                meta = await client.get(
                    f"{_PYPI_JSON}/{candidate.package}/json"
                )
                resolve = github_repo_from_pypi
            case _:
                assert_never(candidate.ecosystem)
        if meta.status_code != 200:
            return None
        return resolve(meta.json())

    @staticmethod
    async def _release_notes(
        client: httpx.AsyncClient, repo: RepoRef, target: str
    ) -> str | None:
        """GitHub release notes for the tag (``vX.Y.Z`` or ``X.Y.Z``)."""
        for tag in (f"v{target}", target):
            resp = await client.get(
                f"{_GITHUB_API}/repos/{repo.slug}/releases/tags/{tag}"
            )
            if resp.status_code == 200:
                body = resp.json().get("body")
                if isinstance(body, str) and body.strip():
                    return body
        return None
