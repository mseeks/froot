"""Temporal reader: the live run ledger (scan loops + bump outcomes).

Reuses the worker's own connected client. Lists the durable scan loops (the
signal stage's heartbeat) and the per-bump workflows; for a completed bump it
reads the structured outcome from the workflow result (verdict + CI reading + PR
number), and for a terminated/failed one it recovers the human reason from
history. Everything is keyed off the deterministic workflow ids, so the
read-model joins to GitHub by PR number and to repos by id prefix without
parsing ambiguous slugs. Temporal keeps ~7 days, so this is the *recent* ledger;
GitHub is the durable one.

Never raises: a failure returns an error string and whatever was gathered.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from temporalio.client import WorkflowExecutionStatus

from froot.domain.base import Frozen

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from temporalio.client import Client, WorkflowExecution

# A backstop so a runaway visibility store can never spin this forever.
_MAX_PER_TYPE: Final = 500
# The owner/name slug out of a PR url — the repo-aware join key (see fetch).
_PR_URL: Final = re.compile(r"github\.com/([^/]+/[^/]+)/pull/\d+")


class ScanExecution(Frozen):
    """One scan-loop execution (there may be several per id across CAN)."""

    workflow_id: str
    status: str
    start: datetime | None


class BumpExecution(Frozen):
    """One bump workflow, with its outcome (if completed) or reason (if not).

    ``repo`` is the ``owner/name`` the PR was opened against, parsed from the
    outcome's PR url; it makes the GitHub join repo-aware so two repos' PRs that
    share a number cannot cross-attribute.
    """

    workflow_id: str
    status: str
    start: datetime | None
    close: datetime | None
    verdict: str | None
    ci: str | None
    pr_number: int | None
    repo: str | None
    reason: str | None


def _status(execution: WorkflowExecution) -> str:
    """Lowercase the Temporal status enum (``continued_as_new`` etc.)."""
    status = execution.status
    return status.name.lower() if status is not None else "unknown"


def _as_dict(result: object) -> dict[str, Any] | None:
    """Normalise a decoded workflow result to a dict (converter-agnostic)."""
    if isinstance(result, dict):
        return result
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        dumped = dump(mode="json")
        return dumped if isinstance(dumped, dict) else None
    return None


def _nested_kind(data: dict[str, Any], key: str) -> str | None:
    """Read ``data[key]["kind"]`` defensively (a discriminated-union tag)."""
    section = data.get(key)
    if isinstance(section, dict):
        kind = section.get("kind")
        if isinstance(kind, str):
            return kind
    return None


def _pr_number(data: dict[str, Any]) -> int | None:
    """Read ``data["pr"]["number"]`` defensively."""
    pr = data.get("pr")
    if isinstance(pr, dict):
        number = pr.get("number")
        if isinstance(number, int):
            return number
    return None


def _pr_repo(data: dict[str, Any]) -> str | None:
    """The ``owner/name`` slug from ``data["pr"]["url"]`` defensively."""
    pr = data.get("pr")
    url = pr.get("url") if isinstance(pr, dict) else None
    if isinstance(url, str):
        match = _PR_URL.search(url)
        if match is not None:
            return match.group(1)
    return None


class _Outcome(Frozen):
    """The bits of a completed bump's outcome the read-model joins on."""

    verdict: str | None
    ci: str | None
    pr_number: int | None
    repo: str | None


async def _outcome(client: Client, execution: WorkflowExecution) -> _Outcome:
    """A completed bump's outcome (verdict/ci/pr/repo), or all ``None``."""
    empty = _Outcome(verdict=None, ci=None, pr_number=None, repo=None)
    try:
        handle = client.get_workflow_handle(
            execution.id, run_id=execution.run_id
        )
        data = _as_dict(await handle.result())
    except Exception:  # best-effort enrichment — a bad decode is never fatal
        return empty
    if data is None:
        return empty
    return _Outcome(
        verdict=_nested_kind(data, "verdict"),
        ci=_nested_kind(data, "ci"),
        pr_number=_pr_number(data),
        repo=_pr_repo(data),
    )


async def _reason(client: Client, execution: WorkflowExecution) -> str | None:
    """Recover a terminated/failed bump's human reason from history."""
    try:
        handle = client.get_workflow_handle(
            execution.id, run_id=execution.run_id
        )
        found: str | None = None
        async for event in handle.fetch_history_events():
            terminated = event.workflow_execution_terminated_event_attributes
            if terminated.reason:
                found = terminated.reason
            failed = event.workflow_execution_failed_event_attributes
            if failed.failure.message:
                found = failed.failure.message
        return found
    except Exception:  # the reason is a nicety — never fail the page for it
        return None


type _Ledger = tuple[tuple[ScanExecution, ...], tuple[BumpExecution, ...]]


async def fetch(client: Client) -> tuple[_Ledger, str | None]:
    """Read froot's scan + bump executions (degrades to an error string)."""
    scans: list[ScanExecution] = []
    bumps: list[BumpExecution] = []
    try:
        async for execution in _take(
            client.list_workflows("WorkflowType = 'ScanWorkflow'")
        ):
            scans.append(
                ScanExecution(
                    workflow_id=execution.id,
                    status=_status(execution),
                    start=execution.start_time,
                )
            )
        async for execution in _take(
            client.list_workflows("WorkflowType = 'BumpWorkflow'")
        ):
            status = _status(execution)
            outcome = _Outcome(verdict=None, ci=None, pr_number=None, repo=None)
            reason: str | None = None
            if execution.status is WorkflowExecutionStatus.COMPLETED:
                outcome = await _outcome(client, execution)
            elif execution.status in (
                WorkflowExecutionStatus.TERMINATED,
                WorkflowExecutionStatus.FAILED,
            ):
                reason = await _reason(client, execution)
            bumps.append(
                BumpExecution(
                    workflow_id=execution.id,
                    status=status,
                    start=execution.start_time,
                    close=execution.close_time,
                    verdict=outcome.verdict,
                    ci=outcome.ci,
                    pr_number=outcome.pr_number,
                    repo=outcome.repo,
                    reason=reason,
                )
            )
    except Exception as exc:  # degrade to an error string, never crash the page
        return (tuple(scans), tuple(bumps)), f"{type(exc).__name__}: {exc}"
    return (tuple(scans), tuple(bumps)), None


async def _take(
    iterator: AsyncIterator[WorkflowExecution],
) -> AsyncIterator[WorkflowExecution]:
    """Yield at most :data:`_MAX_PER_TYPE` executions (a runaway backstop)."""
    seen = 0
    async for execution in iterator:
        yield execution
        seen += 1
        if seen >= _MAX_PER_TYPE:
            return
