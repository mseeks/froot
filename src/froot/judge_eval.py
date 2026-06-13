"""Scheduled judge eval: re-grade the golden changelogs against the live model.

froot's one model call is the changelog judgment, run on a local model a steward
can swap and that can drift over time — a drift CI never sees, because the judge
has no fixed inputs there. This entrypoint is the adversarial probe for that
bearing: it runs the *live* judge over the fixed golden set
(:mod:`froot.policy.judge_eval`), grades each reading against its known-right
answer, logs every case, and posts one ntfy alert naming the mismatches. It
stays silent when the judge still agrees with all of them.

Run it on a schedule (a k8s CronJob) like the liveness watchdog — a thin probe a
layer below the loops it vouches for, sharing none of their failure mode. It
needs only the model endpoint (``FROOT_OLLAMA_*``) and ``FROOT_NTFY_TOPIC`` for
the alert; no Temporal, no GitHub. A model that is *down* (not merely wrong)
makes the judge call raise, so the run fails loudly as a red Job — the honest
signal, distinct from a drift mismatch. Run as ``python -m froot.judge_eval``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from froot.domain.changelog import Changelog, ChangelogVerdict
    from froot.domain.loop import Loop
    from froot.policy.judge_eval import CaseOutcome

_log = logging.getLogger("froot.judge_eval")


class _Judge(Protocol):
    """The one capability the eval needs: read a changelog into a verdict.

    Narrower than the full :class:`~froot.ports.protocols.ModelJudge` on purpose
    — the eval depends only on :meth:`judge`, so an offline fake (and the live
    :class:`~froot.adapters.model_judge.PydanticAiJudge`) satisfies it directly.
    """

    async def judge(
        self, changelog: Changelog, loop: Loop = ...
    ) -> ChangelogVerdict: ...


async def _evaluate(judge: _Judge | None = None) -> None:
    """Grade the golden set against the live judge once; alert on mismatch."""
    from froot.adapters.model_judge import PydanticAiJudge
    from froot.adapters.ntfy import notify
    from froot.config.settings import NtfySettings
    from froot.policy.judge_eval import (
        GOLDEN,
        eval_alert,
        outcome,
        summarize,
    )

    judge = judge or PydanticAiJudge()  # the live Ollama judge by default
    outcomes: list[CaseOutcome] = []
    for case in GOLDEN:
        verdict = await judge.judge(case.changelog, case.loop)
        graded = outcome(case, verdict)
        outcomes.append(graded)
        _log.info(
            json.dumps(
                {
                    "event": "judge_eval_case",
                    "name": graded.name,
                    "expected_clean": graded.expect_clean,
                    "got": graded.got,
                    "passed": graded.passed,
                }
            )
        )
    summary = summarize(tuple(outcomes))
    _log.info(
        json.dumps(
            {
                "event": "judge_eval",
                "total": summary.total,
                "passed": summary.passed,
                "failed": len(summary.failures),
            }
        )
    )
    alert = eval_alert(summary)
    if alert is not None:
        title, message = alert
        await notify(
            NtfySettings(),
            title=title,
            message=message,
            tags="warning",
            priority="high",
        )


def main() -> None:
    """Console entrypoint: grade the golden set against the live judge once."""
    from froot.worker import configure_logging

    configure_logging()
    asyncio.run(_evaluate())


if __name__ == "__main__":
    main()
