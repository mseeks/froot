"""The loop registry — the spine reads it instead of branching on the enum.

These guard the per-loop seams the registry owns: the disposition, the
changelog-judge framing, the reconcile trait, the PR-title verb, and the
dashboard icon — so a loop's identity stays single-sourced as loops multiply.
Behavior equivalence of each loop's ``observe`` is covered by the existing scan
tests, which now route through the registry.
"""

from __future__ import annotations

import pytest

from froot.adapters.model_judge import _loop_context
from froot.domain.loop import Loop
from froot.loops import registry
from froot.loops.registry import Disposition

_ACTING = (Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH, Loop.DEAD_CODE)


def test_acting_loops_registered_as_commit_or_revert() -> None:
    specs = {spec.loop: spec for spec in registry.all_specs()}
    for loop in _ACTING:
        assert specs[loop].disposition is Disposition.COMMIT_OR_REVERT


def test_title_prefix_is_the_per_loop_pr_verb() -> None:
    # The PR-title verb is a per-loop label single-sourced in the spec (not
    # derivable from the loop name), so a new loop carries its own.
    assert registry.commit_tail(Loop.DEPENDENCY_PATCH).title_prefix == "deps"
    assert registry.commit_tail(Loop.SECURITY_PATCH).title_prefix == "security"
    assert registry.commit_tail(Loop.DEAD_CODE).title_prefix == "dead-code"


def test_judge_context_present_for_changelog_loops_absent_for_dead_code() -> (
    None
):
    # Dependency- and security-patch judge a changelog in-loop (a framing line);
    # dead-code judges at the signal (a removal veto), so it carries no context.
    assert registry.commit_tail(Loop.DEPENDENCY_PATCH).judge_context is not None
    assert registry.commit_tail(Loop.SECURITY_PATCH).judge_context is not None
    assert registry.commit_tail(Loop.DEAD_CODE).judge_context is None


def test_loop_context_reads_the_registry() -> None:
    for loop in (Loop.DEPENDENCY_PATCH, Loop.SECURITY_PATCH):
        assert _loop_context(loop) == registry.commit_tail(loop).judge_context


def test_reconciles_true_for_bump_loops_false_for_dead_code() -> None:
    # Version-supersession reconcile only applies to version-bearing bumps; a
    # removal has no version to be overtaken, so dead-code declares it skips.
    assert registry.commit_tail(Loop.DEPENDENCY_PATCH).reconciles is True
    assert registry.commit_tail(Loop.SECURITY_PATCH).reconciles is True
    assert registry.commit_tail(Loop.DEAD_CODE).reconciles is False


def test_disposition_is_derived_from_the_tail_type() -> None:
    # The discriminant is the tail's TYPE — one conceptual field, not two
    # species. A CommitTail is commit-or-revert; an AdvisoryTail is emit-signal.
    from froot.loops.registry import AdvisoryTail, LoopSpec

    assert (
        registry.get(Loop.DEPENDENCY_PATCH).disposition
        is Disposition.COMMIT_OR_REVERT
    )
    advisory = LoopSpec(
        loop=Loop.DEPENDENCY_PATCH,
        dashboard_icon="search",
        tail=AdvisoryTail(marker="<!-- m -->", panel_title="Review"),
    )
    assert advisory.disposition is Disposition.EMIT_SIGNAL


def test_advisory_loops_registered_as_emit_signal() -> None:
    from froot.loops.registry import AdvisoryTail

    specs = {spec.loop: spec for spec in registry.all_specs()}
    for loop in (Loop.DETERMINISM_REVIEW, Loop.A11Y_REVIEW):
        spec = specs[loop]
        assert spec.disposition is Disposition.EMIT_SIGNAL
        assert isinstance(spec.tail, AdvisoryTail)
        assert spec.tail.marker and spec.tail.panel_title


def test_commit_tail_rejects_an_advisory_loop() -> None:
    # An advisory loop reaching an acting code path fails loudly, not silently.
    with pytest.raises(TypeError):
        registry.commit_tail(Loop.DETERMINISM_REVIEW)
