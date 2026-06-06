"""The environment fingerprint — what trust was earned *under* (§3.7).

MHE's "conditional" property: trust belongs to a task class *in a specific
environment*, and when the environment changes some trust resets. The dominant
piece of froot's judgment environment is the judge model — a changelog verdict
from ``gemma4:26b`` is not the same evidence as one from ``gemma4:e4b`` — so a
track record earned under one model must not silently transfer to another
("The model underneath changes... Trust drops from auto-merge back to
propose-plus-review until the new model re-earns it", §3.7).

froot stamps each PR with the environment it was opened under (a ``froot-env:``
label), and the gate counts only the record earned under the *current*
environment. A model swap therefore resets every class to unearned until fresh
PRs accrue — exactly the calibration window §3.7 prescribes, and with no failure
required, just a changed anchor. The slug is kept human-readable rather than an
opaque hash so a steward can see at a glance which environment earned the trust.

Today the fingerprint captures the model dimension; tools, permissions, and
codebase shape are the other dimensions §3.7 names, and fold in here when froot
learns to track them.
"""

from __future__ import annotations

import re
from typing import Final

_LABEL_PREFIX: Final = "froot-env:"
_SLUG_RE: Final = re.compile(r"[^a-z0-9]+")


def environment_slug(model: str) -> str:
    """A short, legible slug of the judgment environment (currently the model).

    ``gemma4:26b`` -> ``gemma4-26b``. Readable on purpose: the steward should be
    able to read which environment a class's trust was earned under.
    """
    slug = _SLUG_RE.sub("-", model.strip().lower()).strip("-")
    return slug or "unknown"


def env_label(model: str) -> str:
    """The label that stamps a PR with the environment it was opened under."""
    return _LABEL_PREFIX + environment_slug(model)


def env_from_labels(names: set[str]) -> str | None:
    """The environment slug recovered from a PR's ``froot-env:`` label.

    ``None`` if the PR carries no such stamp (opened before stamping existed — a
    prior environment by definition, so it does not count for the current one).
    """
    for name in names:
        if name.startswith(_LABEL_PREFIX):
            return name[len(_LABEL_PREFIX) :]
    return None
