"""The per-bump lifecycle workflow — a thin driver over the pure core.

One durable workflow per (repo, package, target), keyed by the deterministic
:func:`~froot.policy.naming.bump_workflow_id`, so a bump is proposed at most
once. It loops: take the pure state machine's next effect, run it as an activity
(or, for the CI wait, a durable poll-and-sleep), feed the resulting event back
to :func:`~froot.policy.state_machine.advance`, and repeat until ``Recorded``.
All nondeterminism is in the activities; the workflow uses only pure state and
Temporal's own time APIs, so replay is deterministic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from froot.domain.ci import CIStatus, CITimedOut, is_terminal
    from froot.domain.effects import (
        AwaitCi,
        ClosePullRequest,
        Effect,
        JudgeChangelog,
        OpenPullRequest,
        RecordOutcome,
    )
    from froot.domain.events import (
        ChangelogJudged,
        CiResolved,
        LoopEvent,
        OutcomeRecorded,
        PullRequestClosed,
        PullRequestReady,
    )
    from froot.domain.outcome import LoopOutcome
    from froot.domain.state import Recorded
    from froot.policy.state_machine import TransitionKind, advance, start
    from froot.workflow import activities
    from froot.workflow.constants import (
        ACTIVITY_TIMEOUT,
        CI_CHECK_TIMEOUT,
        CI_POLL_INTERVAL,
        CI_WAIT_DEADLINE,
        TOOL_RETRY,
    )
    from froot.workflow.types import (
        BumpParams,
        CiCheckInput,
        CloseInput,
        OpenPrInput,
        RecordInput,
    )

if TYPE_CHECKING:
    # Used only in the (non-workflow-decorated) helper signatures, so these are
    # type-only — unlike the run() signature, Temporal does not evaluate them.
    from froot.domain.pull_request import PullRequestRef
    from froot.domain.repo import TargetRepo


@workflow.defn
class BumpWorkflow:
    """The durable loop for a single dependency patch bump."""

    @workflow.run
    async def run(self, params: BumpParams) -> LoopOutcome:
        """Drive the pure state machine to a recorded outcome."""
        transition = start(params.candidate)
        while transition.effects:
            state = transition.next
            if len(transition.effects) != 1:
                raise ApplicationError(
                    f"non-linear transition ({len(transition.effects)} "
                    "effects)",
                    non_retryable=True,
                )
            event = await self._execute(params.target, transition.effects[0])
            transition = advance(state, event, close_on_red=params.close_on_red)
            if transition.kind is TransitionKind.REJECTED:
                raise ApplicationError(
                    f"rejected transition: {transition.reason}",
                    non_retryable=True,
                )
        final = transition.next
        if not isinstance(final, Recorded):
            raise ApplicationError(
                f"loop ended in non-terminal state: {final.kind}",
                non_retryable=True,
            )
        return final.outcome

    async def _execute(self, target: TargetRepo, effect: Effect) -> LoopEvent:
        """Interpret one effect into an activity (or a durable CI wait)."""
        match effect:
            case JudgeChangelog():
                verdict = await workflow.execute_activity(
                    activities.judge_changelog,
                    effect.candidate,
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=TOOL_RETRY,
                )
                return ChangelogJudged(verdict=verdict)
            case OpenPullRequest():
                pr = await workflow.execute_activity(
                    activities.open_pull_request,
                    OpenPrInput(
                        target=target,
                        candidate=effect.candidate,
                        verdict=effect.verdict,
                    ),
                    start_to_close_timeout=ACTIVITY_TIMEOUT,
                    retry_policy=TOOL_RETRY,
                )
                return PullRequestReady(pr=pr)
            case AwaitCi():
                status = await self._await_ci(target, effect.pr)
                return CiResolved(status=status)
            case ClosePullRequest():
                await workflow.execute_activity(
                    activities.close_pull_request,
                    CloseInput(
                        target=target,
                        pr=effect.pr,
                        failing=effect.failing,
                    ),
                    start_to_close_timeout=CI_CHECK_TIMEOUT,
                    retry_policy=TOOL_RETRY,
                )
                return PullRequestClosed()
            case RecordOutcome():
                await workflow.execute_activity(
                    activities.record_outcome,
                    RecordInput(target=target, outcome=effect.outcome),
                    start_to_close_timeout=CI_CHECK_TIMEOUT,
                    retry_policy=TOOL_RETRY,
                )
                return OutcomeRecorded()
        assert_never(effect)

    async def _await_ci(
        self, target: TargetRepo, pr: PullRequestRef
    ) -> CIStatus:
        """Durably poll the repo's CI until it resolves or the deadline."""
        deadline = workflow.now() + CI_WAIT_DEADLINE
        while True:
            status = await workflow.execute_activity(
                activities.check_ci,
                CiCheckInput(target=target, head_sha=pr.head_sha),
                start_to_close_timeout=CI_CHECK_TIMEOUT,
                retry_policy=TOOL_RETRY,
            )
            if is_terminal(status):
                return status
            if workflow.now() >= deadline:
                return CITimedOut()
            await workflow.sleep(CI_POLL_INTERVAL)
