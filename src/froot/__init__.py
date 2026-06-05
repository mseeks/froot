"""froot — durable, self-scheduled code-maintenance loops on Temporal.

A loop watches a target repo for one class of decay, proposes a bounded fix as a
pull request, lets the repo's own CI verify it, and leaves the outcome behind as
a signal — while a human approves the merge. Two loops run today:
dependency-patch (npm + uv) and a determinism reviewer for Temporal workflows.
See ``SPEC.md`` for the what and the why.

The package is layered, strictly inward-depending:

* :mod:`froot.domain` — the pure, frozen, strongly-typed core. Illegal states
  are unrepresentable; no I/O, no framework.
* :mod:`froot.policy` — pure functions over the domain (candidate selection,
  deterministic naming, the loop state machine).
* :mod:`froot.ports` — typed Protocols for the impure world.
* :mod:`froot.adapters` — concrete implementations of the ports (npm and uv
  package managers, GitHub, the changelog source, the model judges — changelog
  risk and the determinism frontier — and telemetry).
* :mod:`froot.workflow` — the thin Temporal spine (workflows + activities) that
  drives the pure core and interprets its effects.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
