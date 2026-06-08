"""The a11y-review loop: advisory comments on source-level a11y gaps.

Scans a repo's open PRs and upserts one decaying comment per PR on the changed
templates' accessibility gaps — no candidate, no PR of its own, no gate, no
merge. The runtime (the per-repo A11yReviewWorkflow + per-PR
PrA11yReviewWorkflow) is still its own; this spec makes the loop a registry
citizen so the dashboard and config derive it uniformly with the others.
"""

from __future__ import annotations

from froot.domain.loop import Loop
from froot.loops.registry import AdvisoryTail, LoopSpec, register
from froot.policy.a11y_comment import A11Y_MARKER

register(
    LoopSpec(
        loop=Loop.A11Y_REVIEW,
        dashboard_icon="accessibility",
        tail=AdvisoryTail(
            marker=A11Y_MARKER,
            panel_title="A11y review",
        ),
    )
)
