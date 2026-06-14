"""The doc-coherence agent: frame the read-only executor to map semantic drift.

doc-coherence's action is the agentic executor (read the docs against the code).
This module frames it — the system prompt (read-only, three-bucket,
cite-or-omit, no stylistic nitpicks), the output schema, and the mapping to
domain items.
The model is injected, so tests run it offline; the executor jails it to the
checkout. This module lives outside the pure core and the workflow modules — the
model stack must never enter a Temporal workflow sandbox.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from froot.adapters.agentic_executor import run_readonly_agent
from froot.domain.doc_coherence import DocCoherenceItem

if TYPE_CHECKING:
    from pathlib import Path

    from pydantic_ai.models import Model

_SYSTEM_PROMPT = (
    "You are the doc-coherence reviewer for a code project. You are READ-ONLY: "
    "you map documentation drift; you never edit. A human acts on your map.\n"
    "Using the read-only tools (read_file, grep, find), read the docs "
    "against the ACTUAL code and find SEMANTIC drift: claims about code, "
    "architecture, commands, types, or behavior that no longer match reality. "
    "Ignore pure formatting and wording style.\n"
    "Return a list of items, each in exactly one bucket:\n"
    "- drift: a real mismatch between a doc and current reality. Put the wrong "
    "claim in 'what', why it misleads in 'why', the fix in 'action', "
    "and the doc location (a file:line or the exact quoted line) in "
    "'citation'.\n"
    "- ok: something you verified that is actually correct (you may omit "
    "these).\n"
    "- judgment: a possible drift whose resolution needs an authoring call.\n"
    "CITE OR OMIT (hard rule): a 'drift' item MUST quote, in citation, the "
    "exact doc text or file:line you observed. If you cannot quote it, do NOT "
    "return 'drift'. Never invent a claim or a reference. Be terse — a "
    "map, not an essay."
)

_TASK = (
    "Review this repository's documentation against its code for semantic "
    "drift. Find the docs (try find('**/*.md')), read them, and verify their "
    "claims against the code with read_file and grep. Return the three-bucket "
    "map; quote every 'drift'."
)


class _DocItemOut(BaseModel):
    """One item of the model's structured output."""

    bucket: Literal["drift", "ok", "judgment"]
    what: str = ""
    why: str = ""
    action: str = ""
    citation: str = ""


class _DocMapOut(BaseModel):
    """The model's full structured output — the drift map."""

    items: list[_DocItemOut] = Field(default_factory=list)


async def map_doc_coherence(
    *, model: Model, checkout: Path, max_requests: int
) -> tuple[tuple[DocCoherenceItem, ...], str]:
    """Run the read-only agent to map semantic doc drift.

    Returns ``(items, status)``; an ``ended-early`` status yields no items so a
    down model degrades to a "couldn't complete" comment rather than stalling.
    """
    output, status = await run_readonly_agent(
        model=model,
        root=checkout,
        system_prompt=_SYSTEM_PROMPT,
        task=_TASK,
        output_type=_DocMapOut,
        max_requests=max_requests,
    )
    if output is None:
        return (), status
    items = tuple(
        DocCoherenceItem(
            bucket=raw.bucket,
            what=raw.what,
            why=raw.why,
            action=raw.action,
            citation=raw.citation,
        )
        for raw in output.items
    )
    return items, status
