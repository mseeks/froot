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
from tests.support import ver


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
