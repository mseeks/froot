"""The doc-refs loop: advisory comments on dangling documentation references.

Scans a repo's open PRs and upserts one decaying comment per PR on the changed
Markdown's broken links / file paths / make targets — no candidate, no PR of its
own, no gate, no merge. The runtime (the per-repo DocRefsReviewWorkflow + per-PR
PrDocRefsReviewWorkflow) is its own; this spec makes the loop a registry citizen
so the dashboard and config derive it uniformly with the others.
"""

from __future__ import annotations

from froot.domain.loop import Loop
from froot.loops.registry import AdvisoryTail, LoopSpec, register
from froot.policy.doc_refs_comment import DOC_REFS_MARKER

register(
    LoopSpec(
        loop=Loop.DOC_REFS,
        dashboard_icon="link",
        tail=AdvisoryTail(
            marker=DOC_REFS_MARKER,
            panel_title="Doc refs",
        ),
    )
)
