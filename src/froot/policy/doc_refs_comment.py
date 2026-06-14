"""Synthesize and render the doc-refs reviewer's advisory comment (pure).

One marker-tagged comment per PR, upserted in place on each new head SHA (the
marker lets the forge find-and-update rather than stack comments). The comment
is **advisory**: the loop never edits the doc — the voice is the author's — it
just maps the dangling references for a human.

Two pure decisions live here, both unit-tested apart from the network:

* :func:`synthesize_doc_ref_findings` turns model verdicts into findings,
  enforcing *cite-or-omit* — a ``broken`` with no quoted reference is dropped as
  a possible confabulation, so the comment only states what the model saw.
* :func:`should_post` decays the comment: it posts when there are findings *or*
  a prior comment exists, so a PR whose refs were fixed gets its stale comment
  replaced with "all clear" rather than left behind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.doc_refs import DocRefFinding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from froot.domain.doc_refs import DocRefCandidate, DocRefVerdict

DOC_REFS_MARKER = "<!-- froot:doc-refs -->"

_KIND_LABEL = {
    "broken-link": "broken link",
    "missing-path": "missing file path",
    "missing-make": "removed make target",
}


def synthesize_doc_ref_findings(
    candidates: Sequence[DocRefCandidate],
    verdicts: Sequence[DocRefVerdict],
) -> tuple[DocRefFinding, ...]:
    """Combine candidates with their model verdicts into surfaced findings.

    ``candidates`` and ``verdicts`` are index-aligned (one verdict per
    candidate). ``intentional`` verdicts are dropped (the silent, fine case); a
    ``broken`` is surfaced ONLY when it carries a citation (cite-or-omit — an
    unquoted break is a confabulation, suppressed); ``judgment`` items keep
    their own section. The strict ``zip`` turns a misaligned pair into a loud
    ``ValueError`` rather than a silent mismatch.
    """
    findings: list[DocRefFinding] = []
    for cand, verdict in zip(candidates, verdicts, strict=True):
        if verdict.bucket == "broken":
            citation = verdict.citation.strip() or cand.referent
            if not verdict.citation.strip():
                continue  # cite-or-omit: no quote => not a finding
            findings.append(
                DocRefFinding(
                    kind=cand.kind,
                    file=cand.file,
                    line=cand.line,
                    bucket="broken",
                    referent=citation,
                    why=verdict.rationale,
                    action=verdict.action,
                    broken_by_pr=cand.broken_by_pr,
                )
            )
        elif verdict.bucket == "judgment":
            findings.append(
                DocRefFinding(
                    kind=cand.kind,
                    file=cand.file,
                    line=cand.line,
                    bucket="judgment",
                    referent=verdict.citation.strip() or cand.referent,
                    why=verdict.rationale,
                    action=verdict.action,
                    broken_by_pr=cand.broken_by_pr,
                )
            )
    return tuple(findings)


def should_post(*, has_findings: bool, comment_exists: bool) -> bool:
    """Whether to (re)post the comment this tick — the decay rule.

    Post when there is something to say OR a prior comment must be cleared. A
    clean PR that never had a comment stays silent; a PR whose refs were fixed
    gets its comment overwritten with "all clear".
    """
    return has_findings or comment_exists


def render_doc_refs_comment(
    findings: Sequence[DocRefFinding], head_sha: str
) -> str:
    """Render the marker-tagged comment body (always a body, for true decay)."""
    short = head_sha[:7]
    broken = [f for f in findings if f.bucket == "broken"]
    judgments = [f for f in findings if f.bucket == "judgment"]
    out = [DOC_REFS_MARKER, "", "### 🔗 froot doc references", ""]
    if not findings:
        out.append(
            f"✅ No dangling references in this PR's changed docs at `{short}`."
        )
        out.extend(["", _FOOTER])
        return "\n".join(out)
    out.append(
        "References in this PR's changed docs that resolve to nothing at "
        f"`{short}`. **Advisory** — a human fixes what they agree is stale."
    )
    if broken:
        out.extend(["", "#### Broken references — review & fix"])
        out.extend(_render_broken(f) for f in broken)
    if judgments:
        out.extend(["", "#### Judgment calls (your call)"])
        out.extend(_render_judgment(f) for f in judgments)
    out.extend(["", _FOOTER])
    return "\n".join(out)


_FOOTER = "_Reviewed by froot · re-runs update this comment in place._"


def _render_broken(f: DocRefFinding) -> str:
    label = _KIND_LABEL.get(f.kind, f.kind)
    cause = " · ⚠ removed by this PR" if f.broken_by_pr else ""
    action = f" — _action:_ {f.action}" if f.action else ""
    return (
        f"- **`{f.file}:{f.line}`** · {label} — `{f.referent}`{cause}\n"
        f"  - {f.why}{action}"
    )


def _render_judgment(f: DocRefFinding) -> str:
    label = _KIND_LABEL.get(f.kind, f.kind)
    return f"- **`{f.file}:{f.line}`** · {label} — `{f.referent}`\n  - {f.why}"
