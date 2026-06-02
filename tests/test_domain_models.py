from __future__ import annotations

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from froot.domain.changelog import ChangelogVerdict, CleanVerdict, RiskyVerdict
from froot.domain.ci import (
    CIAbsent,
    CIFailed,
    CIPassed,
    CIPending,
    CIStatus,
    CITimedOut,
    is_terminal,
)
from froot.domain.ecosystem import (
    Ecosystem,
    lockfile_filename,
    manifest_filename,
)
from froot.domain.effects import Effect, JudgeChangelog
from froot.domain.events import CiResolved, LoopEvent
from froot.domain.outcome import LoopOutcome
from froot.domain.pull_request import BranchName
from froot.domain.repo import RepoRef
from froot.domain.state import BumpState, Discovered
from froot.result import Err, unwrap
from tests.support import make_candidate, make_pr


def test_repo_ref_parse_and_slug():
    ref = unwrap(RepoRef.parse("acme/widgets"))
    assert ref.slug == "acme/widgets"
    assert str(ref) == "acme/widgets"
    assert isinstance(RepoRef.parse("no-slash"), Err)
    assert isinstance(RepoRef.parse("a/b/c"), Err)


def test_repo_ref_constructor_rejects_invalid_segments():
    # The anchored pattern makes a malformed owner/name unrepresentable, not
    # just guarded at parse() — illegal states stay out of the type.
    for owner, name in [("a b", "x"), ("ok", "bad/slash"), ("a\nb", "x")]:
        with pytest.raises(ValidationError):
            RepoRef(owner=owner, name=name)


def test_branch_name_validation():
    assert BranchName(value="froot/dependency-patch/left-pad-1.4.3").value
    with pytest.raises(ValidationError):
        BranchName(value="has spaces")
    with pytest.raises(ValidationError):
        BranchName(value="bad~char")


def test_ecosystem_files():
    assert manifest_filename(Ecosystem.NPM) == "package.json"
    assert lockfile_filename(Ecosystem.NPM) == "package-lock.json"


def test_ci_is_terminal():
    assert not is_terminal(CIPending())
    for status in (CIPassed(), CIFailed(), CIAbsent(), CITimedOut()):
        assert is_terminal(status)


def test_loop_outcome_ci_passed():
    passed = LoopOutcome(
        candidate=make_candidate(),
        verdict=CleanVerdict(rationale="ok"),
        pr=make_pr(),
        ci=CIPassed(),
    )
    failed = LoopOutcome(
        candidate=make_candidate(),
        verdict=CleanVerdict(rationale="ok"),
        pr=make_pr(),
        ci=CIFailed(),
    )
    assert passed.ci_passed
    assert not failed.ci_passed


def _round_trip(union: Any, value: Any) -> Any:
    adapter = TypeAdapter(union)
    return adapter.validate_python(adapter.dump_python(value))


def test_discriminated_unions_round_trip():
    candidate = make_candidate()
    assert _round_trip(
        BumpState, Discovered(candidate=candidate)
    ) == Discovered(candidate=candidate)
    assert (
        _round_trip(Effect, JudgeChangelog(candidate=candidate)).kind
        == "judge_changelog"
    )
    assert (
        _round_trip(LoopEvent, CiResolved(status=CIPassed())).kind
        == "ci_resolved"
    )
    assert _round_trip(CIStatus, CIFailed(failing=("build",))) == CIFailed(
        failing=("build",)
    )
    assert (
        _round_trip(
            ChangelogVerdict, RiskyVerdict(rationale="r", concerns=("c",))
        ).kind
        == "risky"
    )
