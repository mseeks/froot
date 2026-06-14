"""Synthesize and render the doc-coherence reviewer's advisory comment (pure).

One marker-tagged comment per PR, upserted in place per head SHA. Advisory: the
loop never edits the doc. Two pure decisions, unit-tested apart from the model:

* :func:`synthesize_doc_coherence_findings` filters the agent's three-bucket map
  into findings, enforcing *cite-or-omit* — a ``drift`` with no quoted citation
  is dropped as a possible confabulation, so the comment only states what the
  agent could quote.
* :func:`should_post` decays the comment (post on findings or to clear a stale
  one). :func:`render_doc_coherence_comment` also reflects a run that could not
  complete, so a flaky model reads as "couldn't verify", not a false all-clear.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.doc_coherence import DocCoherenceFinding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from froot.domain.doc_coherence import DocCoherenceItem

DOC_COHERENCE_MARKER = "<!-- froot:doc-coherence -->"


def synthesize_doc_coherence_findings(
    items: Sequence[DocCoherenceItem],
) -> tuple[DocCoherenceFinding, ...]:
    """Filter the agent's map into surfaced findings (cite-or-omit).

    ``ok`` items are dropped; a ``drift`` is surfaced ONLY with a claim and a
    citation (an unquoted drift is a confabulation, suppressed); ``judgment``
    items keep their own section.
    """
    findings: list[DocCoherenceFinding] = []
    for item in items:
        what = item.what.strip()
        citation = item.citation.strip()
        if item.bucket == "drift":
            if not what or not citation:
                continue  # cite-or-omit
            findings.append(
                DocCoherenceFinding(
                    bucket="drift",
                    what=what,
                    why=item.why.strip() or "(no rationale given)",
                    action=item.action.strip(),
                    citation=citation,
                )
            )
        elif item.bucket == "judgment":
            label = what or citation
            if not label:
                continue
            findings.append(
                DocCoherenceFinding(
                    bucket="judgment",
                    what=label,
                    why=item.why.strip() or "(no rationale given)",
                    action=item.action.strip(),
                    citation=citation,
                )
            )
    return tuple(findings)


def should_post(*, has_findings: bool, comment_exists: bool) -> bool:
    """Whether to (re)post this tick — the decay rule.

    Post when there is something to say OR a prior comment must be cleared; a
    clean PR with no prior comment stays silent.
    """
    return has_findings or comment_exists


def render_doc_coherence_comment(
    findings: Sequence[DocCoherenceFinding],
    head_sha: str,
    *,
    completed: bool,
) -> str:
    """Render the marker-tagged comment body (always a body, for true decay)."""
    short = head_sha[:7]
    drift = [f for f in findings if f.bucket == "drift"]
    judgments = [f for f in findings if f.bucket == "judgment"]
    out = [DOC_COHERENCE_MARKER, "", "### 📚 froot doc coherence", ""]
    if not completed:
        out.append(
            "⚠ The semantic review could not complete this run (the model was "
            f"unavailable or hit its budget) at `{short}` — will retry on the "
            "next commit."
        )
        out.extend(["", _FOOTER])
        return "\n".join(out)
    if not findings:
        out.append(
            f"✅ No semantic doc drift found against the code at `{short}`."
        )
        out.extend(["", _FOOTER])
        return "\n".join(out)
    out.append(
        "Documentation that may have drifted from the code at "
        f"`{short}`. **Advisory** — a semantic pass; a human fixes what they "
        "agree is stale."
    )
    if drift:
        out.extend(["", "#### Drift — review & fix"])
        out.extend(_render(f) for f in drift)
    if judgments:
        out.extend(["", "#### Judgment calls (your call)"])
        out.extend(_render(f) for f in judgments)
    out.extend(["", _FOOTER])
    return "\n".join(out)


_FOOTER = "_Reviewed by froot · re-runs update this comment in place._"


def _render(f: DocCoherenceFinding) -> str:
    cite = f" (`{f.citation}`)" if f.citation else ""
    action = f" — _fix:_ {f.action}" if f.action else ""
    return f"- **{f.what}**{cite}\n  - {f.why}{action}"
