"""The changelog and the model's verdict on it — the loop's one judgment.

froot is *spine-heavy, model-thin*: the deterministic spine decides when and
whether to act; the model's entire job is the typed judgment captured here —
*is this patch's changelog clean, or does it hint at hidden behavioral change?*
The verdict is **framing, not a gate**: every patch candidate is still proposed
(SPEC: propose, the human decides), and the verdict shapes the PR's description
and labels so the reviewing human triages faster.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.version import Version


class Changelog(Frozen):
    """The changelog text fetched for a candidate's target version.

    Attributes:
        package: The dependency the changelog belongs to.
        version: The target version the changelog describes.
        text: The raw changelog / release-notes text.
        source_url: Where the text came from (registry, GitHub release), if
            known — surfaced in the PR for the human to follow.
    """

    package: str = Field(min_length=1)
    version: Version
    text: str
    source_url: str | None = None


class CleanVerdict(Frozen):
    """The changelog reads as a clean, low-risk patch."""

    kind: Literal["clean"] = "clean"
    rationale: str


class RiskyVerdict(Frozen):
    """The changelog hints at behavior change worth a careful human look."""

    kind: Literal["risky"] = "risky"
    rationale: str
    concerns: tuple[str, ...] = ()


class UnknownVerdict(Frozen):
    """No changelog could be fetched or read, so risk is unassessed.

    Reached without spending a model call when there is nothing to judge — the
    spine does not ask the model to assess an empty changelog.
    """

    kind: Literal["unknown"] = "unknown"
    rationale: str


# The model's framing of a candidate's changelog.
ChangelogVerdict = Annotated[
    CleanVerdict | RiskyVerdict | UnknownVerdict,
    Field(discriminator="kind"),
]
