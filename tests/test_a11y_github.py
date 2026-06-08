"""Forge tests for the a11y reviewer's GitHub additions (httpx-mocked).

The in-memory FakeForge can't model pagination or the create/patch branch, so
these exercise the real adapter via the shared MockTransport helper — the layer
where the multi-page marker search and the removed-file filter actually live.
"""

from __future__ import annotations

import httpx

from tests.support import make_repo
from tests.test_github_adapter import _link, _mock_forge

_MARKER = "<!-- froot:a11y-review -->"


async def test_list_pull_request_files_paginates_and_drops_removed():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") is None:
            return httpx.Response(
                200,
                json=[
                    {"filename": "components/A.vue", "status": "modified"},
                    {"filename": "old/Gone.vue", "status": "removed"},
                ],
                headers=_link(
                    "https://api.github.com/repos/acme/widgets/pulls/5/"
                    "files?page=2"
                ),
            )
        return httpx.Response(
            200,
            json=[
                {"filename": "src/New.jsx", "status": "added"},
                {"filename": "src/Renamed.jsx", "status": "renamed"},
            ],
        )

    forge, restore = _mock_forge(handler)
    try:
        files = await forge.list_pull_request_files(make_repo(), 5)
    finally:
        restore()
    # Renamed/added/modified kept (new path, at head); removed dropped.
    assert files == ("components/A.vue", "src/New.jsx", "src/Renamed.jsx")


async def test_find_marked_comment_true_across_pages():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") is None:
            return httpx.Response(
                200,
                json=[{"id": 1, "body": "chatter"}],
                headers=_link(
                    "https://api.github.com/repos/acme/widgets/issues/5/"
                    "comments?page=2"
                ),
            )
        return httpx.Response(200, json=[{"id": 2, "body": f"{_MARKER} x"}])

    forge, restore = _mock_forge(handler)
    try:
        found = await forge.find_marked_comment(make_repo(), 5, _MARKER)
    finally:
        restore()
    assert found is True


async def test_find_marked_comment_false_when_absent():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 1, "body": "no marker here"}])

    forge, restore = _mock_forge(handler)
    try:
        found = await forge.find_marked_comment(make_repo(), 5, _MARKER)
    finally:
        restore()
    assert found is False
