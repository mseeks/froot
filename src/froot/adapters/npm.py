"""The npm package-manager adapter.

Reads upgrade availability from the committed manifest + lockfile (no install
needed) plus ``npm view <pkg> versions``, and regenerates the manifest +
lockfile with ``npm install <pkg>@<target> --package-lock-only
--ignore-scripts`` — lockfile-only, no install scripts, so no third-party
dependency code ever runs in the worker (the real install + tests happen in the
repo's CI, the oracle).

The installed baseline comes from ``package-lock.json``, *not* ``npm
outdated``: ``npm outdated``'s ``current`` field is absent without a
``node_modules`` tree, and froot only does a clone (never an install). The
parsing is split into pure module functions so it is unit-tested with fixtures,
away from the subprocess and the network.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from froot.adapters._proc import run_text
from froot.domain.candidate import AvailableUpgrade, InstalledPackage
from froot.domain.removal import Removal
from froot.domain.version import Version
from froot.result import Ok

if TYPE_CHECKING:
    from pathlib import Path

    from froot.domain.candidate import Candidate
    from froot.domain.repo import TargetRepo

_NODE_MODULES = "node_modules/"


def parse_direct_dependencies(package_json: str) -> frozenset[str]:
    """The direct dependency names from a ``package.json`` (deps + devDeps).

    Only direct dependencies are bumped: ``npm install <pkg>`` on a transitive
    dependency would promote it to a direct one, which is not a patch.
    """
    data = json.loads(package_json)
    names: set[str] = set()
    if isinstance(data, dict):
        for field in ("dependencies", "devDependencies"):
            section = data.get(field)
            if isinstance(section, dict):
                names.update(name for name in section if isinstance(name, str))
    return frozenset(names)


def parse_locked_versions(package_lock: str) -> dict[str, str]:
    """Resolved version per top-level dependency from a ``package-lock.json``.

    Reads the lockfileVersion 2/3 ``packages`` map (keys
    ``node_modules/<name>``, skipping nested ``.../node_modules/...`` transitive
    entries), falling back to the legacy v1 top-level ``dependencies`` map.
    """
    data = json.loads(package_lock)
    if not isinstance(data, dict):
        return {}
    versions: dict[str, str] = {}
    packages = data.get("packages")
    if isinstance(packages, dict):
        for key, info in packages.items():
            if not (isinstance(key, str) and key.startswith(_NODE_MODULES)):
                continue
            name = key[len(_NODE_MODULES) :]
            if "/node_modules/" in name:  # a nested (transitive) entry
                continue
            version = info.get("version") if isinstance(info, dict) else None
            if isinstance(version, str):
                versions[name] = version
    if versions:
        return versions
    legacy = data.get("dependencies")  # lockfileVersion 1
    if isinstance(legacy, dict):
        for name, info in legacy.items():
            version = info.get("version") if isinstance(info, dict) else None
            if isinstance(name, str) and isinstance(version, str):
                versions[name] = version
    return versions


def parse_versions(stdout: str) -> tuple[Version, ...]:
    """Parse ``npm view <pkg> versions --json`` into domain versions.

    Accepts a JSON array (the usual case) or a bare JSON string (a single
    version); empty or non-JSON output (e.g. a failed lookup) yields ``()``.
    Unparseable entries are dropped.
    """
    if not stdout.strip():
        return ()
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError:
        return ()
    items = raw if isinstance(raw, list) else [raw]
    versions: list[Version] = []
    for item in items:
        if isinstance(item, str):
            match Version.parse(item):
                case Ok(version):
                    versions.append(version)
                case _:
                    continue
    return tuple(versions)


def _loads_embedded_json(stdout: str) -> object:
    """``json.loads`` ``stdout``, tolerating leading plugin chatter.

    knip's plugins may print progress lines to stdout *before* the JSON report,
    so a plain parse can fail; this retries from the first ``{``. Empty or
    unparseable input yields ``None``.
    """
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    brace = text.find("{")
    if brace < 0:
        return None
    try:
        return json.loads(text[brace:])
    except json.JSONDecodeError:
        return None


def parse_knip_unused(stdout: str) -> tuple[tuple[str, bool], ...]:
    """Parse ``knip --reporter json`` into ``(package, dev)`` unused flags.

    knip groups issues by file; each issue's ``dependencies`` lists unused
    production deps and ``devDependencies`` unused dev deps, every entry an
    object with a ``name``. Returns one ``(name, dev)`` pair per unused
    dependency (``dev`` True for a devDependency). Empty or unparseable output
    yields ``()`` — conservative: no flags, never a raise.
    """
    data = _loads_embedded_json(stdout)
    if not isinstance(data, dict):
        return ()
    issues = data.get("issues")
    if not isinstance(issues, list):
        return ()
    flags: list[tuple[str, bool]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        for field, dev in (("dependencies", False), ("devDependencies", True)):
            section = issue.get(field)
            if not isinstance(section, list):
                continue
            for entry in section:
                name = entry.get("name") if isinstance(entry, dict) else None
                if isinstance(name, str) and name:
                    flags.append((name, dev))
    return tuple(flags)


class NpmPackageManager:
    """A :class:`~froot.ports.protocols.PackageManager` backed by ``npm``."""

    async def list_upgrades(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[AvailableUpgrade, ...]:
        """Report each direct dependency and the versions available to it."""
        direct = parse_direct_dependencies(
            (workspace / "package.json").read_text()
        )
        lock_path = workspace / "package-lock.json"
        locked = (
            parse_locked_versions(lock_path.read_text())
            if lock_path.exists()
            else {}
        )
        upgrades: list[AvailableUpgrade] = []
        for name in sorted(direct):
            current_text = locked.get(name)
            if current_text is None:
                continue
            match Version.parse(current_text):
                case Ok(current):
                    pass
                case _:
                    continue
            _, versions_out, _ = await run_text(
                "npm", "view", name, "versions", "--json", cwd=workspace
            )
            upgrades.append(
                AvailableUpgrade(
                    package=name,
                    ecosystem=target.ecosystem,
                    current=current,
                    available=parse_versions(versions_out),
                )
            )
        return tuple(upgrades)

    async def list_installed(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[InstalledPackage, ...]:
        """Report each direct dependency and its locked version (no network)."""
        direct = parse_direct_dependencies(
            (workspace / "package.json").read_text()
        )
        lock_path = workspace / "package-lock.json"
        locked = (
            parse_locked_versions(lock_path.read_text())
            if lock_path.exists()
            else {}
        )
        installed: list[InstalledPackage] = []
        for name in sorted(direct):
            current_text = locked.get(name)
            if current_text is None:
                continue
            match Version.parse(current_text):
                case Ok(version):
                    installed.append(
                        InstalledPackage(
                            package=name,
                            ecosystem=target.ecosystem,
                            version=version,
                        )
                    )
                case _:
                    continue
        return tuple(installed)

    async def apply_patch_bump(
        self, candidate: Candidate, workspace: Path
    ) -> None:
        """Rewrite the manifest + lockfile to the target (lockfile-only)."""
        code, out, err = await run_text(
            "npm",
            "install",
            f"{candidate.package}@{candidate.target}",
            "--package-lock-only",
            "--ignore-scripts",
            cwd=workspace,
        )
        if code != 0:
            raise RuntimeError(f"npm install failed ({code}): {err or out}")

    async def list_unused(
        self, target: TargetRepo, workspace: Path
    ) -> tuple[Removal, ...]:
        """Report each unused direct dependency via ``knip`` (static analysis).

        Best-effort: ``knip`` exits non-zero precisely *because* it found
        issues, so the exit code is ignored and stdout is parsed regardless;
        crashed or empty output simply yields no removals. ``knip`` is baked
        into the worker image and on ``PATH``; if it is absent (e.g. local
        dev), the signal degrades to no removals rather than raising.
        ``justification`` records the detector so the judge and PR body name it.
        """
        try:
            _, out, _ = await run_text(
                "knip",
                "--reporter",
                "json",
                "--no-progress",
                cwd=workspace,
            )
        except FileNotFoundError:
            return ()
        return tuple(
            Removal(
                package=name,
                ecosystem=target.ecosystem,
                dev=dev,
                justification="unused (knip)",
            )
            for name, dev in parse_knip_unused(out)
        )

    async def remove_dependency(
        self, removal: Removal, workspace: Path
    ) -> None:
        """Remove the dependency from package.json + lockfile (lockfile-only).

        ``npm uninstall`` finds the dependency's section itself, so ``dev`` need
        not be passed; ``--package-lock-only --ignore-scripts`` keeps it to a
        manifest+lock rewrite with no ``node_modules`` and no scripts.
        """
        code, out, err = await run_text(
            "npm",
            "uninstall",
            removal.package,
            "--package-lock-only",
            "--ignore-scripts",
            cwd=workspace,
        )
        if code != 0:
            raise RuntimeError(f"npm uninstall failed ({code}): {err or out}")
