"""Domain types for the doc-coherence reviewer (the agentic semantic mapper).

doc-refs catches mechanical reference breakage; doc-coherence catches SEMANTIC
drift — a doc claiming something about the code, architecture, or behavior that
no longer matches reality. No regex sees it, so the loop's action is the
read-only agentic executor: a model reads the docs against the code and returns
a three-bucket map (drift / ok / judgment), cite-or-omit. It never edits — a
human fixes the doc.

Frozen so the findings serialize across the Temporal boundary (the agent runs in
an activity; its result rides back to the deterministic workflow). The agent's
raw model-output schema is the adapter's private concern.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from froot.domain.base import Frozen

DocCoherenceBucket = Literal["drift", "ok", "judgment"]
"""The agent's three readings: confirmed drift, not-drift (fine), or a judgment
call the human must make."""


class DocCoherenceItem(Frozen):
    """One reading the agent returned, before cite-or-omit filtering.

    The model's structured output, mapped into the domain. A ``drift`` only
    becomes a finding when it carries a citation (enforced in synthesis).
    """

    bucket: DocCoherenceBucket
    what: str = ""
    """The doc claim / location the agent flagged."""
    why: str = ""
    """The mismatch with reality (drift) or the ambiguity (judgment)."""
    action: str = ""
    citation: str = ""
    """The exact doc text or ``file:line`` quoted — a drift MUST carry one."""


class DocCoherenceFinding(Frozen):
    """A surfaced finding — one item of the advisory comment.

    Only ``drift`` (with a citation — cite-or-omit) and ``judgment`` reach here;
    an ``ok`` is dropped.
    """

    bucket: Literal["drift", "judgment"]
    what: str = Field(min_length=1)
    why: str = Field(min_length=1)
    action: str = ""
    citation: str = ""


class DocCoherenceRun(Frozen):
    """The agent activity's output: the mapped items + the run status.

    Crosses the Temporal boundary back to the workflow, which synthesizes the
    findings (pure) and records whether the run completed.
    """

    items: tuple[DocCoherenceItem, ...] = ()
    status: str = "completed"


class PrDocCoherenceResult(Frozen):
    """The loop's recorded outcome for one PR review (a derived ledger row)."""

    pr_number: int = Field(ge=1)
    head_sha: str = Field(min_length=7)
    run_status: str
    findings: tuple[DocCoherenceFinding, ...] = ()
    comment_url: str | None = None
