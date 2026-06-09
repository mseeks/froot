"""Integration test for the scan loop on a time-skipping test server.

Mocks the scan + dispatch activities to verify the fan-out: one dispatch per
selected candidate, and the tick's reported counts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from froot.domain.candidate import Candidate
from froot.workflow.runtime import DATA_CONVERTER
from froot.workflow.scan_workflow import ScanWorkflow
from froot.workflow.types import (
    DispatchInput,
    GateSelfTestInput,
    ReconcileInput,
    ScanCandidatesInput,
    ScanParams,
    ScanResult,
)
from tests.support import make_candidate, make_repo

_TASK_QUEUE = "froot-test-scan"
_dispatched: list[str] = []
_dispatched_loops: list[str] = []


@activity.defn(name="scan_candidates")
async def _mock_scan(params: ScanCandidatesInput) -> tuple[Candidate, ...]:
    return (
        make_candidate(package="alpha", current="1.0.0", target="1.0.1"),
        make_candidate(package="beta", current="2.0.0", target="2.0.1"),
    )


@activity.defn(name="dispatch_bump")
async def _mock_dispatch(params: DispatchInput) -> None:
    _dispatched.append(params.candidate.subject)
    _dispatched_loops.append(params.loop.value)


@activity.defn(name="reconcile_open_prs")
async def _mock_reconcile(params: ReconcileInput) -> int:
    return 1


@activity.defn(name="gate_selftest")
async def _mock_gate_selftest(params: GateSelfTestInput) -> tuple[str, ...]:
    return ()


_MOCKS: list[Callable[..., Any]] = [
    _mock_scan,
    _mock_dispatch,
    _mock_reconcile,
    _mock_gate_selftest,
]


async def _pydantic_client(env: WorkflowEnvironment) -> Client:
    config = env.client.config()
    config["data_converter"] = DATA_CONVERTER
    return Client(**config)


async def test_scan_dispatches_each_candidate():
    _dispatched.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[ScanWorkflow],
            activities=_MOCKS,
        ):
            result: ScanResult = await client.execute_workflow(
                ScanWorkflow.run,
                ScanParams(target=make_repo(), continuous=False),
                id="scan-test",
                task_queue=_TASK_QUEUE,
            )
    assert result.found == 2
    assert result.dispatched == 2
    assert result.reconciled == 1  # the reconcile sweep ran after dispatch
    assert sorted(_dispatched) == ["alpha", "beta"]


async def test_scan_threads_the_loop_to_dispatch():
    # A security-patch scan threads its loop through to every dispatched bump,
    # so the bump runs in the right branch/label/judge namespace.
    from froot.domain.loop import Loop

    _dispatched.clear()
    _dispatched_loops.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[ScanWorkflow],
            activities=_MOCKS,
        ):
            await client.execute_workflow(
                ScanWorkflow.run,
                ScanParams(
                    target=make_repo(),
                    continuous=False,
                    loop=Loop.SECURITY_PATCH,
                ),
                id="scan-security",
                task_queue=_TASK_QUEUE,
            )
    assert _dispatched_loops == ["security-patch", "security-patch"]


async def test_continuous_loop_keeps_running_and_redispatches():
    _dispatched.clear()
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _pydantic_client(env)
        async with Worker(
            client,
            task_queue=_TASK_QUEUE,
            workflows=[ScanWorkflow],
            activities=_MOCKS,
        ):
            handle = await client.start_workflow(
                ScanWorkflow.run,
                ScanParams(
                    target=make_repo(), interval_seconds=60, continuous=True
                ),
                id="scan-continuous",
                task_queue=_TASK_QUEUE,
            )
            # Advance past one interval: time-skipping fires the durable sleep,
            # so the loop continues-as-new into another tick rather than ending.
            await env.sleep(90)
            description = await handle.describe()
            await handle.terminate()
    assert description.status == WorkflowExecutionStatus.RUNNING
    assert len(_dispatched) >= 2  # at least the first tick dispatched both
