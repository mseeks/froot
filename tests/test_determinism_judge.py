"""The frontier adjudicator, run offline with a Pydantic AI ``TestModel``."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from froot.adapters.determinism_judge import DeterminismFrontierJudge
from froot.domain.determinism import FrontierItem, FrontierVerdict


def _frontier() -> FrontierItem:
    return FrontierItem(
        kind="third_party_import",
        workflow="app.workflow:W",
        module="app.workflow",
        line=2,
        symbol="httpx",
        snippet="import httpx",
    )


async def test_adjudicate_maps_model_output_to_verdict():
    judge = DeterminismFrontierJudge(model=TestModel())
    verdict = await judge.adjudicate(_frontier())
    assert isinstance(verdict, FrontierVerdict)
    assert verdict.reaches in ("yes", "no", "uncertain")
    assert verdict.rationale
