"""Domain types for the determinism reviewer — the transitive ring.

The kernel CI check (``scripts/check_determinism.py``) flags nondeterministic
calls written *lexically* inside an ``@workflow.defn`` class. This loop catches
what the kernel structurally cannot: a hazard reached *transitively* — a
first-party helper, up to two call levels out from a workflow method, that hides
wall-clock, randomness, or I/O from the workflow. The static pass confirms the
call paths it can resolve; the ambiguous frontier (a risky third-party import at
a workflow module's scope) is handed to a model for a typed verdict.

Every type is :class:`~froot.domain.base.Frozen` so it serializes across the
Temporal boundary (the analyzer runs in an activity; its result rides back to
the workflow).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from froot.domain.base import Frozen


class Impurity(Frozen):
    """A single banned call site — the kernel matcher's output, as data."""

    rule: str = Field(min_length=1)
    """The resolved callee, e.g. ``datetime.datetime.now``."""
    hint: str = Field(min_length=1)
    """The sanctioned replacement, e.g. ``use workflow.now()``."""
    module: str = Field(min_length=1)
    """The first-party module the call site was found in (dotted qualname)."""
    line: int = Field(ge=1)
    """1-based line of the call site within its module."""


class HazardPath(Frozen):
    """A confirmed transitive hazard: a call path from a workflow to impurity.

    ``via`` is the chain of first-party symbols the static pass walked from the
    workflow class to the impurity (depth-bounded). It is never empty — an
    empty path would be a lexical hit (the kernel's job), not this loop's.
    """

    workflow: str = Field(min_length=1)
    """The originating workflow, ``module:ClassName``."""
    via: tuple[str, ...] = Field(min_length=1)
    """The first-party call chain, e.g. ``("plan_join", "_stamp")``."""
    impurity: Impurity
    """The banned call the chain reaches."""


class FrontierItem(Frozen):
    """A node the static pass can't resolve — a question for the model.

    The only v1 frontier is a risky third-party import at a workflow module's
    scope: static analysis can't tell whether it actually reaches the workflow
    boundary, so the model adjudicates.
    """

    kind: Literal["third_party_import"]
    workflow: str = Field(min_length=1)
    """A workflow in the module the item appears in, ``module:ClassName``."""
    module: str = Field(min_length=1)
    line: int = Field(ge=1)
    symbol: str = Field(min_length=1)
    """The import as written, e.g. ``import httpx``."""
    snippet: str
    """The source line, for the model's context."""


class FrontierVerdict(Frozen):
    """The model's typed judgment on one frontier item."""

    reaches: Literal["yes", "no", "uncertain"]
    """Whether the item reaches nondeterminism that breaks workflow replay."""
    rationale: str = Field(min_length=1)


class ReviewFinding(Frozen):
    """A surfaced finding — one line of the advisory comment.

    Either a static-confirmed transitive hazard or a model-confirmed frontier
    item. ``origin`` keeps the comment honest about how the finding was reached.
    """

    origin: Literal["static", "model"]
    workflow: str = Field(min_length=1)
    detail: str = Field(min_length=1)
    """Human-readable: the call path (static) or the model rationale (model)."""
    rule: str = Field(min_length=1)
    hint: str = Field(min_length=1)
    module: str = Field(min_length=1)
    line: int = Field(ge=1)


class AnalysisResult(Frozen):
    """The pure analyzer's output for one repo's workflow surface."""

    lexical: tuple[Impurity, ...] = ()
    """Calls the kernel already catches lexically — deduped out of findings."""
    hazards: tuple[HazardPath, ...] = ()
    """Static-confirmed transitive hazards."""
    frontier: tuple[FrontierItem, ...] = ()
    """Ambiguous items needing model adjudication."""


class PrReviewResult(Frozen):
    """The loop's recorded outcome for one PR review (a derived ledger row)."""

    pr_number: int = Field(ge=1)
    head_sha: str = Field(min_length=7)
    lexical_count: int = Field(ge=0)
    findings: tuple[ReviewFinding, ...] = ()
    comment_url: str | None = None
