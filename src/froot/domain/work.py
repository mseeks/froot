"""The work item: the bounded unit of work the chassis carries, for any loop.

A loop proposes one work item at a time; the spine shuttles it through the same
states and effects (judge → open PR → await CI → record → gate) regardless of
*what* it is. The kinds are heterogeneous on purpose — a bump moves a version, a
removal deletes dead weight — so they are a discriminated union, not a single
forced shape. Activities (the impure boundary) dispatch on ``kind`` to the right
signal, judge, and action; the pure spine never inspects the payload.

This is the first widening of the chassis past "a bump" — the seam that, taken
to its conclusion (an open loop registry), is froot's north star (see VISION).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from froot.domain.candidate import Candidate
from froot.domain.removal import Removal

# One bounded unit of work, of any loop's kind. ``kind`` discriminates so the
# Temporal data converter and the activities both route without guesswork.
WorkItem = Annotated[Candidate | Removal, Field(discriminator="kind")]
