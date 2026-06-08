"""Synthesize and render the a11y reviewer's advisory comment (pure).

One marker-tagged comment per PR, upserted in place on each new head SHA (the
marker lets the forge find-and-update rather than stack comments — a reviewer
that spams is the entropy it exists to prevent). The comment is **advisory**:
the loop never merges, and a human fixes what they agree is a defect.

Two pure decisions live here, both unit-tested apart from the network:

* :func:`synthesize_a11y_findings` turns model verdicts into findings, enforcing
  *cite-or-omit* — a ``gap`` with no quoted citation is dropped as a possible
  confabulation, so the comment only ever states what the model actually saw.
* :func:`should_post` closes the decay gap the determinism reviewer leaves: it
  posts when there are findings *or* a prior comment exists, so a PR whose gaps
  were fixed gets its stale comment replaced with "all clear" rather than left
  behind — the signal decays as the debt is paid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.a11y import A11yFinding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from froot.domain.a11y import A11yCandidate, A11yVerdict

A11Y_MARKER = "<!-- froot:a11y-review -->"

_KIND_LABEL = {
    "role-img": "role=img / svg",
    "svg": "svg",
    "labelable": "form control",
    "clickable-nonbutton": "clickable non-button",
    "image": "image",
}


def synthesize_a11y_findings(
    candidates: Sequence[A11yCandidate],
    verdicts: Sequence[A11yVerdict],
) -> tuple[A11yFinding, ...]:
    """Combine candidates with their model verdicts into surfaced findings.

    ``candidates`` and ``verdicts`` are index-aligned (one verdict per
    candidate). ``ok`` verdicts are dropped (silence is the accessible case); a
    ``gap`` is surfaced ONLY when it carries a citation (cite-or-omit — an
    unquoted gap is a confabulation, suppressed); ``judgment`` items are kept
    in their own section. The strict ``zip`` makes a misaligned pair a loud
    ``ValueError`` rather than a silent mismatch.
    """
    findings: list[A11yFinding] = []
    for cand, verdict in zip(candidates, verdicts, strict=True):
        if verdict.bucket == "gap":
            citation = verdict.citation.strip()
            if not citation:
                continue  # cite-or-omit: no quote => not a finding
            findings.append(
                A11yFinding(
                    kind=cand.kind,
                    file=cand.file,
                    line=cand.line,
                    bucket="gap",
                    what=citation,
                    why=verdict.rationale,
                    action=verdict.action,
                )
            )
        elif verdict.bucket == "judgment":
            findings.append(
                A11yFinding(
                    kind=cand.kind,
                    file=cand.file,
                    line=cand.line,
                    bucket="judgment",
                    what=(
                        verdict.citation.strip()
                        or cand.snippet
                        or cand.detail
                        or cand.kind
                    ),
                    why=verdict.rationale,
                    action=verdict.action,
                )
            )
    return tuple(findings)


def should_post(*, has_findings: bool, comment_exists: bool) -> bool:
    """Whether to (re)post the comment this tick — the decay rule.

    Post when there is something to say OR a prior comment must be cleared. A
    clean PR that never had a comment stays silent; a PR whose
    gaps were fixed gets its comment overwritten with "all clear".
    """
    return has_findings or comment_exists


def render_a11y_comment(findings: Sequence[A11yFinding], head_sha: str) -> str:
    """Render the marker-tagged comment body (always a body, for true decay).

    With findings, the gap and judgment sections; with none, an explicit
    "all clear" so a fixed PR's comment reflects the new reality instead of
    lingering stale. :func:`should_post` decides whether this body is actually
    posted.
    """
    short = head_sha[:7]
    gaps = [f for f in findings if f.bucket == "gap"]
    judgments = [f for f in findings if f.bucket == "judgment"]
    out = [A11Y_MARKER, "", "### ♿ froot a11y review", ""]
    if not findings:
        out.append(
            "✅ No source-level a11y gaps in this PR's changed templates at "
            f"`{short}`."
        )
        out.extend(["", _FOOTER])
        return "\n".join(out)
    out.append(
        "Source-level accessibility risks in this PR's changed templates at "
        f"`{short}`. **Advisory** — a static pass beside the runtime a11y"
        " checks; a human fixes what they agree is a defect."
    )
    if gaps:
        out.extend(["", "#### A11y gap — review & fix"])
        out.extend(_render_gap(f) for f in gaps)
    if judgments:
        out.extend(["", "#### Judgment calls (your call)"])
        out.extend(_render_judgment(f) for f in judgments)
    out.extend(["", _FOOTER])
    return "\n".join(out)


_FOOTER = "_Reviewed by froot · re-runs update this comment in place._"


def _render_gap(f: A11yFinding) -> str:
    label = _KIND_LABEL.get(f.kind, f.kind)
    action = f" — _action:_ {f.action}" if f.action else ""
    return (
        f"- **`{f.file}:{f.line}`** · {label} — `{f.what}`\n  - {f.why}{action}"
    )


def _render_judgment(f: A11yFinding) -> str:
    label = _KIND_LABEL.get(f.kind, f.kind)
    return f"- **`{f.file}:{f.line}`** · {label} — `{f.what}`\n  - {f.why}"
