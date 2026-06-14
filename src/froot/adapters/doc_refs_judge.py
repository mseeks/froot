"""The doc-refs adjudicator: is this dangling reference a real defect?

The mechanical scan flags references whose target is missing at the PR head;
what it can't decide is whether the miss is a real break the doc should fix, or
an *intentional / historical* mention (a changelog citing a removed path, a
"previously named", an illustrative example). A Pydantic AI agent reads the
candidate and returns a typed :class:`~froot.domain.doc_refs.DocRefVerdict`,
under a hard cite-or-omit rule so a ``broken`` is never a confabulation. The
model is injected, so tests run it offline with a ``TestModel``.

This module is outside the pure core and the workflow modules — the model stack
must never be imported into a Temporal workflow sandbox.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from froot.adapters.model import build_model
from froot.domain.doc_refs import DocRefVerdict

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from froot.domain.doc_refs import DocRefCandidate

_SYSTEM_PROMPT = (
    "You review a single documentation reference whose target a mechanical "
    "scan could not find at the pull request's head, for a doc-refs "
    "reviewer. The scan is precise about absence; your job is to decide "
    "whether the miss is a real defect, citing the reference.\n"
    "You are given one candidate: its kind (a broken link, a missing file "
    "path, or a removed make target), the referent that resolved to "
    "nothing, the doc line it sits on, and whether THIS pull request "
    "removed or renamed the target.\n"
    "Classify into exactly one bucket:\n"
    "- broken: a real dangling reference the doc should be fixed to match "
    "reality. If the PR itself removed/renamed the target, it is almost "
    "certainly this.\n"
    "- intentional: the reference is deliberately to something that does "
    "not exist in the tree — a changelog or history note citing an "
    "old/removed path, a 'previously named X', a placeholder or "
    "illustrative example, or an external thing the scan mistook for a repo "
    "path. The doc is fine as-is.\n"
    "- judgment: genuinely ambiguous — whether the doc should change is an "
    "authoring call.\n"
    "CITE OR OMIT (hard rule): a 'broken' verdict MUST quote, in citation, "
    "the exact reference substring from the line. If you cannot quote it, "
    "you may NOT return 'broken' — return 'intentional' or 'judgment'.\n"
    "For a 'broken', put the next step in action (e.g. update the link to "
    "the new path; drop the stale reference). Keep rationale to one or two "
    "sentences. No stylistic preferences — only reference integrity."
)


class _DocRefAssessment(BaseModel):
    """The model's structured output, mapped to a domain verdict."""

    bucket: Literal["broken", "intentional", "judgment"]
    rationale: str = Field(min_length=1)
    citation: str = ""
    action: str = ""


class DocRefsJudge:
    """Adjudicates doc-ref candidates with a Pydantic AI agent."""

    def __init__(self, model: Model | None = None) -> None:
        """Build the agent; ``model`` defaults to the configured Ollama."""
        self._agent: Agent[None, _DocRefAssessment] = Agent(
            model or build_model(),
            output_type=_DocRefAssessment,
            system_prompt=_SYSTEM_PROMPT,
        )

    async def adjudicate(self, candidate: DocRefCandidate) -> DocRefVerdict:
        """Judge whether one dangling reference is a real defect."""
        removed = (
            "This PR removed or renamed the target.\n"
            if candidate.broken_by_pr
            else "This PR did not touch the target.\n"
        )
        prompt = (
            f"Kind: {candidate.kind}\n"
            f"Referent (resolves to nothing): {candidate.referent}\n"
            f"Doc line {candidate.line}: {candidate.snippet}\n"
            f"{removed}"
            "Is this a real broken reference? Quote the exact reference if you "
            "call it broken."
        )
        result = await self._agent.run(prompt)
        return DocRefVerdict(
            bucket=result.output.bucket,
            rationale=result.output.rationale,
            citation=result.output.citation,
            action=result.output.action,
        )
