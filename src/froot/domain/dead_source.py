"""Dead source: the work-item kinds the dead-code loop deletes from the source.

The dead-code loop began on one shape of dead weight — an unused *dependency*
(:class:`~froot.domain.removal.Removal`). These two kinds finish it out to the
rest of MHE's dead-code catalog: dead *code*. A static analyzer (knip) that
already maps the import graph reports two further shapes of deadness:

* :class:`DeadFile` — a whole module nothing imports. The action deletes the
  file; CI is the oracle (a build that still needs it goes red).
* :class:`DeadExport` — a symbol exported but imported by no other module. knip
  flags "does not need to be exported", not "dead everywhere", so the safe,
  reversible action is to *un-export* it (strip the ``export`` modifier),
  leaving it module-private. Cross-module use the analyzer missed surfaces as a
  red CI; in-file use is untouched.

Both are *signal-judged* like a removal — a safe-to-remove veto runs at the
signal, there is no changelog to read — and neither carries a version, so like a
removal they set ``reconciles=False`` and never touch the forward-stable
invariant a candidate must satisfy. They are separate kinds (not one shape with
an optional symbol) so each is valid by construction: a file deletion has no
symbol, an un-export must name one.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.ecosystem import Ecosystem


class DeadFile(Frozen):
    """A proposed deletion of a single unused source file.

    Attributes:
        kind: The work-item discriminator — always ``"dead_file"``.
        path: The file to delete, relative to the manifest directory the
            analyzer ran in (where the action resolves it against the checkout).
        ecosystem: The ecosystem whose analyzer flagged it (namespacing only;
            the deletion itself is language-agnostic).
        justification: A short "why" — the analyzer's finding plus the
            safe-to-remove veto's reasoning; carried to the PR body.
    """

    kind: Literal["dead_file"] = "dead_file"
    path: str = Field(min_length=1)
    ecosystem: Ecosystem
    justification: str | None = None

    @property
    def subject(self) -> str:
        """The work item's human-readable identifier (its path)."""
        return self.path

    def __str__(self) -> str:
        """Render as ``delete path (unused)``."""
        return f"delete {self.path} (unused)"


class DeadExport(Frozen):
    """A proposed un-export of a single unused exported symbol.

    The action strips the ``export`` modifier on ``file`` at ``line`` — a
    one-line edit that leaves the symbol in place but module-private. The signal
    only ever emits the un-exportable inline declaration forms (``export
    function/const/class/…``); clause re-exports, ``export default``, and
    ``export *`` are dropped at the signal because un-exporting them is not a
    single-line edit (see :func:`froot.policy.dead_source.unexport_line`).

    Attributes:
        kind: The work-item discriminator — always ``"dead_export"``.
        file: The source file holding the export, relative to the manifest dir.
        symbol: The exported name the analyzer flagged as unused cross-module.
        line: The 1-based line of the export declaration (the analyzer's
            position; the action re-checks it names ``symbol`` before acting).
        ecosystem: The ecosystem whose analyzer flagged it (namespacing).
        justification: A short "why" — the analyzer's finding plus the veto's
            reasoning; carried to the PR body.
    """

    kind: Literal["dead_export"] = "dead_export"
    file: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    line: int = Field(gt=0)
    ecosystem: Ecosystem
    justification: str | None = None

    @property
    def subject(self) -> str:
        """The work item's human-readable identifier (its symbol)."""
        return self.symbol

    def __str__(self) -> str:
        """Render as ``un-export symbol in file (unused)``."""
        return f"un-export {self.symbol} in {self.file} (unused)"
