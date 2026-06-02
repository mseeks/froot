from __future__ import annotations

import pytest

from froot.domain.changelog import CleanVerdict, RiskyVerdict, UnknownVerdict
from froot.domain.ci import (
    CIAbsent,
    CIFailed,
    CIPassed,
    CITimedOut,
    TerminalCIStatus,
)
from froot.domain.outcome import LoopOutcome
from froot.policy.compose import outcome_labels, pull_request_draft
from froot.policy.naming import branch_name
from tests.support import make_candidate, make_pr, make_repo


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


@pytest.mark.parametrize(
    "ci,label",
    [
        (CIPassed(), "ci:passed"),
        (CIFailed(), "ci:failed"),
        (CIAbsent(), "ci:no-checks"),
        (CITimedOut(), "ci:timed-out"),
    ],
)
def test_outcome_labels(ci: TerminalCIStatus, label: str):
    outcome = LoopOutcome(
        candidate=make_candidate(),
        verdict=RiskyVerdict(rationale="r"),
        pr=make_pr(),
        ci=ci,
    )
    labels = outcome_labels(outcome)
    expected = {"froot", "dependency-patch", "changelog:risky", label}
    assert expected <= set(labels)
