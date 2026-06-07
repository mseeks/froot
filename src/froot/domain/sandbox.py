"""The sandbox result — what running a script in an isolated sandbox returns.

froot runs a target's real toolchain (install + analyze) in an isolated sandbox,
never in the worker (SPEC: no third-party code in the worker). A signal that
needs the deps installed — ``deptry`` for the uv dead-code arm — runs there.
This is the value the :class:`~froot.ports.protocols.Sandbox` port returns: the
command's exit code and captured output, nothing more. The caller parses
``stdout`` into domain values with its own pure, tested parser.
"""

from __future__ import annotations

from froot.domain.base import Frozen


class SandboxResult(Frozen):
    """The outcome of running one script in a sandbox.

    Attributes:
        exit_code: The script's exit status (0 is success).
        stdout: Captured standard output — what the caller parses.
        stderr: Captured standard error — install/build chatter and errors,
            kept off ``stdout`` so the parsed payload stays clean.
    """

    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """True iff the script exited zero."""
        return self.exit_code == 0
