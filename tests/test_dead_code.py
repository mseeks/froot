"""The dead-code loop's observe: bounded-concurrent safe-to-remove vetting.

A repo with a large backlog (vibe-themer flags ~70) must not serialize one ~30s
judgment after another past the scan ceiling — observe fans the judgments out
under a semaphore. This pins that it overlaps (not sequential), stays within the
bound, and preserves the flagged order.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

import froot.adapters.model_judge as model_mod
from froot.domain.changelog import ChangelogVerdict, CleanVerdict
from froot.domain.removal import Removal
from froot.loops.dead_code import _JUDGE_CONCURRENCY, observe
from tests.support import FakePackageManager, make_removal, make_repo

if TYPE_CHECKING:
    from froot.domain.dead_source import DeadExport, DeadFile


class _ConcurrencyJudge:
    """Records peak in-flight judgments, to prove the fan-out is concurrent."""

    def __init__(self) -> None:
        self.inflight = 0
        self.peak = 0
        self.calls = 0

    async def _judge(self) -> ChangelogVerdict:
        self.calls += 1
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            await asyncio.sleep(0.02)  # hold the slot so overlap is observable
        finally:
            self.inflight -= 1
        return CleanVerdict(rationale="ok")

    async def judge_removal(self, removal: Removal) -> ChangelogVerdict:
        return await self._judge()

    async def judge_dead_source(
        self, item: DeadFile | DeadExport
    ) -> ChangelogVerdict:
        return await self._judge()


async def test_observe_vets_concurrently_within_the_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = _ConcurrencyJudge()
    monkeypatch.setattr(model_mod, "PydanticAiJudge", lambda: judge)
    items = tuple(make_removal(package=f"pkg-{i}") for i in range(12))
    pm = FakePackageManager(unused=items)

    considered, kept = await observe(make_repo(), pm, Path())

    assert considered == 12
    assert judge.calls == 12
    # All clean -> all kept, in the flagged order (gather preserves it).
    assert [k.package for k in kept if isinstance(k, Removal)] == [
        f"pkg-{i}" for i in range(12)
    ]
    # Concurrency actually happened (sequential would peak at 1) and stayed
    # within the bound.
    assert 1 < judge.peak <= _JUDGE_CONCURRENCY
