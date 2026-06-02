"""Operational constants for the froot workflows (stdlib only, sandbox-safe)."""

from __future__ import annotations

from datetime import timedelta

# Generous per-activity ceiling for the tool-backed steps: a checkout + npm +
# git + a (possibly cold) local model call all fit; the bound only trips a hang.
ACTIVITY_TIMEOUT = timedelta(minutes=10)
# Reading CI status or setting labels is a quick GitHub API call.
CI_CHECK_TIMEOUT = timedelta(seconds=60)
# Dispatching a bump loop is a fast Temporal client call.
DISPATCH_TIMEOUT = timedelta(seconds=30)
# The durable CI wait: how often to poll, and how long before giving up. The
# wait is a workflow timer (durable, free while idle) — this is Temporal's
# sweet spot, so froot can sit on a slow CI run for an hour without holding any
# process open.
CI_POLL_INTERVAL = timedelta(minutes=1)
CI_WAIT_DEADLINE = timedelta(hours=1)
