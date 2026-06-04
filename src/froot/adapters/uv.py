"""The uv (Python) package-manager adapter.

Reads upgrade availability from the committed manifest + lockfile (no install
needed) plus the PyPI registry, and regenerates the lockfile with ``uv lock
--upgrade-package <pkg>==<target>`` — lockfile-only, so the real install, build,
and tests happen in the repo's CI (the oracle), never in the worker.

Three boundary facts, each parsed by a pure, fixture-tested function:

* **Direct dependencies** come from ``pyproject.toml`` (PEP 621
  ``[project.dependencies]`` / ``[project.optional-dependencies]`` and PEP 735
  ``[dependency-groups]``). Only direct dependencies are bumped; a transitive
  one would be promoted to direct, which is not a patch.
* **The installed baseline** comes from ``uv.lock`` (its ``[[package]]``
  entries), *not* from an installed environment: froot only does a clone, never
  a ``uv sync``. Names are PEP 503-normalized so the manifest and lock agree
  (``Pydantic-Settings`` == ``pydantic-settings``).
* **The available versions** come from the PyPI JSON API. uv has no
  "list every version" command (its ``pip`` subcommands inspect an installed
  environment only), so this is the registry query that mirrors ``npm view``.

Two deliberate scope notes, both conservative — froot proposes *fewer* Python
bumps, never a wrong one:

* Versions use the shared semver :class:`~froot.domain.version.Version`, so
  PEP 440 forms outside ``X.Y.Z`` (epochs, two- or four-segment releases,
  ``post``/``dev`` releases, non-``-`` prereleases) are skipped. The common
  ``X.Y.Z -> X.Y.(Z+1)`` patch — the loop's whole job — round-trips cleanly.
* ``uv lock`` only touches ``uv.lock``; it does not edit ``pyproject.toml``. A
  patch within the existing constraint (``>=`` / ``~=`` / unbounded) needs no
  manifest change and ``uv sync --frozen`` accepts the pair. A dependency
  pinned exactly (``pkg==1.2.3``) cannot be patched lockfile-only — ``uv lock``
  errors, which :meth:`UvPackageManager.apply_patch_bump` surfaces.
"""

from __future__ import annotations

import json
import re
import tomllib
from typing import TYPE_CHECKING

import httpx

from froot.adapters._proc import run_text
from froot.domain.candidate import AvailableUpgrade
from froot.domain.version import Version
from froot.result import Ok

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.candidate import PatchCandidate
    from froot.domain.repo import TargetRepo

_PYPI_JSON = "https://pypi.org/pypi"
_TIMEOUT = 15.0

# The leading distribution name of a PEP 508 requirement (before any extras,
# version specifier, or environment marker).
_REQUIREMENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# PEP 503 separators: runs of '.', '-', '_' collapse to a single '-'.
_NAME_SEPARATORS = re.compile(r"[-_.]+")


def normalize_name(name: str) -> str:
    """PEP 503-normalize a project name (lowercase; ``.-_`` runs -> ``-``)."""
    return _NAME_SEPARATORS.sub("-", name).strip("-").lower()


def _requirement_name(requirement: str) -> str | None:
    """The normalized distribution name of a PEP 508 requirement string."""
    match = _REQUIREMENT_NAME.match(requirement.strip())
    return normalize_name(match.group(0)) if match else None


def _collect_requirements(requirements: object, into: set[str]) -> None:
    """Add the normalized names from a list of requirement strings."""
    if not isinstance(requirements, list):
        return
    for requirement in requirements:
        # PEP 735 groups may hold ``{include-group = ...}`` tables; the group
        # they reference is collected on its own pass, so non-strings are
        # skipped here.
        if not isinstance(requirement, str):
            continue
        name = _requirement_name(requirement)
        if name:
            into.add(name)


def parse_direct_dependencies(pyproject: str) -> frozenset[str]:
    """The direct dependency names declared in a ``pyproject.toml``.

    Reads PEP 621 ``[project.dependencies]`` and every
    ``[project.optional-dependencies]`` group, plus PEP 735
    ``[dependency-groups]`` (e.g. uv's ``dev`` group). Names are PEP
    503-normalized. Malformed TOML yields an empty set (a boundary concern,
    handled like any other unparseable input).
    """
    try:
        data = tomllib.loads(pyproject)
    except tomllib.TOMLDecodeError:
        return frozenset()
    names: set[str] = set()
    project = data.get("project")
    if isinstance(project, dict):
        _collect_requirements(project.get("dependencies"), names)
        optional = project.get("optional-dependencies")
        if isinstance(optional, dict):
            for group in optional.values():
                _collect_requirements(group, names)
    groups = data.get("dependency-groups")
    if isinstance(groups, dict):
        for group in groups.values():
            _collect_requirements(group, names)
    return frozenset(names)


def parse_locked_versions(uv_lock: str) -> dict[str, str]:
    """Resolved version per package from a ``uv.lock``.

    Reads the ``[[package]]`` array, keying on the PEP 503-normalized name. The
    root project and any entry without a ``version`` are simply absent from the
    map; callers look up direct dependencies by name, so extras are harmless.
    Malformed TOML yields an empty map.
    """
    try:
        data = tomllib.loads(uv_lock)
    except tomllib.TOMLDecodeError:
        return {}
    versions: dict[str, str] = {}
    packages = data.get("package")
    if not isinstance(packages, list):
        return versions
    for package in packages:
        if not isinstance(package, dict):
            continue
        name = package.get("name")
        version = package.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[normalize_name(name)] = version
    return versions


def _has_installable_file(files: object) -> bool:
    """True if a PyPI release has at least one non-yanked distribution file."""
    if not isinstance(files, list) or not files:
        return False
    return any(
        not (isinstance(file, dict) and file.get("yanked", False))
        for file in files
    )


def parse_available_versions(payload: str) -> tuple[Version, ...]:
    """Parse a PyPI ``/pypi/<name>/json`` body into domain versions.

    Reads the ``releases`` map, dropping any release that is fully yanked or
    ships no files (so a yanked patch is never proposed) and any version string
    that is not a clean semver (prereleases and PEP 440 oddities fall out here).
    Empty or non-JSON input yields ``()``.
    """
    if not payload.strip():
        return ()
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return ()
    releases = data.get("releases") if isinstance(data, dict) else None
    if not isinstance(releases, dict):
        return ()
    versions: list[Version] = []
    for raw, files in releases.items():
        if not (isinstance(raw, str) and _has_installable_file(files)):
            continue
        match Version.parse(raw):
            case Ok(version):
                versions.append(version)
            case _:
                continue
    return tuple(versions)


async def _available_versions(
    client: httpx.AsyncClient, name: str
) -> tuple[Version, ...]:
    """Fetch a package's published versions from PyPI (best-effort)."""
    try:
        response = await client.get(f"{_PYPI_JSON}/{name}/json")
    except httpx.HTTPError:
        # A network error means "no known upgrades for this package" — the scan
        # proposes nothing for it rather than failing the whole run.
        return ()
    if response.status_code != 200:
        return ()
    return parse_available_versions(response.text)


class UvPackageManager:
    """A :class:`~froot.ports.protocols.PackageManager` backed by ``uv``."""

    async def list_upgrades(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[AvailableUpgrade, ...]:
        """Report each direct dependency and the versions available to it."""
        direct = parse_direct_dependencies(
            (workspace / "pyproject.toml").read_text()
        )
        lock_path = workspace / "uv.lock"
        locked = (
            parse_locked_versions(lock_path.read_text())
            if lock_path.exists()
            else {}
        )
        upgrades: list[AvailableUpgrade] = []
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            for name in sorted(direct):
                current_text = locked.get(name)
                if current_text is None:
                    continue
                match Version.parse(current_text):
                    case Ok(current):
                        pass
                    case _:
                        continue
                upgrades.append(
                    AvailableUpgrade(
                        package=name,
                        ecosystem=target.ecosystem,
                        current=current,
                        available=await _available_versions(client, name),
                    )
                )
        return tuple(upgrades)

    async def apply_patch_bump(
        self, candidate: PatchCandidate, workspace: Path
    ) -> None:
        """Regenerate ``uv.lock`` at the target version (lockfile-only)."""
        code, out, err = await run_text(
            "uv",
            "lock",
            "--upgrade-package",
            f"{candidate.package}=={candidate.target}",
            cwd=workspace,
        )
        if code != 0:
            raise RuntimeError(f"uv lock failed ({code}): {err or out}")
