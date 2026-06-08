"""The a11y activities: the decay decision, the scan, the model fan-out."""

from __future__ import annotations

import pytest

import froot.adapters.a11y_judge as judge_mod
import froot.adapters.github as github_mod
from froot.domain.a11y import A11yCandidate, A11yFinding, A11yVerdict
from froot.workflow import activities
from froot.workflow.types import (
    AdjudicateA11yInput,
    PostA11yInput,
    PrA11yReviewParams,
)
from tests.support import FakeForge, make_pr, make_repo


def _gap() -> A11yFinding:
    return A11yFinding(
        kind="image",
        file="components/W.vue",
        line=4,
        bucket="gap",
        what="<img :src='u' />",
        why="a screen reader reads the URL",
        action="add :alt to the img",
    )


async def test_post_a11y_posts_when_there_are_findings(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge()
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    url = await activities.post_a11y_review(
        PostA11yInput(target=make_repo(), pr=make_pr(), findings=(_gap(),))
    )
    assert url is not None
    assert fake.upserted is not None
    assert "add :alt to the img" in fake.upserted[1]


async def test_post_a11y_clears_a_stale_comment_when_clean(
    monkeypatch: pytest.MonkeyPatch,
):
    # The decay fix: a PR whose gaps were fixed gets "all clear", not a stale
    # finding list left behind.
    fake = FakeForge(marked_comment=True)
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    url = await activities.post_a11y_review(
        PostA11yInput(target=make_repo(), pr=make_pr(), findings=())
    )
    assert url is not None
    assert fake.upserted is not None
    assert "✅" in fake.upserted[1]


async def test_post_a11y_stays_silent_on_a_clean_pr_with_no_prior_comment(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(marked_comment=False)
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    url = await activities.post_a11y_review(
        PostA11yInput(target=make_repo(), pr=make_pr(), findings=())
    )
    assert url is None
    assert fake.upserted is None  # never posted on a clean PR


async def test_scan_pr_a11y_returns_empty_when_no_templates_changed(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeForge(changed_files=("server/store.ts",))
    monkeypatch.setattr(github_mod, "GitHubForge", lambda: fake)
    analysis = await activities.scan_pr_a11y(
        PrA11yReviewParams(target=make_repo(), pr=make_pr())
    )
    assert analysis.candidates == ()
    assert analysis.scanned_files == 0


class _FakeJudge:
    async def adjudicate(self, candidate: A11yCandidate) -> A11yVerdict:
        return A11yVerdict(bucket="ok", rationale="named elsewhere")


async def test_adjudicate_a11y_runs_the_judge_per_candidate(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(judge_mod, "A11ySourceJudge", _FakeJudge)
    candidates = (
        A11yCandidate(file="W.vue", line=1, kind="svg", dialect="vue"),
        A11yCandidate(file="W.vue", line=2, kind="image", dialect="vue"),
    )
    verdicts = await activities.adjudicate_a11y(
        AdjudicateA11yInput(candidates=candidates)
    )
    assert len(verdicts) == 2
    assert all(v.bucket == "ok" for v in verdicts)
