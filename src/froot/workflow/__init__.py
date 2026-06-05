"""The Temporal spine: thin workflows that drive the pure core.

The durable-loop chassis, shared by both loops. For dependency-patch,
:class:`~froot.workflow.scan_workflow` is the self-scheduling loop that
discovers candidates and dispatches a :class:`~froot.workflow.bump_workflow` per
bump; the bump workflow is a thin driver around
:func:`froot.policy.state_machine.advance`, interpreting each effect into an
activity (and a durable CI wait). The determinism reviewer mirrors the shape:
:class:`~froot.workflow.review_workflow` self-schedules and dispatches a
:class:`~froot.workflow.pr_review_workflow` per open PR. All nondeterminism
lives in :mod:`froot.workflow.activities`; the workflows use only pure state and
Temporal APIs, so they replay deterministically.
"""
