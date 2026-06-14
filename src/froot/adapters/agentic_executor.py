"""froot's read-only agentic executor — a bounded, tool-using model run.

The heavier "action" some loops need: a model that doesn't make one thin
judgment but RANGES over a checkout (read files, grep, glob) to reason, then
returns a structured result. froot's first user is the doc-coherence reviewer,
which reads docs against code to find semantic drift.

Deliberately bounded and READ-ONLY: the tools can only read inside the checkout,
never write, and never read secrets (``.env`` / ``.git`` / keys are denied), and
the run is capped at a hard request ceiling so a runaway reasoning loop can't
burn the worker. The design is borrowed from the pydantic-ai-harness FileSystem
capability (whose published package is still a stub), hand-rolled here on
pydantic-ai so froot owns the jail and adds no churny dependency.

This is froot's first step toward the fabrication executor VISION defers —
named, not generalized from one example. It runs ENTIRELY inside one activity
(the model and tool calls are nondeterministic), so it never touches a workflow
body; the determinism gates enforce that. The model is injected, so tests run
it offline.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.usage import UsageLimits

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from pydantic_ai.models import Model

# Directories never worth reading (and never descended into).
_SKIP = frozenset({".git", "node_modules", ".venv", "__pycache__"})
_READ_MAX_LINES = 400
_GREP_MAX_HITS = 80
_FIND_MAX = 200
_SNIPPET = 200


def _denied(rel_parts: tuple[str, ...]) -> bool:
    """Whether any path segment is a skip dir or a secret (never readable)."""
    for part in rel_parts:
        low = part.lower()
        if (
            part in _SKIP
            or low == ".env"
            or low.startswith(".env.")
            or low.endswith((".key", ".pem"))
            or "secret" in low
        ):
            return True
    return False


def _resolve(root: Path, rel: str) -> Path | None:
    """Resolve ``rel`` inside the jail; ``None`` if out of scope or denied."""
    base = root.resolve()
    candidate = (base / rel).resolve()
    try:
        parts = candidate.relative_to(base).parts
    except ValueError:
        return None  # escaped the checkout root
    if _denied(parts):
        return None
    return candidate


def _walk(root: Path) -> Iterator[Path]:
    """Yield readable files under ``root``, pruning skip dirs and secrets."""
    base = root.resolve()
    for dirpath, dirs, files in os.walk(base):
        dirs[:] = [
            d
            for d in dirs
            if d not in _SKIP and not d.lower().startswith(".env")
        ]
        for name in files:
            path = Path(dirpath) / name
            if not _denied(path.relative_to(base).parts):
                yield path


def _tools(root: Path) -> list[Callable[[str], str]]:
    """The read-only file tools, jailed to ``root`` (read / grep / glob)."""
    base = root.resolve()

    def read_file(path: str) -> str:
        """Read a UTF-8 text file inside the repo, with 1-based line numbers."""
        target = _resolve(root, path)
        if target is None or not target.is_file():
            return f"error: {path!r} is not a readable file in scope"
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return f"error: cannot read {path!r}"
        shown = lines[:_READ_MAX_LINES]
        body = "\n".join(f"{i + 1}: {line}" for i, line in enumerate(shown))
        if len(lines) > _READ_MAX_LINES:
            body += f"\n... ({len(lines) - _READ_MAX_LINES} more lines)"
        return body or "(empty file)"

    def grep(pattern: str) -> str:
        """Regex-search file contents across the repo; return file:line hits."""
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"error: bad regex: {exc}"
        hits: list[str] = []
        for file in _walk(root):
            try:
                lines = file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            rel = file.relative_to(base).as_posix()
            for num, line in enumerate(lines, start=1):
                if rx.search(line):
                    hits.append(f"{rel}:{num}: {line.strip()[:_SNIPPET]}")
                    if len(hits) >= _GREP_MAX_HITS:
                        return "\n".join(hits) + "\n... (truncated)"
        return "\n".join(hits) if hits else "(no matches)"

    def find(glob: str) -> str:
        """Glob filenames across the repo, e.g. ``**/*.py`` or ``docs/*.md``."""
        try:
            matches = sorted(base.glob(glob))
        except (ValueError, OSError) as exc:
            return f"error: bad glob {glob!r}: {exc}"
        out: list[str] = []
        for path in matches:
            rel = path.relative_to(base)
            if _denied(rel.parts):
                continue
            out.append(rel.as_posix())
            if len(out) >= _FIND_MAX:
                out.append("... (truncated)")
                break
        return "\n".join(out) if out else "(no matches)"

    return [read_file, grep, find]


async def run_readonly_agent[T](
    *,
    model: Model,
    root: Path,
    system_prompt: str,
    task: str,
    output_type: type[T],
    max_requests: int,
) -> tuple[T | None, str]:
    """Run a bounded, read-only tool-using agent over ``root``.

    Returns the structured output and ``"completed"`` on success, or ``None``
    and an ``"ended-early: …"`` status when the request cap trips or the model
    errors — a down model must degrade, never stall the loop. Reads only inside
    ``root`` (secrets denied).
    """
    agent = Agent(
        model,
        output_type=output_type,
        system_prompt=system_prompt,
        tools=_tools(root),
    )
    try:
        result = await agent.run(
            task, usage_limits=UsageLimits(request_limit=max_requests)
        )
    except UsageLimitExceeded:
        return None, "ended-early: request limit reached"
    except Exception as exc:
        return None, f"ended-early: {exc!r}"
    return result.output, "completed"
