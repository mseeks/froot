"""The e2b sandbox adapter — runs a script against a checkout in a microVM.

A :class:`~froot.ports.protocols.Sandbox` backed by e2b (Firecracker microVMs).
froot uploads its *existing* worker checkout as a tar (so the GitHub token never
enters the sandbox), extracts it, runs the caller's ``sh`` script with the
upload as the working directory, and tears the sandbox down. The sandbox has
internet egress (to ``uv sync`` / ``npm ci`` from the registries) but no path
back into froot's cluster — the isolation boundary the worker can't provide.

The e2b SDK is imported lazily inside the method so the model/HTTP stacks (and
e2b) need not be present to import this module; tests drive the loop with an
in-memory ``FakeSandbox`` instead. The tar packing is a pure, fixture-tested
function, away from the SDK and the network.
"""

from __future__ import annotations

import io
import tarfile
from typing import TYPE_CHECKING

from froot.domain.sandbox import SandboxResult

if TYPE_CHECKING:
    from pathlib import Path

# Never ship these into the sandbox: VCS metadata and any local install trees
# (the worker does a clone-only checkout, but be defensive) — they bloat the
# upload and the sandbox re-installs from the manifest anyway.
_TAR_EXCLUDE = frozenset({".git", ".venv", "node_modules", "__pycache__"})


def workdir_tar(workdir: Path) -> bytes:
    """Pack ``workdir``'s contents into an uncompressed tar (pure).

    Entries are rooted at ``.`` so they extract into the sandbox's working
    directory; VCS/install trees in :data:`_TAR_EXCLUDE` are skipped at any
    depth so the upload stays the source + manifests + lockfile.
    """

    def _keep(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        parts = info.name.split("/")
        return None if any(part in _TAR_EXCLUDE for part in parts) else info

    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        tar.add(workdir, arcname=".", filter=_keep)
    return buffer.getvalue()


class E2bSandbox:
    """A :class:`~froot.ports.protocols.Sandbox` backed by e2b microVMs."""

    async def run(
        self, workdir: Path, script: str, *, timeout_seconds: int = 600
    ) -> SandboxResult:
        """Upload ``workdir``, run ``script`` in it, tear the sandbox down."""
        from e2b import AsyncSandbox, CommandExitException

        from froot.config.settings import E2bSettings

        settings = E2bSettings()
        if settings.api_key is None:
            raise RuntimeError(
                "FROOT_E2B_API_KEY is unset; the sandbox is not configured."
            )
        tar = workdir_tar(workdir)
        sandbox = await AsyncSandbox.create(
            template=settings.template or None,
            timeout=timeout_seconds,
            api_key=settings.api_key.get_secret_value(),
        )
        try:
            await sandbox.files.write("/tmp/work.tar", tar)
            # Extract is froot's own command, not the target's — a failure here
            # is an infrastructure fault, so let it raise.
            await sandbox.commands.run(
                "mkdir -p /work && tar -xf /tmp/work.tar -C /work",
                timeout=120,
            )
            try:
                result = await sandbox.commands.run(
                    script, cwd="/work", timeout=timeout_seconds
                )
                return SandboxResult(
                    exit_code=result.exit_code,
                    stdout=result.stdout,
                    stderr=result.stderr,
                )
            except CommandExitException as exc:
                # A non-zero script exit is the caller's to interpret (deptry
                # exits non-zero when it finds issues), not an error here.
                return SandboxResult(
                    exit_code=exc.exit_code,
                    stdout=exc.stdout,
                    stderr=exc.stderr,
                )
        finally:
            await sandbox.kill()
