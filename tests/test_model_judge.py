from __future__ import annotations

from pydantic_ai.models.test import TestModel

from froot.adapters.model_judge import (
    PydanticAiJudge,
    _Assessment,
    assessment_to_verdict,
)
from froot.domain.changelog import (
    Changelog,
    CleanVerdict,
    RiskyVerdict,
    UnknownVerdict,
)
from tests.support import (
    make_dead_export,
    make_dead_file,
    make_removal,
    ver,
)


def test_assessment_to_verdict_clean():
    verdict = assessment_to_verdict(
        _Assessment(verdict="clean", rationale="just fixes")
    )
    assert isinstance(verdict, CleanVerdict)


def test_assessment_to_verdict_risky_carries_concerns():
    verdict = assessment_to_verdict(
        _Assessment(verdict="risky", rationale="api", concerns=["renamed x"])
    )
    assert isinstance(verdict, RiskyVerdict)
    assert verdict.concerns == ("renamed x",)


def test_assessment_to_verdict_unknown():
    verdict = assessment_to_verdict(
        _Assessment(verdict="unknown", rationale="empty")
    )
    assert isinstance(verdict, UnknownVerdict)


async def test_judge_wires_through_a_model_offline():
    judge = PydanticAiJudge(model=TestModel())
    changelog = Changelog(
        package="left-pad", version=ver("1.4.3"), text="Fixed a typo."
    )
    verdict = await judge.judge(changelog)
    assert verdict.kind in {"clean", "risky", "unknown"}


async def test_gate_review_wires_through_its_own_model_offline():
    # The gate reviewer is a second agent; an injected model drives it offline,
    # and a separate gate_model overrides only that agent.
    judge = PydanticAiJudge(model=TestModel(), gate_model=TestModel())
    changelog = Changelog(
        package="left-pad", version=ver("1.4.3"), text="Fixed a typo."
    )
    verdict = await judge.gate_review(changelog)
    assert verdict.kind in {"clean", "risky", "unknown"}


async def test_judge_removal_wires_through_a_model_offline():
    # The safe-to-remove judge is a third agent over the shared _Assessment
    # shape; an injected model drives it offline (no changelog needed).
    judge = PydanticAiJudge(model=TestModel())
    verdict = await judge.judge_removal(make_removal(package="left-pad"))
    assert verdict.kind in {"clean", "risky", "unknown"}


async def test_judge_dead_source_wires_through_a_model_offline():
    # The dead-source veto is a fourth agent over the shared _Assessment shape,
    # asked about a file or an export; an injected model drives it offline.
    judge = PydanticAiJudge(model=TestModel())
    for item in (make_dead_file(), make_dead_export()):
        verdict = await judge.judge_dead_source(item)
        assert verdict.kind in {"clean", "risky", "unknown"}
