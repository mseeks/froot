from __future__ import annotations

from froot.domain.changelog import CleanVerdict, RiskyVerdict, UnknownVerdict
from froot.domain.ecosystem import Ecosystem
from froot.policy.compose import PR_LABELS, pull_request_draft
from froot.policy.naming import branch_name
from tests.support import make_candidate, make_repo


def test_pull_request_draft_clean():
    repo = make_repo("acme/widgets")
    candidate = make_candidate(
        package="left-pad", current="1.4.2", target="1.4.3"
    )
    draft = pull_request_draft(repo, candidate, CleanVerdict(rationale="fixes"))
    assert draft.title == "deps: bump left-pad to 1.4.3"
    assert draft.base == "main"
    assert draft.branch == branch_name(candidate)
    assert "Bumps `left-pad` from 1.4.2 to 1.4.3" in draft.body
    assert "package.json" in draft.body
    assert "a human approves" in draft.body
    assert "fixes" in draft.body


def test_pull_request_draft_uv_describes_lockfile_only():
    # A uv bump rewrites only uv.lock; the body must not tell the human approver
    # that pyproject.toml changed when the diff won't contain it.
    repo = make_repo("acme/pylib", ecosystem=Ecosystem.UV)
    candidate = make_candidate(
        package="idna", current="3.6.0", target="3.6.1", ecosystem=Ecosystem.UV
    )
    draft = pull_request_draft(repo, candidate, CleanVerdict(rationale="ok"))
    assert "uv.lock only" in draft.body
    assert "pyproject.toml unchanged" in draft.body
    assert "pyproject.toml + lockfile" not in draft.body


def test_pull_request_draft_risky_renders_concerns():
    draft = pull_request_draft(
        make_repo(),
        make_candidate(),
        RiskyVerdict(
            rationale="careful", concerns=("regex change", "deprecated")
        ),
    )
    assert "- regex change" in draft.body
    assert "- deprecated" in draft.body


def test_pull_request_draft_unknown():
    draft = pull_request_draft(
        make_repo(), make_candidate(), UnknownVerdict(rationale="no notes")
    )
    assert "no notes" in draft.body


def test_pr_labels_are_exactly_the_fixed_pair():
    """Every froot PR carries just these two — no changelog/CI labels.

    How the proposal fared is recorded in the durable workflow history, not
    layered onto the PR as labels that accumulate across re-runs.
    """
    assert PR_LABELS == ("froot", "dependency-patch")
