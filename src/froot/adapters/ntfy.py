"""Best-effort ntfy notifications for loop-health alerts.

The liveness watchdog (:mod:`froot.watchdog`) posts here when it revives a dead
loop. Best-effort by design: an unset topic is a no-op, and a transport error is
logged, never raised — a down notifier must not crash the watchdog whose whole
job is to keep the loops alive.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from froot.config.settings import NtfySettings

_log = logging.getLogger("froot.ntfy")


async def notify(
    settings: NtfySettings,
    *,
    title: str,
    message: str,
    tags: str = "",
    priority: str = "default",
) -> bool:
    """POST a notification to the configured ntfy topic; best-effort.

    Returns ``True`` if a notification was sent, ``False`` if it was skipped (no
    topic configured) or the POST failed. Never raises — alerting is a nicety
    the watchdog must not depend on.
    """
    topic = settings.ntfy_topic
    if not topic:
        return False
    headers = {"Title": title, "Priority": priority}
    if tags:
        headers["Tags"] = tags
    url = f"{settings.ntfy_url.rstrip('/')}/{topic}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            response = await http.post(
                url, content=message.encode("utf-8"), headers=headers
            )
            response.raise_for_status()
    except Exception as exc:
        _log.warning("ntfy notify failed (%s): %r", title, exc)
        return False
    return True
