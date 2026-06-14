from __future__ import annotations

import time
from collections.abc import Callable
from datetime import timedelta

import httpx
import pytest
from temporalio.exceptions import ApplicationError

from froot.adapters import github
from froot.adapters.github import (
    CheckRow,
    _pr_file_change,
    _pull_request_ref,
    ci_status_from_checks,
)
from froot.domain.ci import CIAbsent, CIFailed, CIPassed, CIPending
from tests.support import make_repo


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


def test_pr_file_change_keeps_removed_and_renamed():
    # The path-only list_pull_request_files drops these; the richer feed must
    # keep a removed target and a rename's previous path (the refs a PR breaks).
    removed = _pr_file_change({"filename": "docs/gone.md", "status": "removed"})
    assert removed.status == "removed"
    assert removed.previous_filename is None

    renamed = _pr_file_change(
        {
            "filename": "src/new.py",
            "status": "renamed",
            "previous_filename": "src/old.py",
        }
    )
    assert renamed.status == "renamed"
    assert renamed.previous_filename == "src/old.py"


def test_pr_file_change_unknown_status_degrades_to_modified():
    # A future GitHub status must not break the feed (boundary robustness).
    change = _pr_file_change({"filename": "x.py", "status": "future-thing"})
    assert change.status == "modified"


# ── Rate-limit classification (_raise_for_status) ───────────────────────────


def _resp(
    status: int,
    headers: dict[str, str] | None = None,
    text: str = "",
) -> httpx.Response:
    return httpx.Response(
        status,
        headers=headers or {},
        text=text,
        request=httpx.Request("GET", "https://api.github.com/x"),
    )


def test_401_is_non_retryable():
    with pytest.raises(ApplicationError) as ei:
        github._raise_for_status(_resp(401))
    assert ei.value.non_retryable


def test_403_without_rate_limit_markers_is_non_retryable():
    with pytest.raises(ApplicationError) as ei:
        github._raise_for_status(_resp(403, text="Resource not accessible"))
    assert ei.value.non_retryable


def test_403_secondary_rate_limit_is_retryable_and_honors_retry_after():
    with pytest.raises(ApplicationError) as ei:
        github._raise_for_status(_resp(403, headers={"retry-after": "30"}))
    assert not ei.value.non_retryable
    assert ei.value.next_retry_delay == timedelta(seconds=30)


def test_403_primary_rate_limit_uses_reset_for_backoff():
    reset = str(int(time.time()) + 50)
    with pytest.raises(ApplicationError) as ei:
        github._raise_for_status(
            _resp(
                403,
                headers={
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": reset,
                },
            )
        )
    assert not ei.value.non_retryable
    assert ei.value.next_retry_delay is not None
    assert ei.value.next_retry_delay.total_seconds() > 0


def test_403_rate_limit_body_is_retryable():
    with pytest.raises(ApplicationError) as ei:
        github._raise_for_status(
            _resp(403, text="You have exceeded a secondary rate limit")
        )
    assert not ei.value.non_retryable


def test_429_is_retryable():
    with pytest.raises(ApplicationError) as ei:
        github._raise_for_status(_resp(429))
    assert not ei.value.non_retryable


def test_2xx_does_not_raise():
    github._raise_for_status(_resp(204))


def test_5xx_raises_httpx_error_for_temporal_to_retry():
    with pytest.raises(httpx.HTTPStatusError):
        github._raise_for_status(_resp(500))


# ── Pagination (Link rel=next) ──────────────────────────────────────────────


def _mock_forge(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[github.GitHubForge, Callable[[], None]]:
    """A GitHubForge whose HTTP client is backed by an in-memory transport."""

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="https://api.github.com",
            transport=httpx.MockTransport(handler),
        )

    original = github._client
    github._client = factory
    return github.GitHubForge(), lambda: setattr(github, "_client", original)


def _link(next_url: str) -> dict[str, str]:
    return {"link": f'<{next_url}>; rel="next"'}


def _pr(number: int) -> dict[str, object]:
    return {
        "number": number,
        "html_url": f"https://github.com/acme/widgets/pull/{number}",
        "head": {"ref": f"feature/b{number}", "sha": f"{number:07d}abc"},
    }


async def test_list_open_pull_requests_follows_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") is None:
            return httpx.Response(
                200,
                json=[_pr(1), _pr(2)],
                headers=_link(
                    "https://api.github.com/repos/acme/widgets/pulls?page=2"
                ),
            )
        return httpx.Response(200, json=[_pr(3)])

    forge, restore = _mock_forge(handler)
    try:
        refs = await forge.list_open_pull_requests(make_repo())
    finally:
        restore()
    assert [r.number for r in refs] == [1, 2, 3]


async def test_ci_status_sees_a_failing_check_on_a_later_page():
    # The correctness fix: a failing 2nd-page check must not read as green.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/check-runs"):
            if request.url.params.get("page") is None:
                return httpx.Response(
                    200,
                    json={
                        "check_runs": [
                            {
                                "name": "build",
                                "status": "completed",
                                "conclusion": "success",
                            }
                        ]
                    },
                    headers=_link(
                        "https://api.github.com/repos/acme/widgets/commits/"
                        "sha/check-runs?page=2"
                    ),
                )
            return httpx.Response(
                200,
                json={
                    "check_runs": [
                        {
                            "name": "e2e",
                            "status": "completed",
                            "conclusion": "failure",
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"state": "success", "total_count": 1})

    forge, restore = _mock_forge(handler)
    try:
        status = await forge.ci_status(make_repo(), "sha")
    finally:
        restore()
    assert isinstance(status, CIFailed)
    assert status.failing == ("e2e",)


async def test_upsert_finds_its_marker_on_a_later_page_and_edits():
    # The idempotency fix: froot's marker past page 1 must be found, so the
    # comment is EDITED (PATCH), never duplicated (POST).
    calls: dict[str, bool] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if request.url.params.get("page") is None:
                return httpx.Response(
                    200,
                    json=[{"id": 1, "body": "chatter"}],
                    headers=_link(
                        "https://api.github.com/repos/acme/widgets/issues/5/"
                        "comments?page=2"
                    ),
                )
            return httpx.Response(200, json=[{"id": 2, "body": "<!--m--> hi"}])
        if request.method == "PATCH":
            calls["patched"] = True
            return httpx.Response(
                200, json={"html_url": "https://github.com/x#c2"}
            )
        calls["posted"] = True
        return httpx.Response(201, json={"html_url": "dup"})

    forge, restore = _mock_forge(handler)
    try:
        url = await forge.upsert_issue_comment(
            make_repo(), 5, "<!--m-->", "new body"
        )
    finally:
        restore()
    assert url == "https://github.com/x#c2"
    assert calls.get("patched") and not calls.get("posted")
