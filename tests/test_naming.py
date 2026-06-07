from __future__ import annotations

from froot.domain.loop import Loop
from froot.policy.naming import (
    branch_name,
    branch_package_prefix,
    bump_workflow_id,
    scan_workflow_id,
)
from tests.support import make_candidate, make_removal, make_repo


def test_security_loop_namespaces_branches_and_ids():
    repo = make_repo("acme/widgets")
    candidate = make_candidate(
        package="left-pad", current="1.2.0", target="1.3.0"
    )
    # Branches carry the loop, so the two loops never collide on one branch.
    assert branch_name(candidate, Loop.SECURITY_PATCH).value == (
        "froot/security-patch/left-pad-1.3.0"
    )
    assert branch_package_prefix("left-pad", Loop.SECURITY_PATCH) == (
        "froot/security-patch/left-pad-"
    )
    # Workflow ids namespace non-default loops; dependency-patch stays as-is.
    assert bump_workflow_id(repo, candidate, Loop.SECURITY_PATCH) == (
        "froot-bump-security-patch-acme-widgets-left-pad-1.3.0"
    )
    assert scan_workflow_id(repo, Loop.SECURITY_PATCH) == (
        "froot-scan-security-patch-acme-widgets"
    )
    # The dependency-patch ids are byte-for-byte what they were before loops.
    assert scan_workflow_id(repo) == "froot-scan-acme-widgets"


def test_branch_name_format():
    candidate = make_candidate(package="left-pad", target="1.4.3")
    assert (
        branch_name(candidate).value == "froot/dependency-patch/left-pad-1.4.3"
    )


def test_branch_package_prefix_is_branch_minus_version():
    # The prefix is exactly branch_name minus the "-<target>" tail, so a bump's
    # branch always starts with its package's prefix.
    candidate = make_candidate(package="left-pad", target="1.4.3")
    prefix = branch_package_prefix("left-pad")
    assert prefix == "froot/dependency-patch/left-pad-"
    assert branch_name(candidate).value.startswith(prefix)


def test_branch_package_prefix_sanitizes_scoped_package():
    assert (
        branch_package_prefix("@scope/pkg")
        == "froot/dependency-patch/scope-pkg-"
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


def test_removal_names_use_unused_tail():
    # A removal carries no version, so its branch/id tail is "-unused" rather
    # than "-<target>" — the discriminating behavior the work-item widening
    # adds. Naming is loop-agnostic, so the default loop exercises it (the
    # dead-code loop that will own removals lands in a later slice).
    repo = make_repo("acme/widgets")
    removal = make_removal(package="left-pad")
    assert branch_name(removal).value == (
        "froot/dependency-patch/left-pad-unused"
    )
    assert bump_workflow_id(repo, removal) == (
        "froot-bump-acme-widgets-left-pad-unused"
    )


def test_removal_names_sanitize_scoped_package():
    removal = make_removal(package="@scope/pkg")
    assert branch_name(removal).value == (
        "froot/dependency-patch/scope-pkg-unused"
    )


def test_bump_names_unchanged_by_work_item_widening():
    # Regression: widening Candidate -> WorkItem must leave a bump's names
    # byte-for-byte what they were, so a running bump loop is never orphaned.
    repo = make_repo("acme/widgets")
    candidate = make_candidate(package="left-pad", target="1.4.3")
    assert branch_name(candidate).value == (
        "froot/dependency-patch/left-pad-1.4.3"
    )
    assert (
        bump_workflow_id(repo, candidate)
        == "froot-bump-acme-widgets-left-pad-1.4.3"
    )
