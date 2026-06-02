"""Compose the PR content and the outcome labels — pure, no model call.

Spine-heavy: the PR title/body and the labels are deterministic templates over
the candidate, the model's changelog verdict, and the terminal CI status. The
model already did its one job (the verdict); rendering text is mechanical, so it
costs no model round-trip. These are
the strings the forge writes — the human-facing half of "derive, never store".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from froot.domain.changelog import CleanVerdict, RiskyVerdict, UnknownVerdict
from froot.domain.ci import (
    CIAbsent,
    CIFailed,
    CIPassed,
    CIPending,
    CITimedOut,
)
from froot.domain.ecosystem import manifest_filename
from froot.domain.pull_request import PullRequestDraft
from froot.policy.naming import branch_name

if TYPE_CHECKING:
    from froot.domain.candidate import PatchCandidate
    from froot.domain.changelog import ChangelogVerdict
    from froot.domain.ci import CIStatus
    from froot.domain.outcome import LoopOutcome
    from froot.domain.repo import TargetRepo

_LABEL_NAMESPACE = "froot"


def _verdict_summary(verdict: ChangelogVerdict) -> str:
    """Render the model's changelog framing for the human reviewer."""
    match verdict:
        case CleanVerdict():
            return f"Changelog reads clean. {verdict.rationale}"
        case RiskyVerdict():
            concerns = "".join(f"\n- {concern}" for concern in verdict.concerns)
            return f"Review carefully. {verdict.rationale}{concerns}"
        case UnknownVerdict():
            return f"Changelog unavailable. {verdict.rationale}"
    assert_never(verdict)


def pull_request_draft(
    target: TargetRepo,
    candidate: PatchCandidate,
    verdict: ChangelogVerdict,
) -> PullRequestDraft:
    """Build the deterministic PR content for a bump (no model call).

    Args:
        target: The repo the PR is opened against (gives the base branch).
        candidate: The bump being proposed.
        verdict: The model's changelog framing, surfaced for the reviewer.

    Returns:
        A :class:`PullRequestDraft` ready for the forge to open.
    """
    manifest = manifest_filename(candidate.ecosystem)
    body = "\n".join(
        (
            f"Bumps `{candidate.package}` from {candidate.current} to "
            f"{candidate.target} ({manifest} + lockfile).",
            "",
            _verdict_summary(verdict),
            "",
            "---",
            "Opened by froot. froot does not merge; a human approves.",
        )
    )
    return PullRequestDraft(
        branch=branch_name(candidate),
        base=target.default_branch,
        title=f"deps: bump {candidate.package} to {candidate.target}",
        body=body,
    )


def _ci_label(status: CIStatus) -> str:
    """Map a terminal CI status to its PR label."""
    match status:
        case CIPassed():
            return "ci:passed"
        case CIFailed():
            return "ci:failed"
        case CIAbsent():
            return "ci:no-checks"
        case CITimedOut():
            return "ci:timed-out"
        case CIPending():
            return "ci:pending"
    assert_never(status)


def outcome_labels(outcome: LoopOutcome) -> tuple[str, ...]:
    """Derive the PR labels that record how a proposal fared.

    These labels are the human-readable signal-update: the next reader (a
    person, or a later reputation query) sees froot's verdict and the CI result
    on the PR itself — no separate store.
    """
    return (
        _LABEL_NAMESPACE,
        "dependency-patch",
        f"changelog:{outcome.verdict.kind}",
        _ci_label(outcome.ci),
    )
