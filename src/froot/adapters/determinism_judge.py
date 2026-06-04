"""The frontier adjudicator: does a risky import actually reach the workflow?

The static analyzer resolves the call paths it can. What it can't decide — a
risky third-party import at a workflow module's scope (is it reached from
workflow code, or dead weight?) — is the model's frontier. A Pydantic AI agent
returns a typed :class:`_FrontierAssessment`, mapped to a domain
:class:`~froot.domain.determinism.FrontierVerdict`. Lean on the static graph;
the model only adjudicates the ambiguity. The model is injected, so tests run it
offline with a ``TestModel`` / ``FunctionModel``.

This module is outside the pure core and the workflow modules — the model stack
must never be imported into a Temporal workflow sandbox.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from froot.adapters.model import build_model
from froot.domain.determinism import FrontierVerdict

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from froot.domain.determinism import FrontierItem

_SYSTEM_PROMPT = (
    "You review Python for a Temporal workflow determinism checker. A workflow "
    "must replay deterministically: wall-clock, randomness, env, network, and "
    "file/subprocess I/O are forbidden in workflow code and must live in "
    "activities. You are given a risky third-party import found at the module "
    "scope of a file that defines a @workflow.defn workflow.\n"
    "Decide whether that import is actually *reached from the workflow's own "
    "code* (so it would run during replay and break determinism).\n"
    "Return one verdict:\n"
    "- yes: workflow code uses the import (directly or via a same-module "
    "helper) — a real determinism hazard.\n"
    "- no: the import is unused by workflow code, or only used by activities / "
    "module-level constants — not a hazard.\n"
    "- uncertain: you cannot tell from the given context.\n"
    "Base the verdict on the evidence; keep the rationale to one or two "
    "sentences."
)


class _FrontierAssessment(BaseModel):
    """The model's structured output, mapped to a domain verdict."""

    reaches: Literal["yes", "no", "uncertain"]
    rationale: str = Field(min_length=1)


class DeterminismFrontierJudge:
    """Adjudicates frontier items with a Pydantic AI agent."""

    def __init__(self, model: Model | None = None) -> None:
        """Build the agent; ``model`` defaults to the configured Ollama."""
        self._agent: Agent[None, _FrontierAssessment] = Agent(
            model or build_model(),
            output_type=_FrontierAssessment,
            system_prompt=_SYSTEM_PROMPT,
        )

    async def adjudicate(self, item: FrontierItem) -> FrontierVerdict:
        """Judge whether a frontier item reaches workflow nondeterminism."""
        prompt = (
            f"Module: {item.module}\n"
            f"Workflow defined here: {item.workflow}\n"
            f"Risky import (line {item.line}): {item.snippet or item.symbol}\n"
            "Does the workflow's own code reach this import?"
        )
        result = await self._agent.run(prompt)
        return FrontierVerdict(
            reaches=result.output.reaches,
            rationale=result.output.rationale,
        )
