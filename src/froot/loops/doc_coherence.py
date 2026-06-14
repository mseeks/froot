"""The doc-coherence loop: advisory comments on semantic documentation drift.

Scans a repo's open PRs and upserts one decaying comment per PR with the agentic
reviewer's three-bucket drift map — no candidate, no PR of its own, no gate, no
merge. The runtime (the per-repo DocCoherenceReviewWorkflow + per-PR
PrDocCoherenceReviewWorkflow + the read-only agentic executor) is its own; this
spec makes the loop a registry citizen so the dashboard and config derive it
uniformly with the others.
"""

from __future__ import annotations

from froot.domain.loop import Loop
from froot.loops.registry import AdvisoryTail, LoopSpec, register
from froot.policy.doc_coherence_comment import DOC_COHERENCE_MARKER

register(
    LoopSpec(
        loop=Loop.DOC_COHERENCE,
        dashboard_icon="docs",
        tail=AdvisoryTail(
            marker=DOC_COHERENCE_MARKER,
            panel_title="Doc coherence",
        ),
    )
)
