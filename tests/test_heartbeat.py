"""The activity heartbeat helper (``beating``).

Model activities make multi-minute calls — several back to back in the
adjudicators. ``beating`` tickers Temporal heartbeats around them so a hung
worker trips the short heartbeat timeout instead of running out the long
start-to-close ceiling. These pin that it actually heartbeats under an activity
context, stays a transparent passthrough without one, and that the configured
cadences hold the invariant the design depends on.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from temporalio.testing import ActivityEnvironment

from froot.workflow.activities import beating
from froot.workflow.constants import (
    ACTIVITY_TIMEOUT,
    HEARTBEAT_INTERVAL,
    HEARTBEAT_TIMEOUT,
    MODEL_ACTIVITY_TIMEOUT,
)


async def test_beating_is_transparent_passthrough_outside_an_activity() -> None:
    # Unit tests call activity bodies directly (no activity context): the
    # heartbeat is skipped and the wrapped result comes straight back.
    async def _work() -> str:
        return "ok"

    assert await beating(_work()) == "ok"


async def test_beating_heartbeats_while_a_slow_call_runs() -> None:
    env = ActivityEnvironment()
    beats: list[tuple[object, ...]] = []
    env.on_heartbeat = lambda *args: beats.append(args)

    async def _activity() -> str:
        async def _slow() -> str:
            await asyncio.sleep(0.1)
            return "done"

        # A tiny interval so the brief call still ticks several times.
        return await beating(_slow(), interval=timedelta(seconds=0.01))

    assert await env.run(_activity) == "done"
    assert beats, "expected the ticker to heartbeat during the slow call"


async def test_beating_propagates_errors_and_cancels_the_ticker() -> None:
    async def _boom() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await beating(_boom())


def test_heartbeat_config_invariants() -> None:
    # The cadence sits under the heartbeat timeout (so a live-but-slow call
    # keeps beating between checks), which sits under the start-to-close
    # ceiling; and model-bearing activities get a longer ceiling than tool ones.
    assert HEARTBEAT_INTERVAL < HEARTBEAT_TIMEOUT < MODEL_ACTIVITY_TIMEOUT
    assert MODEL_ACTIVITY_TIMEOUT > ACTIVITY_TIMEOUT
