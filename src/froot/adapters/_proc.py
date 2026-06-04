"""A small async subprocess helper shared by the tool-backed adapters.

``npm`` and ``git`` are blocking CLIs; this runs them off the event loop and
returns their exit code plus captured stdout and stderr, so the adapters stay
free of process plumbing.
"""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

# Scrub URL userinfo (e.g. a token in an authed git remote) so credentials can
# never reach a RuntimeError message or Temporal history via captured output.
_USERINFO = re.compile(r"://[^@/\s]+@")


async def run_text(*args: str, cwd: Path) -> tuple[int, str, str]:
    """Run ``args`` in ``cwd``; return ``(exit_code, stdout, stderr)``.

    Both streams are captured separately and returned redacted. stdout stays
    clean for callers that parse it (``npm view`` JSON, ``git rev-parse``
    SHA); stderr -- where ``uv``/``git``/``npm`` write their real error
    output -- is returned too, so failures aren't opaque (callers fold it
    into the RuntimeError). ``user:pass@`` URL userinfo is redacted.
    """
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate()
    return (
        process.returncode or 0,
        _USERINFO.sub("://***@", out.decode()),
        _USERINFO.sub("://***@", err.decode()),
    )
