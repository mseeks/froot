"""The doc-refs comment: cite-or-omit synthesis, the decay rule, rendering."""

from __future__ import annotations

from froot.domain.doc_refs import (
    DocRefCandidate,
    DocRefFinding,
    DocRefVerdict,
)
from froot.policy.doc_refs_comment import (
    DOC_REFS_MARKER,
    render_doc_refs_comment,
    should_post,
    synthesize_doc_ref_findings,
)


def _cand(referent: str = "docs/gone.md", *, broken_by_pr: bool = False):
    return DocRefCandidate(
        file="README.md",
        line=2,
        kind="broken-link",
        referent=referent,
        snippet="x",
        broken_by_pr=broken_by_pr,
    )


def test_broken_without_a_citation_is_dropped():
    cands = (_cand(),)
    verdicts = (
        DocRefVerdict(bucket="broken", rationale="missing", citation=""),
    )
    assert synthesize_doc_ref_findings(cands, verdicts) == ()


def test_broken_with_citation_and_judgment_kept_intentional_dropped():
    cands = (_cand("a.md"), _cand("b.md"), _cand("c.md"))
    verdicts = (
        DocRefVerdict(
            bucket="broken", rationale="r", citation="a.md", action="fix"
        ),
        DocRefVerdict(bucket="intentional", rationale="a changelog ref"),
        DocRefVerdict(bucket="judgment", rationale="unsure"),
    )
    findings = synthesize_doc_ref_findings(cands, verdicts)
    assert sorted(f.bucket for f in findings) == ["broken", "judgment"]


def test_should_post_decays_when_a_prior_comment_exists():
    assert should_post(has_findings=False, comment_exists=True) is True
    assert should_post(has_findings=False, comment_exists=False) is False
    assert should_post(has_findings=True, comment_exists=False) is True


def test_render_all_clear_when_no_findings():
    body = render_doc_refs_comment((), "abcdef1234")
    assert DOC_REFS_MARKER in body
    assert "No dangling references" in body


def test_render_marks_a_pr_caused_break():
    finding = DocRefFinding(
        kind="broken-link",
        file="README.md",
        line=2,
        bucket="broken",
        referent="docs/gone.md",
        why="the PR deleted it",
        action="drop the link",
        broken_by_pr=True,
    )
    body = render_doc_refs_comment((finding,), "abcdef1234")
    assert "removed by this PR" in body
    assert "docs/gone.md" in body
    assert "Broken references" in body
