"""The doc-refs adjudicator, run offline with a Pydantic AI ``TestModel``."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel

from froot.adapters.doc_refs_judge import DocRefsJudge
from froot.domain.doc_refs import DocRefCandidate, DocRefVerdict


def _candidate(*, broken_by_pr: bool = False) -> DocRefCandidate:
    return DocRefCandidate(
        file="README.md",
        line=3,
        kind="broken-link",
        referent="docs/gone.md",
        snippet="See [gone](docs/gone.md).",
        broken_by_pr=broken_by_pr,
    )


async def test_adjudicate_maps_model_output_to_verdict():
    verdict = await DocRefsJudge(model=TestModel()).adjudicate(_candidate())
    assert isinstance(verdict, DocRefVerdict)
    assert verdict.bucket in ("broken", "intentional", "judgment")
    assert verdict.rationale


async def test_adjudicate_handles_a_pr_removed_referent():
    # The broken_by_pr branch builds a different prompt — exercise it offline.
    verdict = await DocRefsJudge(model=TestModel()).adjudicate(
        _candidate(broken_by_pr=True)
    )
    assert isinstance(verdict, DocRefVerdict)
