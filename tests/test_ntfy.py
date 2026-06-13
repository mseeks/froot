"""The best-effort ntfy notifier.

Pins the two behaviours the watchdog depends on: an unset topic disables alerts
(a silent no-op, not an error), and a configured topic POSTs to the
``<url>/<topic>`` endpoint with the title header.
"""

from __future__ import annotations

import httpx
import pytest

from froot.adapters.ntfy import notify
from froot.config.settings import NtfySettings


async def test_notify_is_a_noop_without_a_topic() -> None:
    sent = await notify(NtfySettings(ntfy_topic=""), title="x", message="y")
    assert sent is False


async def test_notify_posts_to_the_topic_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posted: dict[str, object] = {}

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class _FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(
            self, url: str, *, content: bytes, headers: dict[str, str]
        ) -> _FakeResponse:
            posted["url"] = url
            posted["content"] = content
            posted["headers"] = headers
            return _FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    sent = await notify(
        NtfySettings(ntfy_topic="my-topic", ntfy_url="https://ntfy.sh"),
        title="Loop down",
        message="dead-code · repo",
        tags="rotating_light",
    )
    assert sent is True
    assert posted["url"] == "https://ntfy.sh/my-topic"
    assert posted["content"] == b"dead-code \xc2\xb7 repo"
    headers = posted["headers"]
    assert isinstance(headers, dict)
    assert headers["Title"] == "Loop down"
