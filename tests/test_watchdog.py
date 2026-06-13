"""The liveness watchdog's alert decision (pure).

The I/O — list the configured loops, idempotently restart the dead ones — reuses
the starter's already-tested ``plans`` and the same failed-only start. The one
decision unique to the watchdog is *when to alert* — only when it actually
revived something. These pin that.
"""

from __future__ import annotations

from froot.watchdog import revival_alert


def test_no_alert_when_nothing_was_revived() -> None:
    assert revival_alert(()) is None


def test_alert_counts_and_lists_the_revived_loops() -> None:
    alert = revival_alert(("dead-code scan · mseeks/vibe-themer",))
    assert alert is not None
    title, message = alert
    assert "revived 1 dead loop" in title
    assert "vibe-themer" in message


def test_alert_pluralizes_the_count() -> None:
    alert = revival_alert(("a · x", "b · y"))
    assert alert is not None
    assert "revived 2 dead loops" in alert[0]
