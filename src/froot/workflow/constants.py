"""Operational constants for the froot workflows (sandbox-safe).

stdlib plus Temporal's own :class:`~temporalio.common.RetryPolicy` (a plain,
deterministic value object) — nothing here touches I/O or the clock, so the
module is safe to import inside a workflow.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

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

# Bound every activity's retries. The default policy retries forever, so a
# persistent fault (a deleted commit, a sustained GitHub outage, a genuinely
# broken tool) would loop invisibly; capping attempts makes it surface as a
# failed workflow in the dashboard's Failures panel instead. Permanent faults
# (a missing or invalid token) are already raised non-retryable by the adapters,
# so they stop on the first attempt regardless of this bound. Six attempts with
# the default exponential backoff (1s, 2s, 4s, …) ride out a transient blip.
TOOL_RETRY = RetryPolicy(maximum_attempts=6)
