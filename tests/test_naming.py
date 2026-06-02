from __future__ import annotations

from froot.policy.naming import (
    branch_name,
    bump_workflow_id,
    scan_workflow_id,
)
from tests.support import make_candidate, make_repo


def test_branch_name_format():
    candidate = make_candidate(package="left-pad", target="1.4.3")
    assert (
        branch_name(candidate).value == "froot/dependency-patch/left-pad-1.4.3"
    )


def test_branch_name_sanitizes_scoped_package():
    candidate = make_candidate(package="@scope/pkg", target="1.4.3")
    assert branch_name(candidate).value == (
        "froot/dependency-patch/scope-pkg-1.4.3"
    )


def test_workflow_ids_deterministic():
    repo = make_repo("acme/widgets")
    candidate = make_candidate(package="left-pad", target="1.4.3")
    assert (
        bump_workflow_id(repo, candidate)
        == "froot-bump-acme-widgets-left-pad-1.4.3"
    )
    # same inputs -> same id (the dispatch dedup key)
    assert bump_workflow_id(repo, candidate) == bump_workflow_id(
        repo, candidate
    )
    assert scan_workflow_id(repo) == "froot-scan-acme-widgets"


def test_scan_id_distinct_per_repo():
    assert scan_workflow_id(make_repo("a/b")) != scan_workflow_id(
        make_repo("a/c")
    )
