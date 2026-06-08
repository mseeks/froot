"""Synthesize and render the determinism reviewer's advisory PR comment (pure).

One marker-tagged comment per PR, upserted in place on each new head SHA (the
marker lets the forge find-and-update rather than stack comments — a reviewer
that spams is the entropy it exists to prevent). Findings are synthesized from
the static transitive hazards and the model-adjudicated frontier; the comment is
advisory — the blocking gate is the kernel's ``Determinism`` CI check.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.determinism import ReviewFinding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from froot.domain.determinism import (
        FrontierItem,
        FrontierVerdict,
        HazardPath,
    )

REVIEW_MARKER = "<!-- froot:determinism-review -->"

_THIRD_PARTY_HINT = "move this dependency behind an activity"


def synthesize_findings(
    hazards: Sequence[HazardPath],
    frontier: Sequence[FrontierItem],
    verdicts: Sequence[FrontierVerdict],
) -> tuple[ReviewFinding, ...]:
    """Combine confirmed hazards and model-confirmed frontier into findings.

    ``frontier`` and ``verdicts`` are index-aligned (one verdict per item). Only
    items the model judged ``reaches == "yes"`` are surfaced; ``no`` and
    ``uncertain`` are dropped to keep the advisory comment high-signal.
    """
    findings: list[ReviewFinding] = [
        ReviewFinding(
            origin="static",
            workflow=h.workflow,
            detail=" → ".join((*h.via, h.impurity.rule)),
            rule=h.impurity.rule,
            hint=h.impurity.hint,
            module=h.impurity.module,
            line=h.impurity.line,
        )
        for h in hazards
    ]
    for item, verdict in zip(frontier, verdicts, strict=True):
        if verdict.reaches == "yes":
            findings.append(
                ReviewFinding(
                    origin="model",
                    workflow=item.workflow,
                    detail=verdict.rationale,
                    rule=item.symbol,
                    hint=_THIRD_PARTY_HINT,
                    module=item.module,
                    line=item.line,
                )
            )
    return tuple(findings)


def render_review_comment(
    findings: Sequence[ReviewFinding], head_sha: str
) -> str:
    """Render the marker-tagged comment body (always a body, for true decay).

    With findings, the hazard list; with none, an explicit all-clear so a PR
    whose hazards were fixed gets its comment overwritten instead of lingering
    stale. :func:`should_post` decides whether this body is actually posted.
    """
    out = [REVIEW_MARKER, "", "### 🧭 froot determinism review", ""]
    if not findings:
        out.append(
            "✅ No transitive determinism hazards reachable from this repo's "
            f"Temporal workflows at `{head_sha[:7]}`."
        )
        out.extend(
            ["", "_Reviewed by froot · re-runs update this comment in place._"]
        )
        return "\n".join(out)
    out.append(
        "Transitive determinism hazards reachable from this repo's "
        f"Temporal workflows at `{head_sha[:7]}`. **Advisory** — the "
        "blocking gate is the `Determinism` CI check; this loop catches "
        "what that lexical check can't see across calls."
    )
    out.append("")
    for finding in findings:
        origin = (
            "static call-path"
            if finding.origin == "static"
            else "model-assessed"
        )
        out.append(f"- **`{finding.rule}`** — {finding.hint}")
        out.append(
            f"  - reached from `{finding.workflow}`, "
            f"at `{finding.module}:{finding.line}` ({origin})"
        )
        out.append(f"  - path: `{finding.detail}`")
    out.extend(
        ["", "_Reviewed by froot · re-runs update this comment in place._"]
    )
    return "\n".join(out)


def should_post(*, has_findings: bool, comment_exists: bool) -> bool:
    """Whether to (re)post the comment this tick — the decay rule.

    Post when there is something to say OR a prior comment must be cleared. A
    clean PR that never had a comment stays silent; a PR whose hazards were
    fixed gets its comment overwritten with the all-clear.
    """
    return has_findings or comment_exists
