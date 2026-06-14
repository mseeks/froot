"""doc-coherence: cite-or-omit synthesis, rendering (incl. a failed run), agent.

The cite-or-omit filter is the confabulation guard for an agentic loop, so it is
pinned hard; the render must show a failed run as "couldn't verify" (never a
false all-clear); and the agent builder runs offline with a ``TestModel``.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel

from froot.adapters.doc_coherence_agent import map_doc_coherence
from froot.domain.doc_coherence import DocCoherenceFinding, DocCoherenceItem
from froot.policy.doc_coherence_comment import (
    DOC_COHERENCE_MARKER,
    render_doc_coherence_comment,
    should_post,
    synthesize_doc_coherence_findings,
)


def _item(
    bucket: str, *, what: str = "", citation: str = "", why: str = "r"
) -> DocCoherenceItem:
    return DocCoherenceItem(
        bucket=bucket,  # type: ignore[arg-type]  # test feeds valid buckets
        what=what,
        why=why,
        citation=citation,
    )


def test_drift_without_a_citation_is_dropped():
    items = (_item("drift", what="README says X", citation=""),)
    assert synthesize_doc_coherence_findings(items) == ()


def test_drift_with_citation_and_judgment_kept_ok_dropped():
    items = (
        _item("drift", what="README claims foo()", citation="README.md:3"),
        _item("ok", what="bar is fine", citation="x"),
        _item("judgment", what="ambiguous Z"),
    )
    findings = synthesize_doc_coherence_findings(items)
    assert sorted(f.bucket for f in findings) == ["drift", "judgment"]


def test_should_post_decays_when_a_prior_comment_exists():
    assert should_post(has_findings=False, comment_exists=True) is True
    assert should_post(has_findings=False, comment_exists=False) is False


def test_render_all_clear_when_completed_with_no_findings():
    body = render_doc_coherence_comment((), "abcdef1234", completed=True)
    assert DOC_COHERENCE_MARKER in body
    assert "No semantic doc drift" in body


def test_render_flags_an_incomplete_run_rather_than_all_clear():
    body = render_doc_coherence_comment((), "abcdef1234", completed=False)
    assert "could not complete" in body
    assert "No semantic doc drift" not in body


def test_render_lists_a_drift_finding_with_its_citation():
    finding = DocCoherenceFinding(
        bucket="drift",
        what="README claims foo() exists",
        why="it was renamed to bar()",
        action="update the README",
        citation="README.md:3",
    )
    body = render_doc_coherence_comment(
        (finding,), "abcdef1234", completed=True
    )
    assert "README claims foo() exists" in body
    assert "README.md:3" in body
    assert "Drift" in body


async def test_map_doc_coherence_runs_offline(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Title\nbody\n")
    items, status = await map_doc_coherence(
        model=TestModel(), checkout=tmp_path, max_requests=4
    )
    assert status == "completed"
    assert isinstance(items, tuple)
