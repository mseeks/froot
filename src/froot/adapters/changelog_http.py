"""Best-effort changelog source: npm registry metadata + GitHub release notes.

There is no universal changelog format, so this fetches the one cheap, reliable
signal of *what changed*: the linked GitHub repo's release notes for the version
tag. It returns ``None`` when there are none. A package's registry *description*
is deliberately NOT used as a fallback — it describes what the package does, not
what changed between versions, and feeding it to the judge produces misleading
risk verdicts. The judge activity treats ``None`` as an ``UnknownVerdict``
without spending a model call (spine-heavy: never ask the model to assess a
non-changelog). The registry-URL parsing is a pure function, tested offline.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

import httpx

from froot.domain.changelog import Changelog
from froot.domain.repo import RepoRef
from froot.result import Ok

if TYPE_CHECKING:
    from froot.domain.candidate import PatchCandidate

_REGISTRY = "https://registry.npmjs.org"
_GITHUB_API = "https://api.github.com"
_GITHUB_URL = re.compile(r"github\.com[/:]([^/]+)/([^/.]+)")
_TIMEOUT = 15.0


def github_repo_from_registry(metadata: Any) -> RepoRef | None:
    """Extract the GitHub repo from npm registry ``repository.url``, if any."""
    repository = (
        metadata.get("repository") if isinstance(metadata, dict) else None
    )
    url = repository.get("url") if isinstance(repository, dict) else repository
    if not isinstance(url, str):
        return None
    found = _GITHUB_URL.search(url)
    if found is None:
        return None
    match RepoRef.parse(f"{found.group(1)}/{found.group(2)}"):
        case Ok(ref):
            return ref
        case _:
            return None


class HttpChangelogSource:
    """A :class:`~froot.ports.protocols.ChangelogSource` over HTTP."""

    async def fetch(self, candidate: PatchCandidate) -> Changelog | None:
        """Fetch the target version's changelog, or ``None`` (best-effort)."""
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                return await self._fetch(client, candidate)
        except (httpx.HTTPError, json.JSONDecodeError):
            # Best-effort: a network error or a malformed 200 body both mean
            # "no usable changelog", which the judge maps to UnknownVerdict.
            return None

    async def _fetch(
        self, client: httpx.AsyncClient, candidate: PatchCandidate
    ) -> Changelog | None:
        meta = await client.get(f"{_REGISTRY}/{candidate.package}")
        if meta.status_code != 200:
            return None
        metadata = meta.json()
        repo = github_repo_from_registry(metadata)
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
