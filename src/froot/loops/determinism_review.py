"""The determinism-review loop: advisory comments on a PR's determinism risk.

Scans a repo's open PRs and upserts one decaying comment per PR on the
transitive Temporal-determinism hazards reachable from its workflows — no
candidate, no PR of its own, no gate, no merge. The runtime (ReviewWorkflow +
PrReviewWorkflow) is still its own; this spec makes the loop a registry
citizen so the dashboard and config derive it uniformly with the others.
"""

from __future__ import annotations

from froot.domain.loop import Loop
from froot.loops.registry import AdvisoryTail, LoopSpec, register
from froot.policy.review_comment import REVIEW_MARKER

register(
    LoopSpec(
        loop=Loop.DETERMINISM_REVIEW,
        dashboard_icon="search",
        tail=AdvisoryTail(
            marker=REVIEW_MARKER,
            panel_title="Determinism review",
        ),
    )
)
