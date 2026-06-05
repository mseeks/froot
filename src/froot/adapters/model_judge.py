"""The thin model judgment: is this changelog a clean patch?

froot's changelog model call — one of two (the determinism reviewer's frontier
judge is the other). A Pydantic AI agent reads the changelog and returns a
typed :class:`_Assessment`, which :func:`assessment_to_verdict` maps to the
domain :data:`~froot.domain.changelog.ChangelogVerdict`. The verdict is framing,
not a gate — the spine proposes the bump regardless — so even a "risky" reading
just shapes the PR. The model is injected, so tests run it offline with a
``TestModel`` / ``FunctionModel``; the mapping is a pure function, tested apart
from any model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, assert_never

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from froot.adapters.model import build_model
from froot.domain.changelog import (
    CleanVerdict,
    RiskyVerdict,
    UnknownVerdict,
)

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from froot.domain.changelog import Changelog, ChangelogVerdict

_SYSTEM_PROMPT = (
    "You assess the changelog of a dependency's PATCH-level upgrade for a "
    "code-maintenance bot. The bot proposes the bump either way; your job is "
    "only to frame the risk for the human reviewer.\n"
    "Return one verdict:\n"
    "- clean: the notes describe only fixes / docs / internal changes with no "
    "behavioral or API impact.\n"
    "- risky: the notes hint at behavior change, deprecations, or anything a "
    "reviewer should look at closely; list the concerns.\n"
    "- unknown: the notes are empty or uninformative.\n"
    "Quote-or-omit: base 'risky' concerns on what the text actually says; do "
    "not speculate. Keep the rationale to one or two sentences."
)


class _Assessment(BaseModel):
    """The model's structured output, mapped to a domain verdict."""

    verdict: Literal["clean", "risky", "unknown"]
    rationale: str
    concerns: list[str] = Field(default_factory=list)


def assessment_to_verdict(assessment: _Assessment) -> ChangelogVerdict:
    """Map the model's structured assessment to a domain verdict (pure)."""
    match assessment.verdict:
        case "clean":
            return CleanVerdict(rationale=assessment.rationale)
        case "risky":
            return RiskyVerdict(
                rationale=assessment.rationale,
                concerns=tuple(assessment.concerns),
            )
        case "unknown":
            return UnknownVerdict(rationale=assessment.rationale)
    assert_never(assessment.verdict)


class PydanticAiJudge:
    """A :class:`~froot.ports.protocols.ModelJudge` backed by Pydantic AI."""

    def __init__(self, model: Model | None = None) -> None:
        """Build the agent; ``model`` defaults to the configured Ollama."""
        self._agent: Agent[None, _Assessment] = Agent(
            model or build_model(),
            output_type=_Assessment,
            system_prompt=_SYSTEM_PROMPT,
        )

    async def judge(self, changelog: Changelog) -> ChangelogVerdict:
        """Assess a changelog and return a typed verdict."""
        prompt = (
            f"Package: {changelog.package}\n"
            f"Target version: {changelog.version}\n"
            f"Changelog:\n{changelog.text}"
        )
        result = await self._agent.run(prompt)
        return assessment_to_verdict(result.output)
