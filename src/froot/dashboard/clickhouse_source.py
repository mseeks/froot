"""ClickHouse reader: trace-derived run telemetry (best-effort enrichment).

froot's spans land in ClickStack's ``otel_traces`` under ``ServiceName =
'froot-worker'``; this aggregates them into per-activity latencies and a health
count. It is deliberately *not* load-bearing: ClickHouse holds only a 3-day
window and froot emits no app metrics, so when it is unset or unreachable the
dashboard shows the panel as unavailable and leans on GitHub + Temporal. The
two queries are read-only and bounded to the retained window.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx

from froot.config.settings import ClickHouseSettings
from froot.dashboard.model import ActivityStat, RunTelemetry

_TIMEOUT: Final = 10.0
_WINDOW_DAYS: Final = 3

_TOTALS_SQL: Final = (
    "SELECT count() AS total_spans, "
    "countIf(StatusCode = 'Error') AS error_spans, "
    "max(Timestamp) AS last_activity "
    "FROM {db}.otel_traces "
    "WHERE ServiceName = 'froot-worker' "
    "AND Timestamp > now() - INTERVAL {days} DAY "
    "FORMAT JSON"
)
_ACTIVITIES_SQL: Final = (
    "SELECT replaceOne(SpanName, 'RunActivity:', '') AS name, "
    "count() AS count, "
    "round(avg(Duration) / 1e6, 1) AS avg_ms, "
    "round(max(Duration) / 1e6, 1) AS max_ms "
    "FROM {db}.otel_traces "
    "WHERE ServiceName = 'froot-worker' "
    "AND SpanName LIKE 'RunActivity:%' "
    "AND Timestamp > now() - INTERVAL {days} DAY "
    "GROUP BY name ORDER BY count DESC "
    "FORMAT JSON"
)


def _unavailable() -> RunTelemetry:
    """The empty, not-reached telemetry value."""
    return RunTelemetry(
        available=False,
        total_spans=0,
        error_spans=0,
        last_activity=None,
        window_days=_WINDOW_DAYS,
        activities=(),
    )


def _int(value: Any) -> int:
    """Coerce a ClickHouse JSON scalar (often a quoted 64-bit int) to int."""
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    """Coerce a ClickHouse JSON scalar to float."""
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _ch_datetime(value: Any) -> datetime | None:
    """Parse a ClickHouse ``DateTime64`` string as a UTC-aware datetime."""
    if not isinstance(value, str) or not value or value.startswith("1970"):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


async def _query(client: httpx.AsyncClient, sql: str) -> list[dict[str, Any]]:
    """Run one ``FORMAT JSON`` query and return its ``data`` rows."""
    resp = await client.post("/", content=sql)
    resp.raise_for_status()
    payload = resp.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


async def fetch() -> tuple[RunTelemetry, str | None]:
    """Read froot's run telemetry; returns ``(telemetry, error)``.

    ``error`` is ``"off"`` when ClickHouse is not configured, an error string
    when it is configured but unreachable, else ``None``.
    """
    settings = ClickHouseSettings()
    if not settings.url:
        return _unavailable(), "off"
    headers = {"X-ClickHouse-User": settings.user}
    if settings.password is not None:
        headers["X-ClickHouse-Key"] = settings.password.get_secret_value()
    db = settings.database
    try:
        async with httpx.AsyncClient(
            base_url=settings.url,
            timeout=_TIMEOUT,
            headers=headers,
            params={"database": db},
        ) as client:
            totals = await _query(
                client, _TOTALS_SQL.format(db=db, days=_WINDOW_DAYS)
            )
            activity_rows = await _query(
                client, _ACTIVITIES_SQL.format(db=db, days=_WINDOW_DAYS)
            )
    except (httpx.HTTPError, ValueError) as exc:
        return _unavailable(), f"{type(exc).__name__}: {exc}"

    head = totals[0] if totals else {}
    activities = tuple(
        ActivityStat(
            name=str(row.get("name", "")),
            count=_int(row.get("count")),
            avg_ms=_float(row.get("avg_ms")),
            max_ms=_float(row.get("max_ms")),
        )
        for row in activity_rows
    )
    return (
        RunTelemetry(
            available=True,
            total_spans=_int(head.get("total_spans")),
            error_spans=_int(head.get("error_spans")),
            last_activity=_ch_datetime(head.get("last_activity")),
            window_days=_WINDOW_DAYS,
            activities=activities,
        ),
        None,
    )
