from __future__ import annotations

from froot.domain.changelog import CleanVerdict, RiskyVerdict, UnknownVerdict
from froot.domain.ecosystem import Ecosystem
from froot.domain.loop import Loop
from froot.policy.compose import (
    CLOSE_MARKER,
    closed_on_red_comment,
    pr_labels,
    pull_request_draft,
    removal_pull_request_draft,
)
from froot.policy.naming import branch_name
from tests.support import make_candidate, make_removal, make_repo


def test_security_draft_uses_security_namespace_and_justification():
    from froot.domain.candidate import Candidate
    from froot.domain.ecosystem import Ecosystem
    from froot.domain.version import Version

    repo = make_repo("acme/widgets")
    candidate = Candidate(
        package="left-pad",
        ecosystem=Ecosystem.NPM,
        current=Version(major=1, minor=2, patch=0),
        target=Version(major=1, minor=3, patch=0),
        justification="Clears GHSA-xxxx (CVE-1).",
    )
    draft = pull_request_draft(
        repo,
        candidate,
        CleanVerdict(rationale="ok"),
        Loop.SECURITY_PATCH,
        title_prefix="security",
    )
    assert draft.title == "security: bump left-pad to 1.3.0"
    assert draft.branch.value == "froot/security-patch/left-pad-1.3.0"
    assert "Clears GHSA-xxxx (CVE-1)." in draft.body


def test_removal_draft_names_the_unused_dependency():
    repo = make_repo("acme/widgets")
    removal = make_removal(
        package="left-pad",
        dev=True,
        justification="unused (knip); not imported",
    )
    draft = removal_pull_request_draft(
        repo, removal, Loop.DEPENDENCY_PATCH, title_prefix="deps"
    )
    assert draft.title == "deps: remove left-pad (unused)"
    assert draft.base == "main"
    assert draft.branch == branch_name(removal, Loop.DEPENDENCY_PATCH)
    assert "Removes the unused dev dependency `left-pad`" in draft.body
    assert "unused (knip); not imported" in draft.body  # the safe-to-remove why
    assert "a human approves" in draft.body


def test_closed_on_red_comment_names_failing_checks():
    body = closed_on_red_comment(("build", "tests"))
    assert CLOSE_MARKER in body  # goes through the idempotent comment path
    assert "`build`" in body
    assert "`tests`" in body
    assert "re-propose" in body or "propose it fresh" in body


def test_closed_on_red_comment_without_check_names():
    # GitHub didn't report specific failing checks: still a coherent message.
    body = closed_on_red_comment(())
    assert CLOSE_MARKER in body
    assert "CI did not pass." in body


def test_pull_request_draft_clean():
    repo = make_repo("acme/widgets")
    candidate = make_candidate(
        package="left-pad", current="1.4.2", target="1.4.3"
    )
    draft = pull_request_draft(
        repo, candidate, CleanVerdict(rationale="fixes"), title_prefix="deps"
    )
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
    draft = pull_request_draft(
        repo, candidate, CleanVerdict(rationale="ok"), title_prefix="deps"
    )
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
        title_prefix="deps",
    )
    assert "- regex change" in draft.body
    assert "- deprecated" in draft.body


def test_pull_request_draft_unknown():
    draft = pull_request_draft(
        make_repo(),
        make_candidate(),
        UnknownVerdict(rationale="no notes"),
        title_prefix="deps",
    )
    assert "no notes" in draft.body


def test_pr_labels_are_exactly_the_fixed_pair():
    """Every froot PR carries just these two — no changelog/CI labels.

    How the proposal fared is recorded in the durable workflow history, not
    layered onto the PR as labels that accumulate across re-runs.
    """
    assert pr_labels() == ("froot", "dependency-patch")
    assert pr_labels(Loop.SECURITY_PATCH) == ("froot", "security-patch")
