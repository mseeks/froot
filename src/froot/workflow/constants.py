"""Operational constants for the froot workflows (sandbox-safe).

stdlib plus Temporal's own :class:`~temporalio.common.RetryPolicy` (a plain,
deterministic value object) — nothing here touches I/O or the clock, so the
module is safe to import inside a workflow.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio.common import RetryPolicy

# Per-activity ceiling for the tool-backed steps: a checkout + npm + git all
# fit; the bound only trips a hang. Model-bearing activities use the longer
# MODEL_ACTIVITY_TIMEOUT below.
ACTIVITY_TIMEOUT = timedelta(minutes=10)
# Model-bearing activities (judge_changelog, gate_review, the two adjudicators,
# and the dead-code scan) run a local Gemma that takes minutes per call — and
# the adjudicators make several in a row, over a PR's flagged items. Under the
# worker's raised activity concurrency those calls also contend for the one
# model and slow down, so the old 10-minute ceiling tripped a legitimately busy
# adjudication (it killed a dead-code scan in prod). Give them a generous
# ceiling, but pair it with a SHORT heartbeat timeout so a genuinely hung worker
# is caught in ~2 min instead of at the 20-min ceiling. The activity must
# heartbeat for the heartbeat timeout to bite — see `beating` in activities.py,
# which tickers around the model call.
MODEL_ACTIVITY_TIMEOUT = timedelta(minutes=20)
HEARTBEAT_TIMEOUT = timedelta(minutes=2)
HEARTBEAT_INTERVAL = timedelta(seconds=30)
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
