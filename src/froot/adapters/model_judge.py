"""The thin model judgment: how risky is this dependency bump's changelog?

froot's one model call. A Pydantic AI agent reads the changelog and returns a
typed :class:`_Assessment`, which :func:`assessment_to_verdict` maps to the
domain :data:`~froot.domain.changelog.ChangelogVerdict`. The verdict is framing,
not a gate — the spine proposes the bump regardless — so even a "risky" reading
just shapes the PR. The *loop* shapes what the model is asked: a patch bump asks
"is this clean?", a security bump (often a minor/major) asks "what breaks?". The
model is injected, so tests run it offline with a ``TestModel`` /
``FunctionModel``; the mapping is a pure function, tested apart from any model.
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
from froot.domain.loop import Loop

if TYPE_CHECKING:
    from pydantic_ai.models import Model

    from froot.domain.changelog import Changelog, ChangelogVerdict

_SYSTEM_PROMPT = (
    "You assess the changelog of a dependency upgrade for a code-maintenance "
    "bot. The bot proposes the bump either way; your job is only to frame the "
    "risk for the human reviewer.\n"
    "Return one verdict:\n"
    "- clean: the notes describe only fixes / docs / internal changes with no "
    "behavioral or API impact.\n"
    "- risky: the notes hint at behavior change, deprecations, or anything a "
    "reviewer should look at closely; list the concerns.\n"
    "- unknown: the notes are empty or uninformative.\n"
    "Quote-or-omit: base 'risky' concerns on what the text actually says; do "
    "not speculate. Keep the rationale to one or two sentences."
)

# The gate reviewer's stance is adversarial and asymmetric: this bump is about
# to merge with NO human in the loop, so the burden is on the changelog to prove
# it is safe, not on the reviewer to prove it is dangerous. The same _Assessment
# shape, read as approve/hold (clean = approve).
_GATE_SYSTEM_PROMPT = (
    "You are the LAST line of defense before a dependency upgrade auto-merges "
    "with no human review. Re-read the changelog adversarially and decide "
    "whether it is safe to merge unattended.\n"
    "Return one verdict:\n"
    "- clean: ONLY if the notes clearly describe nothing beyond fixes / docs / "
    "internal changes — no behavioral change, no API change, no deprecation, "
    "no ambiguity. This approves the merge.\n"
    "- risky: any hint of behavior change, removal, deprecation, or surface a "
    "reviewer should see; list the concerns. This holds the PR.\n"
    "- unknown: the notes are empty, uninformative, or you are unsure. This "
    "holds the PR.\n"
    "The burden is on the changelog to prove safety: when in doubt, do NOT "
    "return clean. Base concerns on what the text says; keep it to one or two "
    "sentences."
)


def _loop_context(loop: Loop) -> str:
    """The one line that tells the model what kind of bump it is judging."""
    match loop:
        case Loop.DEPENDENCY_PATCH:
            return (
                "This is a patch-level upgrade; weigh whether the notes hide "
                "any behavioral change behind a 'patch'."
            )
        case Loop.SECURITY_PATCH:
            return (
                "This is a SECURITY upgrade that may cross a minor or major "
                "line to clear a vulnerability; weigh breaking changes the "
                "human should know before merging — the fix is still worth it."
            )
    assert_never(loop)


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


def _gate_model() -> Model:
    """Build the gate reviewer's model: the override, else the judge model."""
    from froot.config.settings import ModelSettings

    return build_model(model_name=ModelSettings().gate_review_model or None)


def _changelog_prompt(changelog: Changelog, loop: Loop) -> str:
    """The shared user prompt: the bump's context and its changelog text."""
    return (
        f"{_loop_context(loop)}\n"
        f"Package: {changelog.package}\n"
        f"Target version: {changelog.version}\n"
        f"Changelog:\n{changelog.text}"
    )


class PydanticAiJudge:
    """A :class:`~froot.ports.protocols.ModelJudge` backed by Pydantic AI.

    Two agents share the structured ``_Assessment`` output but differ in stance:
    the neutral framing judge (:meth:`judge`) and the adversarial gate reviewer
    (:meth:`gate_review`), each its own model so a steward can make the deep
    review independent in capability, not just prompt.
    """

    def __init__(
        self, model: Model | None = None, gate_model: Model | None = None
    ) -> None:
        """Build both agents.

        ``model`` defaults to the configured Ollama; ``gate_model`` to the
        gate-review override, else ``model``, else the gate-review model.
        """
        self._agent: Agent[None, _Assessment] = Agent(
            model or build_model(),
            output_type=_Assessment,
            system_prompt=_SYSTEM_PROMPT,
        )
        self._gate_agent: Agent[None, _Assessment] = Agent(
            gate_model or model or _gate_model(),
            output_type=_Assessment,
            system_prompt=_GATE_SYSTEM_PROMPT,
        )

    async def judge(
        self, changelog: Changelog, loop: Loop = Loop.DEPENDENCY_PATCH
    ) -> ChangelogVerdict:
        """Assess a changelog into a verdict, framed by the loop."""
        result = await self._agent.run(_changelog_prompt(changelog, loop))
        return assessment_to_verdict(result.output)

    async def gate_review(
        self, changelog: Changelog, loop: Loop = Loop.DEPENDENCY_PATCH
    ) -> ChangelogVerdict:
        """Adversarially re-review a bump at the gate (clean = approve)."""
        result = await self._gate_agent.run(_changelog_prompt(changelog, loop))
        return assessment_to_verdict(result.output)
