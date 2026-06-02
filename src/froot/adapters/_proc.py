"""A small async subprocess helper shared by the tool-backed adapters.

``npm`` and ``git`` are blocking CLIs; this runs them off the event loop and
returns their exit code and captured stdout, so the adapters stay free of
process plumbing.
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


async def run_text(*args: str, cwd: Path) -> tuple[int, str]:
    """Run ``args`` in ``cwd``; return ``(exit_code, redacted_stdout)``.

    stderr is captured but discarded — adapters surface failures via the exit
    code and a domain-level message, not raw tool chatter. Any ``user:pass@``
    URL userinfo in stdout is redacted as a defense-in-depth measure.
    """
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await process.communicate()
    return process.returncode or 0, _USERINFO.sub("://***@", out.decode())
