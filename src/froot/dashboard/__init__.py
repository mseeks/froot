"""The read-model dashboard — froot's reputation, derived on read.

A small read-only HTTP surface the worker serves alongside the Temporal worker
(same process, same pod; reach it with ``kubectl port-forward``). On every
request it derives a 10,000ft view of the agent from the two truths froot
already owns — GitHub (the outcome ledger) and Temporal (the live run ledger)
— plus best-effort run telemetry from ClickHouse, and **stores nothing**.
That is froot obeying its own derived-state invariant: the dashboard is the
reputation read-model the SPEC calls for, not a database.

The package mirrors froot's layering:

* :mod:`~froot.dashboard.model` — the pure, frozen view types.
* :mod:`~froot.dashboard.read_model` — pure assembly + derived aggregates
  (track record, verification, judgment, the approval queue), fully testable.
* ``github_source`` / ``temporal_source`` / ``clickhouse_source`` — the impure
  readers, one per external truth, each degrading to an error string rather
  than raising.
* :mod:`~froot.dashboard.render` — a pure ``model -> HTML`` projection (inline
  CSS, no JavaScript, no network).
* :mod:`~froot.dashboard.server` — a dependency-free asyncio HTTP server that
  fans out the readers, assembles, and renders.

It is never imported by a workflow- or activity-decorated module, so httpx and
the Temporal client never enter the Temporal workflow sandbox graph.
"""

from __future__ import annotations
