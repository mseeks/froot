"""Pure policy over the domain: no I/O, no framework, just business logic.

Three pure modules the spine leans on: :mod:`froot.policy.candidates` (which
available version is the right patch target), :mod:`froot.policy.naming` (the
deterministic branch and workflow ids that make the loop idempotent), and
:mod:`froot.policy.state_machine` (the loop's transitions, effects as data).
Everything here is unit-testable without Temporal, npm, GitHub, or a model.
"""
