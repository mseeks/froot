"""The a11y adjudicator, run offline with a Pydantic AI ``TestModel``."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from froot.adapters.a11y_judge import A11ySourceJudge
from froot.domain.a11y import A11yCandidate, A11yVerdict


def _candidate() -> A11yCandidate:
    return A11yCandidate(
        file="components/W.vue",
        line=4,
        kind="image",
        dialect="vue",
        detail="<img>",
        snippet="<img :src='u' />",
        context="<template>\n  <img :src='u' />\n</template>",
    )


async def test_adjudicate_maps_model_output_to_verdict():
    judge = A11ySourceJudge(model=TestModel())
    verdict = await judge.adjudicate(_candidate())
    assert isinstance(verdict, A11yVerdict)
    assert verdict.bucket in ("gap", "ok", "judgment")
    assert verdict.rationale
