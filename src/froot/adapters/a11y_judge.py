"""The a11y adjudicator: is this flagged site a real source-level defect?

The mechanical scan flags candidate risk sites; what it can't decide — whether
the accessible name / label / keyboard path / alt is actually present (often on
an adjacent line, or wired by id at a distance) — is the model's frontier. A
Pydantic AI agent reads the candidate in context and returns a typed
:class:`~froot.domain.a11y.A11yVerdict`. Lean on the scan; the model only
adjudicates the ambiguity, under a hard cite-or-omit rule so a "gap" is never a
confabulation. The model is injected, so tests run it offline with a
``TestModel`` / ``FunctionModel``.

This module is outside the pure core and the workflow modules — the model stack
must never be imported into a Temporal workflow sandbox.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from froot.adapters.model import build_model
from froot.domain.a11y import A11yVerdict

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from froot.domain.a11y import A11yCandidate

_SYSTEM_PROMPT = (
    "You review a single accessibility risk site found in a web template, in "
    "context, for a source-level a11y reviewer. The mechanical scan flags "
    "candidates; your job is to confirm whether each is a REAL defect, citing "
    "the source.\n"
    "You are given one candidate: its kind, the UI dialect (Vue or JSX/React), "
    "the flagged line, and a window of source. The accessible name, "
    "label, keyboard handler, or alt is OFTEN on an ADJACENT line in that "
    "window — read it before judging. Default to 'ok' unless the window proves "
    "a gap.\n"
    "Dialect notes. Vue: @click / @keydown.enter / :aria-label / aria-label / "
    "aria-labelledby / tabindex / :alt / alt / <label for>. JSX/React: onClick "
    "/ onKeyDown / aria-label / aria-labelledby / tabIndex / alt / htmlFor. "
    "Natively interactive (keyboard-operable for free): button, a[href], "
    "input, select, textarea, summary, label.\n"
    "Classify into exactly one bucket:\n"
    "- gap: a real source-level a11y defect. role=img/<svg> with NO accessible "
    "name (no aria-label/aria-labelledby/<title>) and not decorative "
    "(aria-hidden); a labelable control with NO associated label (no "
    "aria-label, no <label for=id> wiring, no aria-labelledby); a "
    "non-interactive element (<div>/<span>/<li>/...) with a click handler but "
    "NO keyboard path (no role + tabindex + @keydown/onKeyDown — a partial "
    "contract like keydown.enter without keydown.space is still a gap); an "
    "<img>/:src with NO alt attribute at all (note: an empty "
    'alt="" is the intentional decorative case — that is "ok", not a gap).\n'
    "- ok: the element is accessible — quote the attribute that names/labels/"
    "operates it, or note it is decorative (aria-hidden beside visible text, "
    'or an <img>/:src with alt=""), or the click is actually on a native '
    "control the backward scan mis-attributed.\n"
    "- judgment: genuinely ambiguous — the fix is a design call "
    "(decorative-vs-meaningful svg, a half-applied ARIA pattern, an unclear "
    "existing name).\n"
    "CITE OR OMIT (hard rule): a 'gap' verdict MUST quote, in citation, the "
    "exact element or attribute substring you observed in the provided source. "
    "If you cannot quote it, you may NOT return 'gap' — return 'ok' or "
    "'judgment'. Do not infer from what an unlabeled control 'usually' looks "
    "like.\n"
    "For a 'gap', put the next step in action (e.g. add :aria-label to "
    "the svg; add @keydown.space beside @keydown.enter; give the range an "
    "aria-label; add :alt to the img). Keep rationale to one or two sentences "
    "(the user impact)."
)


class _A11yAssessment(BaseModel):
    """The model's structured output, mapped to a domain verdict."""

    bucket: Literal["gap", "ok", "judgment"]
    rationale: str = Field(min_length=1)
    citation: str = ""
    action: str = ""


class A11ySourceJudge:
    """Adjudicates a11y candidates with a Pydantic AI agent."""

    def __init__(self, model: Model | None = None) -> None:
        """Build the agent; ``model`` defaults to the configured Ollama."""
        self._agent: Agent[None, _A11yAssessment] = Agent(
            model or build_model(),
            output_type=_A11yAssessment,
            system_prompt=_SYSTEM_PROMPT,
        )

    async def adjudicate(self, candidate: A11yCandidate) -> A11yVerdict:
        """Judge whether one flagged site is a real a11y gap, in context."""
        wired = (
            "An id-wired <label for>/aria-labelledby was found for this "
            "control.\n"
            if candidate.label_wired
            else ""
        )
        prompt = (
            f"Kind: {candidate.kind}\n"
            f"Dialect: {candidate.dialect}\n"
            f"Flagged element: {candidate.detail or '(see line)'}\n"
            f"Flagged line {candidate.line}: {candidate.snippet}\n"
            f"{wired}"
            "\nSurrounding source:\n"
            f"```\n{candidate.context}\n```\n"
            "Is this a real a11y defect? Cite the exact substring if you call "
            "it a gap."
        )
        result = await self._agent.run(prompt)
        return A11yVerdict(
            bucket=result.output.bucket,
            rationale=result.output.rationale,
            citation=result.output.citation,
            action=result.output.action,
        )
