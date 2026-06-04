"""Pure tests for finding synthesis and the advisory-comment renderer."""

from __future__ import annotations

import pytest

from froot.domain.determinism import (
    FrontierItem,
    FrontierVerdict,
    HazardPath,
    Impurity,
)
from froot.policy.review_comment import (
    REVIEW_MARKER,
    render_review_comment,
    synthesize_findings,
)


def _impurity() -> Impurity:
    return Impurity(
        rule="datetime.datetime.now",
        hint="use workflow.now()",
        module="app.util",
        line=4,
    )


def _frontier(symbol: str, line: int) -> FrontierItem:
    return FrontierItem(
        kind="third_party_import",
        workflow="app.wf:W",
        module="app.wf",
        line=line,
        symbol=symbol,
        snippet=f"import {symbol}",
    )


def test_synthesize_static_hazard():
    hazard = HazardPath(
        workflow="app.wf:W", via=("stamp",), impurity=_impurity()
    )
    findings = synthesize_findings((hazard,), (), ())
    assert len(findings) == 1
    assert findings[0].origin == "static"
    assert "stamp" in findings[0].detail
    assert "datetime.datetime.now" in findings[0].detail


def test_synthesize_surfaces_only_model_yes():
    items = (_frontier("httpx", 2), _frontier("requests", 3))
    verdicts = (
        FrontierVerdict(reaches="yes", rationale="used in run()"),
        FrontierVerdict(reaches="no", rationale="only in an activity"),
    )
    findings = synthesize_findings((), items, verdicts)
    assert len(findings) == 1
    assert findings[0].origin == "model"
    assert findings[0].rule == "httpx"


def test_synthesize_requires_aligned_frontier_and_verdicts():
    with pytest.raises(ValueError, match="argument"):
        synthesize_findings((), (_frontier("httpx", 2),), ())


def test_render_none_when_empty():
    assert render_review_comment((), "abc1234def") is None


def test_render_carries_marker_and_facts():
    hazard = HazardPath(
        workflow="app.wf:W", via=("stamp",), impurity=_impurity()
    )
    findings = synthesize_findings((hazard,), (), ())
    body = render_review_comment(findings, "abc1234def9999")
    assert body is not None
    assert body.startswith(REVIEW_MARKER)
    assert "abc1234" in body
    assert "datetime.datetime.now" in body
    assert "use workflow.now()" in body
