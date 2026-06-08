"""Pure tests for a11y finding synthesis and the advisory-comment renderer."""

from __future__ import annotations

import pytest

from froot.domain.a11y import A11yCandidate, A11yVerdict
from froot.policy.a11y_comment import (
    A11Y_MARKER,
    render_a11y_comment,
    should_post,
    synthesize_a11y_findings,
)


def _cand(kind: str = "image", line: int = 4) -> A11yCandidate:
    return A11yCandidate(
        file="components/W.vue",
        line=line,
        kind=kind,  # type: ignore[arg-type]
        dialect="vue",
        detail="<img>",
        snippet="<img :src='u' />",
        context="<img :src='u' />",
    )


def test_gap_with_citation_is_surfaced():
    findings = synthesize_a11y_findings(
        (_cand(),),
        (
            A11yVerdict(
                bucket="gap",
                rationale="screen reader reads the URL",
                citation="<img :src='u' />",
                action="add :alt",
            ),
        ),
    )
    assert len(findings) == 1
    assert findings[0].bucket == "gap"
    assert findings[0].what == "<img :src='u' />"
    assert findings[0].action == "add :alt"


def test_gap_without_citation_is_dropped():
    # Cite-or-omit: a gap the model can't quote is a suspected confabulation.
    findings = synthesize_a11y_findings(
        (_cand(),),
        (A11yVerdict(bucket="gap", rationale="looks unlabeled", citation=""),),
    )
    assert findings == ()


def test_ok_is_dropped_and_judgment_is_kept():
    findings = synthesize_a11y_findings(
        (_cand("svg"), _cand("svg", line=9)),
        (
            A11yVerdict(bucket="ok", rationale="has aria-label"),
            A11yVerdict(
                bucket="judgment", rationale="decorative or meaningful?"
            ),
        ),
    )
    assert [f.bucket for f in findings] == ["judgment"]


def test_misaligned_candidates_and_verdicts_raise():
    with pytest.raises(ValueError, match="argument"):
        synthesize_a11y_findings((_cand(),), ())


def test_should_post_is_the_decay_rule():
    assert should_post(has_findings=True, comment_exists=False) is True
    assert should_post(has_findings=False, comment_exists=True) is True
    assert should_post(has_findings=False, comment_exists=False) is False


def test_render_carries_marker_facts_and_action():
    findings = synthesize_a11y_findings(
        (_cand(),),
        (
            A11yVerdict(
                bucket="gap",
                rationale="screen reader reads the URL",
                citation="<img :src='u' />",
                action="add :alt to the img",
            ),
        ),
    )
    body = render_a11y_comment(findings, "abc1234def999")
    assert body.startswith(A11Y_MARKER)
    assert "abc1234" in body
    assert "components/W.vue:4" in body
    assert "add :alt to the img" in body
    assert "Advisory" in body


def test_render_all_clear_when_empty():
    body = render_a11y_comment((), "abc1234def999")
    assert body.startswith(A11Y_MARKER)
    assert "✅" in body
    assert "abc1234" in body
