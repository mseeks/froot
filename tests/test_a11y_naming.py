"""The a11y reviewer's deterministic workflow ids."""

from __future__ import annotations

from froot.policy.naming import (
    a11y_review_workflow_id,
    pr_a11y_review_workflow_id,
)
from tests.support import make_pr, make_repo


def test_a11y_review_workflow_id_is_a_deterministic_singleton():
    repo = make_repo("Acme/Widgets")
    assert a11y_review_workflow_id(repo) == a11y_review_workflow_id(repo)
    assert a11y_review_workflow_id(repo) == "froot-a11y-acme-widgets"


def test_pr_a11y_review_workflow_id_keys_on_pr_and_head_sha():
    repo = make_repo("acme/widgets")
    pr = make_pr(number=7, head_sha="abcdef1234567")
    wid = pr_a11y_review_workflow_id(repo, pr.number, pr.head_sha)
    assert wid == pr_a11y_review_workflow_id(repo, pr.number, pr.head_sha)
    assert wid.startswith("froot-pr-a11y-acme-widgets-7-")
    # A new commit (different head SHA) is a distinct review.
    other = pr_a11y_review_workflow_id(repo, 7, "fffffff7654321")
    assert other != wid
