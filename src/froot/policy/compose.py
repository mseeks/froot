"""Compose the PR content and the PR labels — pure, no model call.

Spine-heavy: the PR title/body are deterministic templates over the candidate
and the model's changelog verdict (the model already did its one job — the
verdict — so rendering the text costs no model round-trip). froot tags every PR
with one fixed pair of labels; the per-run changelog/CI signal lives in the
durable workflow history (and the structured outcome log), not as accumulating
labels on the PR.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, assert_never

from froot.domain.changelog import CleanVerdict, RiskyVerdict, UnknownVerdict
from froot.domain.ecosystem import (
    Ecosystem,
    lockfile_filename,
    manifest_filename,
)
from froot.domain.pull_request import PullRequestDraft
from froot.policy.naming import branch_name

if TYPE_CHECKING:
    from froot.domain.candidate import PatchCandidate
    from froot.domain.changelog import ChangelogVerdict
    from froot.domain.repo import TargetRepo

_LABEL_NAMESPACE = "froot"

# The fixed labels froot puts on every PR it opens. Deliberately just these two:
# they mark the PR as froot's dependency-patch work, nothing more. How the
# proposal fared (the changelog verdict, the CI result) is recorded durably in
# the workflow history, not layered onto the PR as labels that pile up across
# re-runs.
PR_LABELS: tuple[str, str] = (_LABEL_NAMESPACE, "dependency-patch")

# Tags the comment froot leaves when it closes one of its own PRs (red CI, or a
# reconcile sweep). The marker lets the close go through the idempotent
# upsert_issue_comment path, so a retried close edits its note in place instead
# of stacking a second one.
CLOSE_MARKER = "<!-- froot:closed -->"


def _changed_files(ecosystem: Ecosystem) -> str:
    """Describe which files a bump rewrites, for the PR body.

    The phrase must match the diff the human approver actually sees. npm
    rewrites both the manifest and the lockfile (``npm install
    --package-lock-only`` updates the dependency spec too); uv rewrites only the
    lockfile, because a patch stays within the existing ``pyproject.toml``
    constraint, so the manifest is left untouched.
    """
    match ecosystem:
        case Ecosystem.NPM:
            return f"{manifest_filename(ecosystem)} + lockfile"
        case Ecosystem.UV:
            return (
                f"{lockfile_filename(ecosystem)} only; "
                f"{manifest_filename(ecosystem)} unchanged"
            )
    assert_never(ecosystem)


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
    body = "\n".join(
        (
            f"Bumps `{candidate.package}` from {candidate.current} to "
            f"{candidate.target} ({_changed_files(candidate.ecosystem)}).",
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


def closed_on_red_comment(failing: tuple[str, ...]) -> str:
    """The note froot leaves when it closes a PR for failing CI.

    Names the failing checks (when GitHub reported them) so the human sees why
    without opening the checks tab, and states froot's contract: it will
    re-propose the same bump if a newer patch is published. Carries
    :data:`CLOSE_MARKER` so the close posts through the idempotent comment path.
    """
    checks = ", ".join(f"`{name}`" for name in failing)
    reason = f"CI did not pass ({checks})." if checks else "CI did not pass."
    return "\n".join(
        (
            CLOSE_MARKER,
            f"froot closed this PR: {reason}",
            "",
            "The change wasn't safe to merge, so froot won't leave it open. "
            "If a newer patch is published, froot will propose it fresh.",
        )
    )
