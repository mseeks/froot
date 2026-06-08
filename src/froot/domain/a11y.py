"""Domain types for the source-level accessibility reviewer.

The mechanical sweep (:mod:`froot.policy.a11y_scan`) flags candidate a11y risk
sites in a PR's changed templates; the model adjudicates each *in context* into
one of three buckets, and the confirmed gaps become the advisory comment's
findings. This is the complement to the runtime axe checks an app's e2e suite
runs: it catches at the source level what a rendered check can only see at run
time, and it never merges — a human fixes what they agree is a defect.

Every type is :class:`~froot.domain.base.Frozen` so it serializes across the
Temporal boundary: the scan and the judge run in activities, and their results
ride back to the (deterministic) workflow.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from froot.domain.base import Frozen

A11yKind = Literal[
    "role-img",
    "svg",
    "labelable",
    "clickable-nonbutton",
    "image",
]
"""The high-signal source patterns the mechanical scan flags (five kinds)."""

Dialect = Literal["vue", "jsx"]
"""The template dialect: Vue (``@click``) vs JSX (``onClick``)."""

A11yBucket = Literal["gap", "ok", "judgment"]
"""The model's three verdicts: a real gap, accessible, or a judgment call."""


class A11yCandidate(Frozen):
    """A raw scan hit — a risk site the model must adjudicate in context.

    The per-line scan cannot see whether the accessible name / label / keyboard
    handler / alt sits on an adjacent line, so each candidate carries a
    ``context`` window for the model to read. ``label_wired`` records the one
    distant case the scan *can* resolve precisely (an id-wired ``<label for>`` /
    ``aria-labelledby`` for a labelable control), so the model needn't guess it.
    """

    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    kind: A11yKind
    dialect: Dialect
    detail: str = ""
    """The element tag, e.g. ``<input>``/``<div>`` — the model's context."""
    snippet: str = ""
    """The trimmed flagged line."""
    context: str = ""
    """A window of surrounding source lines — the model's evidence."""
    label_wired: bool = False
    """Labelable: an id-wired ``<label for>``/``aria-labelledby`` exists."""


class A11yVerdict(Frozen):
    """The model's typed adjudication of one candidate."""

    bucket: A11yBucket
    rationale: str = Field(min_length=1)
    citation: str = ""
    """The exact element/attribute the model observed (required for a gap)."""
    action: str = ""
    """The literal next step, when ``bucket == "gap"``."""


class A11yFinding(Frozen):
    """A surfaced finding — one item of the advisory comment.

    Only ``gap`` and ``judgment`` candidates become findings; an ``ok`` is
    dropped. A ``gap`` only reaches here with a citation (cite-or-omit),
    so ``what`` is always a real quoted observation, never an inference.
    """

    kind: A11yKind
    file: str = Field(min_length=1)
    line: int = Field(ge=1)
    bucket: Literal["gap", "judgment"]
    what: str = Field(min_length=1)
    """The quoted citation — the exact element/attribute observed."""
    why: str = Field(min_length=1)
    """The user impact (gap) or the precise ambiguity (judgment)."""
    action: str = ""


class A11yAnalysis(Frozen):
    """The scan's output for one PR's changed templates."""

    candidates: tuple[A11yCandidate, ...] = ()
    scanned_files: int = Field(default=0, ge=0)


class PrA11yResult(Frozen):
    """The loop's recorded outcome for one PR review (a derived ledger row)."""

    pr_number: int = Field(ge=1)
    head_sha: str = Field(min_length=7)
    candidates: int = Field(ge=0)
    findings: tuple[A11yFinding, ...] = ()
    comment_url: str | None = None
