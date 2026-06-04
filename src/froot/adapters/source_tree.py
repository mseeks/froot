"""Load a checked-out repo's first-party modules for the determinism analyzer.

The I/O boundary for the transitive pass: walk the source tree, parse each
``.py`` into an AST, and key it by dotted qualname so the analyzer can resolve
first-party imports (``from pkg.mod import helper``) to a definition. Detects a
``src/`` layout (froot, ynab-agent) and falls back to top-level packages at the
repo root. Files that fail to read or parse are skipped — a best-effort map is
better than no analysis.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from froot.policy.determinism import LoadedModule

if TYPE_CHECKING:
    from pathlib import Path


def _source_root(repo: Path) -> Path:
    """The directory packages live under: ``src/`` if present, else the root."""
    src = repo / "src"
    return src if src.is_dir() else repo


def _qualname(path: Path, root: Path) -> str:
    """The dotted module name for ``path`` relative to the package ``root``."""
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def load_modules(repo: Path) -> dict[str, LoadedModule]:
    """Parse every first-party module under ``repo``, keyed by qualname."""
    root = _source_root(repo)
    packages = sorted(p.parent for p in root.glob("*/__init__.py"))
    modules: dict[str, LoadedModule] = {}
    for package in packages:
        for path in sorted(package.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text, filename=str(path))
            except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
                continue
            qual = _qualname(path, root)
            modules[qual] = LoadedModule(
                qualname=qual, tree=tree, lines=tuple(text.splitlines())
            )
    return modules
