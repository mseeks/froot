from __future__ import annotations

from froot.adapters.github import (
    CheckRow,
    _pull_request_ref,
    ci_status_from_checks,
)
from froot.domain.ci import CIAbsent, CIFailed, CIPassed, CIPending


def _completed(name: str, conclusion: str) -> CheckRow:
    return CheckRow(name=name, status="completed", conclusion=conclusion)


def test_ci_absent_when_nothing_reports():
    assert isinstance(ci_status_from_checks((), None), CIAbsent)


def test_ci_pending_when_a_check_is_running():
    rows = (CheckRow(name="build", status="in_progress", conclusion=None),)
    assert isinstance(ci_status_from_checks(rows, None), CIPending)


def test_ci_pending_when_combined_pending():
    assert isinstance(ci_status_from_checks((), "pending"), CIPending)


def test_ci_passed_when_all_good():
    rows = (_completed("build", "success"), _completed("lint", "skipped"))
    assert isinstance(ci_status_from_checks(rows, "success"), CIPassed)


def test_ci_failed_lists_failing_checks():
    rows = (_completed("build", "success"), _completed("tests", "failure"))
    status = ci_status_from_checks(rows, None)
    assert isinstance(status, CIFailed)
    assert status.failing == ("tests",)


def test_ci_failed_on_combined_failure():
    assert isinstance(ci_status_from_checks((), "failure"), CIFailed)


def test_pull_request_ref_from_payload():
    payload = {
        "number": 7,
        "html_url": "https://github.com/o/n/pull/7",
        "head": {
            "ref": "froot/dependency-patch/left-pad-1.4.3",
            "sha": "abc1234",
        },
    }
    ref = _pull_request_ref(payload)
    assert ref.number == 7
    assert ref.branch.value == "froot/dependency-patch/left-pad-1.4.3"
    assert ref.head_sha == "abc1234"
